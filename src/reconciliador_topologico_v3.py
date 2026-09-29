"""Fase 2 — reconciliador topológico endurecido (CSV v3).

Endurecimiento sobre la versión anterior:

- Presencia en L5X por parseo XML y coincidencia **exacta** de identidad,
  nunca por subcadena sobre el texto del archivo.
- Identidad = (PLC, alcance Controller/Program, tag base, miembro, AliasFor),
  de modo que dos tags locales iguales en programas distintos no se mezclan.
- Tres confianzas separadas (Física, Pertenencia_Lazo, Función_ISA) y la
  confianza final adopta siempre el **peor** nivel.
- Ningún grupo con problemas recibe acciones operativas: se sustituyen por
  CANDIDATO_ENTRADA / CANDIDATO_SALIDA / CANDIDATO_PID / REVISION_LAZO.
- No se asigna ningún número ISA nuevo: solo asociaciones topológicas.

El módulo es de solo lectura para toda base SQLite y para todo L5X.
"""
from __future__ import annotations

import csv
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

# --- Contratos de confianza y acción ---------------------------------------

_NIVEL = {'ALTA': 3, 'MEDIA': 2, 'BAJA': 1}


def worst_confidence(*levels: str) -> str:
    """La confianza final es siempre el PEOR nivel presente."""
    presentes = [n for n in levels if n in _NIVEL]
    if not presentes:
        return 'BAJA'
    return min(presentes, key=lambda n: _NIVEL[n])


ACCIONES_V3 = frozenset({
    'CANDIDATO_ENTRADA', 'CANDIDATO_SALIDA', 'CANDIDATO_PID',
    'REVISION_LAZO', 'SIN_LAZO', 'EXCLUIR_COMO_INSTRUMENTO',
    'CONSERVAR_SIN_CAMBIOS', 'REVISION_MANUAL',
})

_ACCION_POR_ROL = {
    'ENTRADA': 'CANDIDATO_ENTRADA',
    'SALIDA': 'CANDIDATO_SALIDA',
    'PID': 'CANDIDATO_PID',
}


def action_for(role: str, problems) -> str:
    """Un grupo con problemas nunca recibe acción operativa."""
    if problems:
        return 'REVISION_LAZO'
    return _ACCION_POR_ROL.get(role, 'REVISION_LAZO')


# --- Clasificación de elementos finales ------------------------------------

_MOTOR = re.compile(r'(?:^|[_\-\.])(?:MOTOR|BBA|BOMBA|VDF|VFD|DRIVE|VELOCIDAD|ARRANQUE|COMPRESOR|VENTILADOR)(?:[_\-\.]|$)', re.I)
_VALVULA = re.compile(r'(?:^|[_\-\.])(?:VALVULA|VALVE|FV|LV|PV|TV|XV|SV|CV)(?:[_\-\.]|$)', re.I)


def classify_output(operand: str) -> tuple[str, str]:
    """Un motor nunca se convierte en válvula ni recibe función ISA inventada."""
    texto = operand or ''
    if _MOTOR.search(texto):
        return 'MOTOR', ''
    if _VALVULA.search(texto):
        return 'VALVULA', 'V'
    return 'DESCONOCIDO', ''


def classify_input(operand: str) -> tuple[str, str]:
    """Variable ISA de una entrada física, solo con evidencia de nombre inequívoca."""
    tokens = [t for t in re.split(r'[_\-\.]', (operand or '').upper()) if t]
    codigos = [t for t in tokens if re.fullmatch(r'(?:F|P|L|T|I|S|A|C|D|Q|R)(?:T|IT)', t)]
    if len(codigos) == 1:
        return codigos[0][0], codigos[0][1:]
    return '', ''


def _alias_kind(alias_for: str) -> str:
    """Clasifica la dirección de módulo: entrada, salida o desconocida."""
    texto = (alias_for or '').upper()
    if re.search(r':I\.', texto) or re.search(r':I\[', texto):
        return 'ENTRADA'
    if re.search(r':O\.', texto) or re.search(r':O\[', texto):
        return 'SALIDA'
    return ''


# --- Identidad exacta -------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    plc: str
    scope: str
    base: str
    member: str = ''
    declaration_found: bool = False
    tag_type: str = ''
    data_type: str = ''
    alias_for: str = ''

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.plc.casefold(), self.scope.casefold(), self.base.casefold(), self.member.casefold())

    @property
    def qualified(self) -> str:
        return f'{self.base}{self.member}'


_RE_OPERANDO = re.compile(r'^\[?(\*?)([A-Za-z_][A-Za-z0-9_]*)((?:\.[A-Za-z0-9_\[\]]+|\[[^\]]*\])*)\]?$')


def split_operand(operand: str) -> tuple[str, str] | None:
    """Separa tag base y miembro estructurado sin romper rutas de módulo."""
    texto = (operand or '').strip().lstrip('\\')
    if not texto or not re.match(r'^[A-Za-z_]', texto):
        return None
    base = re.split(r'[.\[]', texto, maxsplit=1)[0]
    resto = texto[len(base):]
    if not base:
        return None
    return base, resto


@dataclass
class Asociacion:
    """Componente topológico: entrada(s) → controlador → salida(s)."""
    loop_id: str
    plc: str
    controller: Identity | None = None
    inputs: list[Identity] = field(default_factory=list)
    outputs: list[Identity] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    confianza_fisica: str = 'BAJA'
    confianza_pertenencia: str = 'BAJA'
    confianza_funcion: str = 'BAJA'

    @property
    def confianza_final(self) -> str:
        return worst_confidence(self.confianza_fisica, self.confianza_pertenencia, self.confianza_funcion)


# --- Topología --------------------------------------------------------------

_PIN_PV_PREFERIDOS = ('PV', 'MEASURED', 'VALOR', 'ENTRADA', 'SENSOR', 'IN', 'PROCESO')
_PIN_MV_PREFERIDOS = ('MV', 'CVEU', 'CV', 'COMMAND', 'OUT', 'SALIDA', 'COMANDO')
_NATIVO_PID = re.compile(r'^(?:PID|PIDE|PID01|PIDE01)$', re.I)

# Instrucciones nativas con semántica de lectura/escritura auditada.
_FIRMA_ESCRITURA = {
    'MOV': (0,), 'MOVE': (0,), 'COP': (0,), 'CPS': (0,),
    'OTE': (), 'OTL': (), 'OTU': (),
    'ADD': (0, 1), 'SUB': (0, 1), 'MUL': (0, 1), 'DIV': (0, 1),
    'SCP': (0, 1, 2, 3, 4),
}
_FIRMA_DESTINO = {
    'MOV': 1, 'MOVE': 1, 'COP': 1, 'CPS': 1, 'SCP': 5,
    'ADD': 2, 'SUB': 2, 'MUL': 2, 'DIV': 2,
}
_FIRMA_COIL = {'OTE', 'OTL', 'OTU'}
_FIRMA_LEE_BOOL = {'XIC', 'XIO', 'ONS'}


class Topologia:
    """Índice exacto de declaraciones, ocurrencias y aristas de datos."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.plc = self.path.stem
        self.controller = ''
        self.declarations: dict[tuple[str, str], Identity] = {}
        self.by_base: dict[str, list[Identity]] = defaultdict(list)
        self.edges: set[tuple[tuple, tuple]] = set()
        self.condition_edges: set[tuple[tuple, tuple]] = set()
        self.aoi_definitions: dict[str, dict] = {}
        self.aoi_control: dict[str, tuple[str, tuple[str, ...]]] = {}
        self._parse()

    # -- parseo ------------------------------------------------------------

    def _parse(self):
        root = ET.parse(self.path).getroot()
        controller = root.find('Controller')
        if controller is None:
            raise ValueError(f'L5X sin Controller: {self.path.name}')
        self.controller = controller.get('Name', '')
        if self.controller and self.controller.casefold() != self.plc.casefold():
            self.plc = self.controller
        self._declarations(controller, 'Controller')
        for program in controller.findall('Programs/Program'):
            self._declarations(program, f"Program:{program.get('Name', '')}")
        self._aoi_definitions(controller)
        for program in controller.findall('Programs/Program'):
            self._routines(program, f"Program:{program.get('Name', '')}")
        self._aoi_bodies(controller)

    def _declarar(self, element, scope: str, plc: str):
        nombre = element.get('Name', '')
        if not nombre:
            return
        clave = (scope.casefold(), nombre.casefold())
        if clave in self.declarations:
            raise ValueError(f'Declaración duplicada en {self.plc}: {scope}/{nombre}')
        identidad = Identity(
            plc=plc, scope=scope, base=nombre, member='', declaration_found=True,
            tag_type=element.get('TagType', ''), data_type=element.get('DataType', ''),
            alias_for=element.get('AliasFor', '') or '',
        )
        self.declarations[clave] = identidad
        self.by_base[nombre.casefold()].append(identidad)

    def _declarations(self, owner, scope: str):
        for elemento in owner.findall('Tags/Tag'):
            self._declarar(elemento, scope, self.plc)

    def _aoi_definitions(self, controller):
        for definicion in controller.findall('AddOnInstructionDefinitions/AddOnInstructionDefinition'):
            nombre = definicion.get('Name', '')
            parametros = {
                p.get('Name', ''): {
                    'usage': p.get('Usage', ''),
                    'data_type': p.get('DataType', ''),
                }
                for p in definicion.findall('Parameters/Parameter')
            }
            self.aoi_definitions[nombre] = parametros
            if self._cuerpo_es_control(definicion):
                entrada = self._pin_entrada(parametros)
                salidas = self._pines_salida(parametros)
                if entrada and salidas:
                    self.aoi_control[nombre] = (entrada, salidas)

    def _cuerpo_es_control(self, definicion) -> bool:
        for bloque in definicion.findall('.//Block'):
            if _NATIVO_PID.match(bloque.get('Type', '')):
                return True
        for invocacion in definicion.findall('.//AddOnInstruction'):
            nombre = invocacion.get('Name', '')
            if _NATIVO_PID.match(nombre):
                return True
            if nombre in self.aoi_control:
                return True
        return False

    @staticmethod
    def _pin_entrada(parametros: dict) -> str:
        candidatos = [n for n, p in parametros.items()
                      if p['usage'] == 'Input' and n.casefold() not in ('enablein',)]
        for preferido in _PIN_PV_PREFERIDOS:
            for nombre in candidatos:
                if nombre.upper() == preferido:
                    return nombre
        for nombre in candidatos:
            if parametros[nombre]['data_type'].upper() == 'REAL':
                return nombre
        return candidatos[0] if candidatos else ''

    @staticmethod
    def _pines_salida(parametros: dict) -> tuple[str, ...]:
        candidatos = [n for n, p in parametros.items()
                      if p['usage'] == 'Output' and n.casefold() not in ('enableout',)]
        preferidos = []
        for preferido in _PIN_MV_PREFERIDOS:
            for nombre in candidatos:
                if nombre.upper().startswith(preferido) and nombre not in preferidos:
                    preferidos.append(nombre)
        if preferidos:
            return tuple(preferidos)
        reales = [n for n in candidatos if parametros[n]['data_type'].upper() == 'REAL']
        return tuple(reales or candidatos)

    def _aoi_bodies(self, controller):
        for definicion in controller.findall('AddOnInstructionDefinitions/AddOnInstructionDefinition'):
            for routine in definicion.findall('Routines/Routine'):
                tipo = routine.get('Type', '')
                if tipo == 'FBD':
                    for hoja in routine.findall('FBDContent/Sheet'):
                        self._leer_fbd(hoja, 'AOI')
                elif tipo == 'RLL':
                    for rung in routine.findall('RLLContent/Rung'):
                        self._leer_rll(rung, 'AOI')
                elif tipo == 'ST':
                    for linea in routine.findall('STContent/Line'):
                        self._leer_st(linea)

    def _routines(self, program, scope: str):
        programa = program.get('Name', '')
        for routine in program.findall('Routines/Routine'):
            tipo = routine.get('Type', '')
            if tipo == 'FBD':
                for hoja in routine.findall('FBDContent/Sheet'):
                    self._leer_fbd(hoja, programa)
            elif tipo == 'RLL':
                for rung in routine.findall('RLLContent/Rung'):
                    self._leer_rll(rung, programa)
            elif tipo == 'ST':
                for linea in routine.findall('STContent/Line'):
                    self._leer_st(linea)

    # -- lenguajes ---------------------------------------------------------

    def _leer_fbd(self, hoja, programa: str):
        nodos = {}
        for nodo in hoja:
            if nodo.tag in ('IRef', 'ORef', 'Block', 'AddOnInstruction'):
                nodos[nodo.get('ID')] = nodo
        for cable in hoja.findall('Wire'):
            origen = nodos.get(cable.get('FromID'))
            destino = nodos.get(cable.get('ToID'))
            if origen is None or destino is None:
                continue
            self._arista_nodo(origen, programa, destino)

    def _arista_nodo(self, origen, programa: str, destino):
        de = self.resolve_operand(origen.get('Operand', ''), programa)
        a = self.resolve_operand(destino.get('Operand', ''), programa)
        if de is None or a is None or de.key == a.key:
            return
        self.edges.add((de.key, a.key))

    def _leer_rll(self, rung, programa: str):
        texto = ''.join(t for t in rung.find('Text').itertext()) if rung.find('Text') is not None else ''
        if not texto.strip():
            return
        lecturas, escrituras = [], []
        for nombre, argumentos in _llamadas(texto):
            superior = nombre.upper()
            if superior in _FIRMA_COIL:
                if argumentos:
                    escrituras.append(argumentos[0])
                continue
            indice = _FIRMA_DESTINO.get(superior)
            if indice is not None and len(argumentos) > indice:
                indices_lectura = _FIRMA_ESCRITURA.get(superior, ()) or tuple(range(indice))
                lecturas.extend(argumentos[i] for i in indices_lectura if i < len(argumentos))
                escrituras.append(argumentos[indice])
                continue
            if superior in _FIRMA_ESCRITURA:
                indices = _FIRMA_ESCRITURA[superior]
                lecturas.extend(argumentos[i] for i in indices if i < len(argumentos))
                continue
            if superior in _FIRMA_LEE_BOOL:
                if argumentos:
                    lecturas.append(argumentos[0])
                continue
            definicion = self.aoi_definitions.get(nombre, {})
            if definicion:
                for posicion, valor in enumerate(argumentos):
                    nombre_param = list(definicion)[posicion] if posicion < len(definicion) else ''
                    if definicion.get(nombre_param, {}).get('usage') == 'Output':
                        escrituras.append(valor)
                    else:
                        lecturas.append(valor)
                continue
            lecturas.extend(argumentos)
        self._aristas_rung(lecturas, escrituras, programa)

    def _leer_st(self, linea):
        texto = ''.join(linea.itertext())
        if not texto.strip():
            return
        for sentencia in _sentencias_st(texto):
            izquierda, derecha = sentencia
            escrituras = [izquierda]
            lecturas = _referencias_st(derecha)
            self._aristas_st(lecturas, escrituras)

    def _aristas_st(self, lecturas, escrituras):
        for lectura in lecturas:
            de = self.resolve_operand(lectura, None)
            if de is None:
                continue
            for destino in escrituras:
                a = self.resolve_operand(destino, None)
                if a is None or de.key == a.key:
                    continue
                self.edges.add((de.key, a.key))

    def _aristas_rung(self, lecturas, escrituras, programa: str):
        resueltas_lectura = [self.resolve_operand(x, programa) for x in lecturas]
        resueltas_escritura = [self.resolve_operand(x, programa) for x in escrituras]
        resueltas_lectura = [x for x in resueltas_lectura if x is not None]
        resueltas_escritura = [x for x in resueltas_escritura if x is not None]
        for de in resueltas_lectura:
            for a in resueltas_escritura:
                if de.key == a.key:
                    continue
                self.condition_edges.add((de.key, a.key))

    # -- consultas ---------------------------------------------------------

    def find_exact(self, base: str) -> list[Identity]:
        return list(self.by_base.get((base or '').casefold(), ()))

    def scope_ambiguous(self, base: str) -> bool:
        return len({x.scope.casefold() for x in self.find_exact(base)}) > 1

    def resolve_operand(self, operand: str, programa: str | None) -> Identity | None:
        recorte = split_operand(operand)
        if recorte is None:
            return None
        base, miembro = recorte
        if programa:
            local = self.declarations.get((f'Program:{programa}'.casefold(), base.casefold()))
            if local is not None:
                return Identity(**{**local.__dict__, 'member': miembro})
        global_ = self.declarations.get(('Controller'.casefold(), base.casefold()))
        if global_ is not None:
            return Identity(**{**global_.__dict__, 'member': miembro})
        return Identity(plc=self.plc, scope='DESCONOCIDO', base=base, member=miembro)

    def physical_evidence(self, identity: Identity | None) -> str:
        if identity is None:
            return ''
        declaracion = self.declarations.get((identity.scope.casefold(), identity.base.casefold()))
        if declaracion is None:
            return ''
        return _alias_kind(declaracion.alias_for)

    def has_identity_edge(self, origen: str, destino: str) -> bool:
        def claves(base):
            return {x.key for x in self.find_exact(base)}
        for de in claves(origen):
            for a in claves(destino):
                if (de, a) in self.edges or (de, a) in self.condition_edges:
                    return True
        return False


# --- Utilidades de texto neutral / IEC -------------------------------------


def _llamadas(texto: str):
    """Devuelve (nombre, argumentos) de cada llamada instrucción del renglón."""
    resultado = []
    for coincidencia in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*)\s*\(', texto):
        nombre = coincidencia.group(1)
        inicio = coincidencia.end()
        profundidad = 1
        posicion = inicio
        while posicion < len(texto) and profundidad:
            caracter = texto[posicion]
            if caracter == '(':
                profundidad += 1
            elif caracter == ')':
                profundidad -= 1
            posicion += 1
        if profundidad:
            continue
        argumentos = _dividir_argumentos(texto[inicio:posicion - 1])
        resultado.append((nombre, argumentos))
    return resultado


def _dividir_argumentos(texto: str) -> list[str]:
    argumentos, profundidad, actual = [], 0, []
    for caracter in texto:
        if caracter in '([':
            profundidad += 1
        elif caracter in ')]':
            profundidad -= 1
        if caracter == ',' and profundidad == 0:
            argumentos.append(''.join(actual).strip())
            actual = []
            continue
        actual.append(caracter)
    ultimo = ''.join(actual).strip()
    if ultimo:
        argumentos.append(ultimo)
    return [a for a in argumentos if a and not re.fullmatch(r'[-\d\.]+|\?', a)]


_RE_ST_ASIGNA = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_\.\[\]]*)\s*:=\s*(.+?);?\s*$', re.S)


def _sentencias_st(texto: str):
    for linea in texto.splitlines():
        limpia = re.sub(r'\(\*.*?\*\)', ' ', linea)
        coincidencia = _RE_ST_ASIGNA.match(limpia)
        if coincidencia:
            yield coincidencia.group(1), coincidencia.group(2)


def _referencias_st(expresion: str):
    return [x for x in re.findall(r'[A-Za-z_][A-Za-z0-9_\.\[\]]*', expresion)
            if not re.fullmatch(r'\d+', x)]


# --- Construcción de asociaciones ------------------------------------------


def build_associations(topologia: Topologia) -> list[Asociacion]:
    """Agrupa entrada → controlador → salida por conexión real, sin numerar."""
    grupos: list[Asociacion] = []
    entrantes = defaultdict(list)
    salientes = defaultdict(list)
    # Orden determinista: el conjunto de aristas no garantiza orden estable
    # entre procesos, y el trazado debe dar el mismo resultado siempre.
    for de, a in sorted(topologia.edges):
        entrantes[a].append(de)
        salientes[de].append(a)

    for identidad in _controladores(topologia):
        inputs = _ascendente(topologia, entrantes, identidad)
        outputs = _descendente(topologia, salientes, identidad)
        problemas = []
        if not inputs:
            problemas.append('entrada física no demostrada')
        if not outputs:
            problemas.append('elemento final no demostrado')
        if len(inputs) > 1:
            problemas.append('múltiples entradas')
        if len(outputs) > 1:
            problemas.append('múltiples destinos')
        grupo = Asociacion(
            loop_id=f'{topologia.plc}/{identidad.scope}/{identidad.base}',
            plc=topologia.plc,
            controller=identidad,
            inputs=inputs,
            outputs=outputs,
            problems=sorted(set(problemas)),
        )
        grupo.confianza_pertenencia = 'BAJA' if problemas else 'ALTA'
        grupo.confianza_fisica = 'ALTA' if (inputs and outputs) else 'BAJA'
        grupo.confianza_funcion = 'ALTA' if all(
            classify_output(o.base)[0] == 'VALVULA' for o in outputs) else 'BAJA'
        grupos.append(grupo)
    _marcar_extremos_compartidos(grupos)
    return sorted(grupos, key=lambda g: g.loop_id)


def _marcar_extremos_compartidos(grupos: list[Asociacion]):
    """Un extremo usado por más de un controlador es ambiguo y bloquea candidatos."""
    duenos: dict[tuple, set] = defaultdict(set)
    for grupo in grupos:
        dueno = grupo.controller.key if grupo.controller else None
        for identidad in (*grupo.inputs, *grupo.outputs):
            duenos[identidad.key].add(dueno)
    for grupo in grupos:
        compartido = any(len(duenos[i.key]) > 1 for i in (*grupo.inputs, *grupo.outputs))
        if compartido and 'extremo compartido entre lazos' not in grupo.problems:
            grupo.problems = sorted({*grupo.problems, 'extremo compartido entre lazos'})
            grupo.confianza_pertenencia = 'BAJA'
            grupo.confianza_fisica = 'BAJA'


def _controladores(topologia: Topologia) -> list[Identity]:
    encontrados, vistos = [], set()
    definiciones_control = {nombre.casefold() for nombre in topologia.aoi_control}
    for identidad in topologia.declarations.values():
        if identidad.key in vistos:
            continue
        tipo = (identidad.data_type or '').casefold()
        if tipo in definiciones_control or _NATIVO_PID.match(identidad.data_type or ''):
            vistos.add(identidad.key)
            encontrados.append(identidad)
    return encontrados


def _ascendente(topologia: Topologia, entrantes, origen: Identity, limite: int = 12) -> list[Identity]:
    """Sube por aristas de datos hasta encontrar entradas físicas."""
    vistos, pendientes, fisicas = {origen.key}, list(entrantes.get(origen.key, ())), []
    while pendientes:
        clave = pendientes.pop(0)
        if clave in vistos:
            continue
        vistos.add(clave)
        identidad = _identidad_por_clave(topologia, clave)
        if identidad is None:
            continue
        evidencia = topologia.physical_evidence(identidad)
        if evidencia == 'ENTRADA':
            fisicas.append(identidad)
            continue
        if evidencia == 'SALIDA':
            continue
        if len(vistos) > limite:
            continue
        pendientes.extend(sorted(entrantes.get(clave, ())))
    return _deduplicar(fisicas)


def _descendente(topologia: Topologia, salientes, origen: Identity, limite: int = 12) -> list[Identity]:
    vistos, pendientes, fisicas = {origen.key}, list(salientes.get(origen.key, ())), []
    while pendientes:
        clave = pendientes.pop(0)
        if clave in vistos:
            continue
        vistos.add(clave)
        identidad = _identidad_por_clave(topologia, clave)
        if identidad is None:
            continue
        evidencia = topologia.physical_evidence(identidad)
        if evidencia == 'SALIDA':
            fisicas.append(identidad)
            continue
        if evidencia == 'ENTRADA':
            continue
        if len(vistos) > limite:
            continue
        pendientes.extend(sorted(salientes.get(clave, ())))
    return _deduplicar(fisicas)


def _identidad_por_clave(topologia: Topologia, clave: tuple) -> Identity | None:
    plc, scope, base, member = clave
    declaracion = topologia.declarations.get((scope, base))
    if declaracion is None:
        return None
    return Identity(**{**declaracion.__dict__, 'member': member})


def _deduplicar(items: list[Identity]) -> list[Identity]:
    vistos, resultado = set(), []
    for item in items:
        if item.key in vistos:
            continue
        vistos.add(item.key)
        resultado.append(item)
    return resultado


# --- Reconciliación con el histórico ---------------------------------------


def parse_l5x_v3(path) -> Topologia:
    return Topologia(path)


def _connect_ro(path) -> sqlite3.Connection:
    ruta = Path(path).resolve(strict=True)
    conexion = sqlite3.connect(ruta.as_uri() + '?mode=ro', uri=True)
    conexion.row_factory = sqlite3.Row
    conexion.execute('PRAGMA query_only=ON')
    return conexion


def _leer_catalogo(path) -> list[dict]:
    with closing(_connect_ro(path)) as conexion:
        filas = conexion.execute('''
            SELECT t.*, a.codigo AS area, v.letra AS variable, f.letra AS funcion
              FROM tags t
              JOIN areas a ON a.id=t.area_id
              JOIN variables v ON v.id=t.variable_id
              JOIN funciones f ON f.id=t.funcion_id
             ORDER BY t.id
        ''').fetchall()
    return [dict(f) for f in filas]


_RE_MIGRADO = re.compile(r'^\s*Migrado\s+de\s+(.+?)\s*$', re.I | re.S)


def _nombre_historico(row: dict) -> str:
    coincidencia = _RE_MIGRADO.match(row.get('descripcion') or '')
    return coincidencia.group(1).strip() if coincidencia else ''


CAMPOS_V3 = [
    'PLC_Origen', 'Tag_Anterior', 'Tag_Original_PLC', 'Encontrado_L5X',
    'Alcance', 'Rol_Propuesto', 'Area', 'Variable', 'Funcion',
    'Loop_ID', 'Confianza_Fisica', 'Confianza_Pertenencia_Lazo',
    'Confianza_Funcion_ISA', 'Confianza_Final', 'Accion', 'Motivo',
]


def reconstruir_v3(backup_db, current_db, l5x_dir, output_csv) -> dict:
    """Regenera el CSV v3 desde los 693 históricos, los 10 L5X y la base actual."""
    salida = Path(output_csv)
    if salida.suffix.lower() != '.csv':
        raise ValueError('La salida debe ser un archivo CSV')
    historicos = _leer_catalogo(backup_db)
    actuales = _leer_catalogo(current_db)
    protegidos = {r['tag_completo'] for r in actuales}

    topologias = {}
    for archivo in sorted(Path(l5x_dir).glob('*.L5X')):
        topologias[archivo.stem] = Topologia(archivo)

    indice_global: dict[str, list[tuple[str, Identity]]] = defaultdict(list)
    for plc, topologia in topologias.items():
        for identidad in topologia.declarations.values():
            indice_global[identidad.base.casefold()].append((plc, identidad))

    asociaciones = []
    for topologia in topologias.values():
        asociaciones.extend(build_associations(topologia))

    filas = []
    for row in historicos:
        filas.append(_fila_historica(row, indice_global, asociaciones, protegidos))
    filas.extend(_filas_descubiertas(topologias, asociaciones))

    salida.parent.mkdir(parents=True, exist_ok=True)
    with salida.open('w', encoding='utf-8-sig', newline='') as destino:
        escritor = csv.DictWriter(destino, fieldnames=CAMPOS_V3, delimiter=';')
        escritor.writeheader()
        escritor.writerows(filas)
    return _metricas(filas, asociaciones, historicos, actuales)


def _fila_historica(row, indice_global, asociaciones, protegidos) -> dict:
    anterior = row['tag_completo']
    raw = _nombre_historico(row)
    candidatos = indice_global.get(raw.casefold(), []) if raw else []
    encontrado = bool(candidatos)
    if anterior in protegidos:
        accion, motivo = 'CONSERVAR_SIN_CAMBIOS', 'Registro presente en la base actual protegida'
        rol = 'PROTEGIDO_MANUAL'
    elif not raw:
        accion, motivo, rol = 'REVISION_MANUAL', 'Sin nombre PLC en la descripción', 'IDENTIDAD_NO_RECUPERADA'
    elif not encontrado:
        accion, motivo, rol = 'REVISION_MANUAL', 'Identidad no declarada en los L5X seleccionados', 'NO_ENCONTRADO'
    else:
        relacionadas = [a for a in asociaciones
                        if a.controller and a.controller.base.casefold() == raw.casefold()]
        if relacionadas:
            accion, motivo, rol = 'CANDIDATO_PID', 'Instancia de control demostrada por topología', 'PID'
        else:
            accion, motivo, rol = 'SIN_LAZO', 'Identidad declarada sin relación de lazo demostrada', 'SIN_LAZO'
    alcance = candidatos[0][1].scope if candidatos else ''
    return {
        'PLC_Origen': row.get('plc_origen') or '',
        'Tag_Anterior': anterior,
        'Tag_Original_PLC': raw,
        'Encontrado_L5X': 'SI' if encontrado else 'NO',
        'Alcance': alcance,
        'Rol_Propuesto': rol,
        'Area': row['area'], 'Variable': row['variable'], 'Funcion': row['funcion'],
        'Loop_ID': ' | '.join(sorted({a.loop_id for a in
                                      (x for x in asociaciones
                                       if x.controller and x.controller.base.casefold() == (raw or '').casefold())})),
        'Confianza_Fisica': 'BAJA', 'Confianza_Pertenencia_Lazo': 'BAJA',
        'Confianza_Funcion_ISA': 'BAJA', 'Confianza_Final': 'BAJA',
        'Accion': accion, 'Motivo': motivo,
    }


def _filas_descubiertas(topologias, asociaciones) -> list[dict]:
    filas, vistos = [], set()
    for asociacion in asociaciones:
        problemas = asociacion.problems
        for rol, elementos in (('ENTRADA', asociacion.inputs), ('SALIDA', asociacion.outputs)):
            for identidad in elementos:
                clave = (asociacion.plc, identidad.key)
                if clave in vistos:
                    continue
                vistos.add(clave)
                if rol == 'SALIDA':
                    tipo, funcion = classify_output(identidad.base)
                    motivo = f'Elemento final tipo {tipo}'
                else:
                    variable, funcion = classify_input(identidad.base)
                    motivo = 'Entrada física demostrada por dirección de módulo'
                filas.append({
                    'PLC_Origen': asociacion.plc,
                    'Tag_Anterior': '', 'Tag_Original_PLC': identidad.qualified,
                    'Encontrado_L5X': 'SI', 'Alcance': identidad.scope,
                    'Rol_Propuesto': rol,
                    'Area': '', 'Variable': '', 'Funcion': funcion,
                    'Loop_ID': asociacion.loop_id,
                    'Confianza_Fisica': 'ALTA',
                    'Confianza_Pertenencia_Lazo': asociacion.confianza_pertenencia,
                    'Confianza_Funcion_ISA': 'ALTA' if funcion else 'BAJA',
                    'Confianza_Final': asociacion.confianza_final,
                    'Accion': action_for(rol, problemas), 'Motivo': motivo,
                })
        if asociacion.controller:
            clave = (asociacion.plc, asociacion.controller.key)
            if clave not in vistos:
                vistos.add(clave)
                filas.append({
                    'PLC_Origen': asociacion.plc,
                    'Tag_Anterior': '', 'Tag_Original_PLC': asociacion.controller.qualified,
                    'Encontrado_L5X': 'SI', 'Alcance': asociacion.controller.scope,
                    'Rol_Propuesto': 'PID', 'Area': '', 'Variable': '', 'Funcion': 'C',
                    'Loop_ID': asociacion.loop_id,
                    'Confianza_Fisica': asociacion.confianza_fisica,
                    'Confianza_Pertenencia_Lazo': asociacion.confianza_pertenencia,
                    'Confianza_Funcion_ISA': asociacion.confianza_funcion,
                    'Confianza_Final': asociacion.confianza_final,
                    'Accion': action_for('PID', problemas),
                    'Motivo': 'Instancia de control ejecutada demostrada por definición/pines',
                })
    return filas


def _metricas(filas, asociaciones, historicos, actuales) -> dict:
    completos = [a for a in asociaciones if a.inputs and a.controller and a.outputs]
    entrada_pid = [a for a in asociaciones if a.inputs and a.controller and not a.outputs]
    pid_salida = [a for a in asociaciones if not a.inputs and a.controller and a.outputs]
    sin_lazo = [f for f in filas if f['Rol_Propuesto'] == 'SIN_LAZO']
    motivos = Counter(m for a in asociaciones for m in a.problems)
    return {
        'filas_csv': len(filas),
        'registros_historicos': len(historicos),
        'registros_protegidos_actuales': len(actuales),
        'entradas_unicas': len({(f['PLC_Origen'], f['Tag_Original_PLC']) for f in filas if f['Rol_Propuesto'] == 'ENTRADA'}),
        'salidas_unicas': len({(f['PLC_Origen'], f['Tag_Original_PLC']) for f in filas if f['Rol_Propuesto'] == 'SALIDA'}),
        'pid_unicos': len({(f['PLC_Origen'], f['Tag_Original_PLC']) for f in filas if f['Rol_Propuesto'] == 'PID'}),
        'grupos_completos': len(completos),
        'grupos_entrada_pid': len(entrada_pid),
        'grupos_pid_salida': len(pid_salida),
        'senales_fisicas_sin_lazo': len({(f['PLC_Origen'], f['Tag_Original_PLC']) for f in sin_lazo}),
        'ambiguedades_por_motivo': dict(sorted(motivos.items())),
        'lazos_candidatos': len(asociaciones),
    }


def comparar_con_v2(path_v2, path_v3) -> dict:
    """Diferencias cuantitativas respecto del CSV anterior."""
    def contar(path):
        with Path(path).open(encoding='utf-8-sig', newline='') as origen:
            filas = list(csv.DictReader(origen, delimiter=';'))
        return filas
    previas, nuevas = contar(path_v2), contar(path_v3)
    acciones_previas = Counter(f.get('Accion', '') for f in previas)
    acciones_nuevas = Counter(f.get('Accion', '') for f in nuevas)
    encontrados_previos = sum(f.get('Encontrado_L5X') == 'SI' for f in previas)
    encontrados_nuevos = sum(f.get('Encontrado_L5X') == 'SI' for f in nuevas)
    return {
        'filas_v2': len(previas), 'filas_v3': len(nuevas),
        'encontrado_l5x_v2': encontrados_previos, 'encontrado_l5x_v3': encontrados_nuevos,
        'delta_encontrado_l5x': encontrados_nuevos - encontrados_previos,
        'acciones_eliminadas': sorted(
            {'AGREGAR_CON_LAZO', 'RENUMERAR_CON_LAZO'} & set(acciones_previas)),
        'acciones_nuevas': {k: v for k, v in sorted(acciones_nuevas.items())
                            if k not in acciones_previas},
    }


import argparse  # noqa: E402  (import tardío: solo lo usa la CLI)
import json  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Reconciliador topológico v3 (solo lectura)')
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--db-actual', required=True, type=Path)
    parser.add_argument('--l5x-dir', default=Path('L5X_Produccion'), type=Path)
    parser.add_argument('--salida', required=True, type=Path)
    parser.add_argument('--comparar-con', type=Path)
    args = parser.parse_args(argv)
    metricas = reconstruir_v3(args.backup, args.db_actual, args.l5x_dir, args.salida)
    if args.comparar_con:
        metricas['diferencias_v2'] = comparar_con_v2(args.comparar_con, args.salida)
    print(json.dumps(metricas, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
