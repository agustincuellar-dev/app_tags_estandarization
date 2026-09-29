"""Atravesado de bloques envoltorio AOI en L5X (Sprint de frontera v4, FASE 1).

PROBLEMA QUE RESUELVE
---------------------
`src/trazador_lazos_profundo.py` sigue la salida de un controlador aguas abajo, pero al llegar a
un bloque AOI envoltorio (`ALIMENTADOR_BAGAZO`, `PROPORCION_AM`, `LIMITADOR`, `SEL`, `Relacao`)
solo mira los pines cuyo nombre empieza con MV/Out: `SALIDA_MV` y `VALOR_SALIDA` quedan afuera y
el trazado se corta sin evidencia. El lazo terminaba BLOQUEADO_ANALIZADOR aunque el camino
PV -> control -> MV fuera unico y con direccion fisica en ambos extremos.

QUE HACE ESTE MODULO
--------------------
1. Parsea cada `<AddOnInstructionDefinition>`: parametros (con `Usage`), hojas FBD, rungs de
   escalera (el texto vive en el CDATA de `<Text>`) y lineas ST.
2. Construye el flujo de datos INTERNO del AOI: cada instruccion aporta el par
   (destino <- origenes).
3. Responde la pregunta del sprint: entre dos pines del envoltorio, el camino interno es UNICO?
   Y ese camino atraviesa un bloque de control real (PIDE/PID/PID_*)? Devuelve la evidencia.

REGLAS DE HONESTIDAD
--------------------
- Los pines de salida se toman de la DECLARACION del AOI (`Usage="Output"|"InputOutput"`), nunca
  de una heuristica de nombre: un nombre lindo no es evidencia.
- Si el camino interno tiene mas de un origen posible, se declara AMBIGUO y no se atraviesa.
- Sin definicion del AOI en el L5X no se inventa el paso: se devuelve None y el llamador bloquea.

Uso:
    from envoltorios_l5x import DefinicionesAOI
    d = DefinicionesAOI(texto_l5x)
    d.pines("PROPORCION_AM")            # {'in': [...], 'out': [...]}
    d.paso_interno("PROPORCION_AM", "ENTRADA_MV", "SALIDA_MV")
"""

from __future__ import annotations

import re
from collections import OrderedDict, deque

RE_AOI = re.compile(r"<AddOnInstructionDefinition\s+Name=\"([^\"]+)\"(.*?)(?=<AddOnInstructionDefinition\s|\Z)", re.S)
RE_PARAM = re.compile(r"<Parameter\s+([^>]*?)/?>", re.S)
RE_RUTINA = re.compile(r"<Routine\s+Name=\"([^\"]+)\"\s+Type=\"(\w+)\"(.*?)</Routine>", re.S)
RE_RUNG = re.compile(r"<Rung\s+Number=\"(\d+)\"[^>]*>(.*?)</Rung>", re.S)
RE_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)
RE_ATRIB = re.compile(r'(\w+)="([^"]*)"')
RE_LLAMADA = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")
RE_NODO = re.compile(r"<(IRef|ORef|Block|AddOnInstruction)\b([^>]*)>")
RE_WIRE = re.compile(r'<Wire\s+FromID="(\d+)"(?:\s+FromParam="([^"]+)")?\s+ToID="(\d+)"(?:\s+ToParam="([^"]+)")?\s*/>')

# Instrucciones que NO escriben su ultimo argumento (comparaciones y lecturas).
NO_ESCRIBEN = {
    "XIC", "XIO", "XICN", "OTL", "OTU", "EQU", "NEQ", "LES", "LEQ", "GRT", "GEQ", "LIM", "MEQ",
    "CMP", "JSR", "RET", "JMP", "LBL", "NOP", "AFI", "EOT", "TND", "UID", "UIE", "UIO", "JXR",
    "MSG", "GSV", "SSV", "EVENT", "PATT", "DTR", "SIZE", "CID", "CLL", "ATOH", "ATOI", "AEX",
    "DTOS", "RTOS", "STOD", "TOD", "FRD", "TODT", "TONR", "CPS", "COP2",
}
# Instrucciones de temporizador/contador: escriben su primer argumento, no tienen fuente de proceso.
ESCRIBE_PRIMERO = {"TON", "TOF", "RTO", "CTU", "CTD", "RES", "OTE", "OTU", "OTL", "TONR"}


def instrucciones(texto: str) -> list[tuple[str, list[str]]]:
    """Todas las llamadas `NOMBRE(a, b, ...)` del texto, respetando parentesis anidados.

    En escalera el CDATA trae la logica como texto plano (`MOV(ENTRADA_MV,SALIDA_MV)`), asi que
    el parseo tiene que aguantar comas y parentesis dentro de un argumento (`SCL(A,B/2,C,Dest)`).
    """
    salida, i = [], 0
    while True:
        m = RE_LLAMADA.search(texto, i)
        if not m:
            return salida
        nombre = m.group(1).upper()
        j, nivel, args, actual = m.end(), 1, [], []
        while j < len(texto) and nivel:
            c = texto[j]
            if c == "(":
                nivel += 1
                actual.append(c) if nivel > 1 else None
            elif c == ")":
                nivel -= 1
                if nivel:
                    actual.append(c)
            elif c == "," and nivel == 1:
                args.append("".join(actual).strip())
                actual = []
            else:
                actual.append(c)
            j += 1
        if actual or args:
            args.append("".join(actual).strip())
        salida.append((nombre, [a for a in args]))
        i = j


def destino_y_origenes(nombre: str, args: list[str]) -> tuple[str, list[str]]:
    """(destino, origenes) de una instruccion, segun la convencion de Studio 5000.

    `MOV(src,Dest)`, `MUL(a,b,Dest)`, `DIV(a,b,Dest)`, `SCL(src,rate,offset,Dest)` y similares
    escriben el ULTIMO argumento. Las comparaciones no escriben nada. Los temporizadores
    escriben el primero (estructura propia, sin fuente de proceso).
    """
    limpios = [a for a in args if a]
    if not limpios:
        return "", []
    if nombre in NO_ESCRIBEN:
        return "", []
    if nombre in ESCRIBE_PRIMERO:
        return limpios[0], []
    if nombre == "CPT" and len(limpios) >= 2:
        return limpios[0], limpios[1:]
    return limpios[-1], limpios[:-1]


def es_operando(txt: str) -> bool:
    """True si el argumento referencia un tag/miembro y no es una constante numerica."""
    t = (txt or "").strip()
    if not t or re.match(r"^-?\d+(\.\d+)?$", t):
        return False
    if t.startswith(("'", '"')):
        return False
    if t[0].isdigit():
        return False
    return bool(re.match(r"^[A-Za-z_\\][\w:.\[\]\\/]*$", t))


class FlujoInterno:
    """Flujo de datos interno de una definicion AOI: destino <- origenes."""

    __slots__ = ("fuentes", "pasos", "bloques_control", "lenguajes")

    def __init__(self):
        self.fuentes: dict[str, list[str]] = OrderedDict()   # destino -> [origenes]
        self.pasos: list[str] = []
        self.bloques_control: list[str] = []
        self.lenguajes: list[str] = []

    def agregar(self, destino, origenes, lenguaje, detalle):
        if not destino:
            return
        lista = self.fuentes.setdefault(destino, [])
        for o in origenes:
            if o not in lista:
                lista.append(o)
        self.pasos.append(detalle)
        if lenguaje not in self.lenguajes:
            self.lenguajes.append(lenguaje)

    def escritores_de(self, nodo: str) -> list[tuple]:
        """Todas las instrucciones que escriben `nodo` (o un miembro suyo)."""
        base = (nodo or "").split(".")[0]
        salida = []
        for destino, origenes in self.fuentes.items():
            if destino == nodo or destino.split(".")[0] == base:
                salida.append((destino, origenes))
        return salida

    def trazar_atras(self, entrada: str, salida: str, limite: int = 10) -> dict:
        """Camino interno UNICO de `entrada` a `salida` recorriendo el flujo hacia atras.

        Devuelve {'unico', 'motivo', 'camino': [...], 'ambiguedad': [...]}. Unico solo si cada
        nodo del camino tiene UN escritor y las cadenas confluyen en el pin de entrada: es la
        condicion que pide el sprint para atravesar el envoltorio.
        """
        camino, ambiguedad = [], []

        def recorrer(nodo: str, pasos: list[str], profundidad: int):
            if profundidad > limite:
                return {"unico": False, "motivo": "profundidad %d en %s" % (limite, nodo)}
            escritores = self.escritores_de(nodo)
            if len(escritores) > 1:
                ambiguedad.append("%s tiene %d escritores" % (nodo, len(escritores)))
                return {"unico": False, "motivo": "varios escritores de %s" % nodo}
            if not escritores:
                # Terminal: el nodo no se escribe adentro. Es un pin de entrada del AOI.
                if nodo.split(".")[0] == (entrada or "").split(".")[0]:
                    return {"unico": True, "motivo": "llega a %s" % nodo}
                return {"unico": False, "motivo": "%s no se escribe y no es el pin de entrada" % nodo}
            destino, origenes = escritores[0]
            oper = [o for o in origenes if es_operando(o)]
            paso = next((p for p in self.pasos if p.endswith("-> %s" % destino)), "%s <- %s" % (destino, origenes))
            for o in oper:
                base = o.split(".")[0]
                if base == (entrada or "").split(".")[0]:
                    return {"unico": True, "motivo": "paso %s toma %s" % (destino, o), "cierres": pasos + [paso, "%s = pin de entrada" % o]}
                if self.escritores_de(base):
                    return recorrer(base, pasos + [paso], profundidad + 1)
            # Ningun operando cierra contra la entrada ni tiene escritor interno.
            return {"unico": False,
                    "motivo": "%s se escribe desde %s, que no cierra contra %s" % (destino, oper or origenes, entrada)}

        resultado = recorrer(salida, [], 0)
        return {
            "unico": bool(resultado.get("unico")),
            "motivo": resultado.get("motivo", ""),
            "camino": resultado.get("cierres") or camino,
            "ambiguedad": ambiguedad,
        }


class DefinicionAOI:
    __slots__ = ("nombre", "params", "flujo", "rungs", "rutinas")

    def __init__(self, nombre):
        self.nombre = nombre
        self.params: "OrderedDict[str, dict]" = OrderedDict()
        self.flujo = FlujoInterno()
        self.rungs: list[str] = []
        self.rutinas: list[tuple] = []

    @property
    def pines_entrada(self) -> list[str]:
        """Pines de entrada declarados. Manda `Usage`: `Visible` solo controla el dialogo del
        bloque en Studio 5000, no la semantica del pin (B_SELECTORA los declara con Visible=false
        y aun asi son sus pines)."""
        return [n for n, p in self.params.items() if p["usage"] in ("Input", "InputOutput")]

    @property
    def pines_salida(self) -> list[str]:
        return [n for n, p in self.params.items() if p["usage"] in ("Output", "InputOutput")]


class DefinicionesAOI:
    """Todas las definiciones AOI de un L5X, con su flujo interno listo para consultar."""

    def __init__(self, texto: str):
        self.definiciones: "OrderedDict[str, DefinicionAOI]" = OrderedDict()
        self._parsear(texto)

    # ---------- parseo ----------
    def _parsear(self, texto: str):
        for m in RE_AOI.finditer(texto):
            d = DefinicionAOI(m.group(1))
            cuerpo = m.group(2)
            for pm in RE_PARAM.finditer(cuerpo):
                a = dict(RE_ATRIB.findall(pm.group(1)))
                if not a.get("Name"):
                    continue
                d.params[a["Name"]] = {
                    "usage": a.get("Usage", ""), "datatype": a.get("DataType", ""),
                    "visible": (a.get("Visible", "true") == "true"),
                }
            for rm in RE_RUTINA.finditer(cuerpo):
                nombre, tipo, cuerpo_rutina = rm.group(1), rm.group(2), rm.group(3)
                d.rutinas.append((nombre, tipo))
                if tipo == "RLL":
                    self._flujo_ladder(d, cuerpo_rutina, nombre)
                elif tipo == "FBD":
                    self._flujo_fbd(d, cuerpo_rutina, nombre)
                elif tipo == "ST":
                    self._flujo_st(d, cuerpo_rutina, nombre)
            self.definiciones[d.nombre] = d

    def _flujo_ladder(self, d: DefinicionAOI, cuerpo: str, rutina: str):
        for numero, bruto in RE_RUNG.findall(cuerpo):
            contenido = " ".join(RE_CDATA.findall(bruto)) or bruto
            texto = " ".join(contenido.split())
            if not texto:
                continue
            d.rungs.append("[%s.%s#%s] %s" % (d.nombre, rutina, numero, texto))
            for nombre, args in instrucciones(texto):
                destino, origenes = destino_y_origenes(nombre, args)
                if not destino or not es_operando(destino):
                    continue
                d.flujo.agregar(destino, [o for o in origenes if es_operando(o)] or origenes,
                                "RLL", "%s -> %s" % (nombre, destino))
                if nombre in ("PIDE", "PID", "PID_", "PIDC", "PIDE_") or nombre.startswith("PID"):
                    d.flujo.bloques_control.append("RLL %s" % nombre)

    def _flujo_fbd(self, d: DefinicionAOI, cuerpo: str, rutina: str):
        """En FBD el flujo sale de los wires: nodo destino <- nodo origen (parametros del AOI)."""
        for sm in re.finditer(r'<Sheet Number="(\d+)">(.*?)</Sheet>', cuerpo, re.S):
            hoja = sm.group(2)
            nodos = {}
            for nm in RE_NODO.finditer(hoja):
                a = dict(RE_ATRIB.findall(nm.group(2)))
                if a.get("ID"):
                    nodos[a["ID"]] = {"kind": nm.group(1), "operand": a.get("Operand", ""),
                                      "type": a.get("Type", ""), "name": a.get("Name", "")}
            for w in RE_WIRE.findall(hoja):
                fid, fparam, tid, tparam = w
                origen, destino = nodos.get(fid), nodos.get(tid)
                if not origen or not destino:
                    continue
                op_o = fparam or origen.get("operand") or origen.get("type") or ""
                op_d = tparam or destino.get("operand") or ""
                if es_operando(op_o) and es_operando(op_d):
                    d.flujo.agregar(op_d, [op_o], "FBD",
                                    "FBD %s -> %s" % (op_o[:40], op_d[:40]))
                etiqueta = (destino.get("type") or destino.get("name") or "").upper()
                if "PID" in etiqueta:
                    d.flujo.bloques_control.append("FBD %s" % (destino.get("type") or destino.get("name")))

    def _flujo_st(self, d: DefinicionAOI, cuerpo: str, rutina: str):
        contenido = " ".join(RE_CDATA.findall(cuerpo))
        for linea in re.split(r"[;\n]", contenido):
            m = re.match(r"\s*([A-Za-z_][\w.:\[\]]*)\s*:?=\s*(.+)$", linea.strip())
            if not m:
                continue
            destino, expresion = m.group(1), m.group(2)
            origenes = [t for t in re.findall(r"[A-Za-z_][\w.:\[\]]*", expresion) if es_operando(t)]
            d.flujo.agregar(destino, origenes, "ST", "ST %s <- %s" % (destino, expresion[:40]))

    # ---------- consultas ----------
    def hay(self, tipo: str) -> bool:
        return tipo in self.definiciones

    def pines(self, tipo: str) -> dict:
        d = self.definiciones.get(tipo)
        if not d:
            return {"in": [], "out": []}
        return {"in": d.pines_entrada, "out": d.pines_salida}

    def es_pin_salida(self, tipo: str, pin: str) -> bool | None:
        """True/False si el AOI esta declarado; None si no hay definicion (el llamador decide)."""
        d = self.definiciones.get(tipo)
        if not d:
            return None
        return (pin or "") in set(d.pines_salida)

    def paso_interno(self, tipo: str, pin_entrada: str, pin_salida: str) -> dict | None:
        """Camino interno del envoltorio entre dos pines. None si no hay definicion.

        {'unico': bool, 'motivo': str, 'camino': [...], 'bloques_control': [...],
         'rutinas': [...], 'ambiguedad': [...]}
        """
        d = self.definiciones.get(tipo)
        if not d:
            return None
        r = d.flujo.trazar_atras(pin_entrada, pin_salida)
        return {
            "unico": r["unico"],
            "motivo": r["motivo"],
            "camino": r["camino"],
            "ambiguedad": r["ambiguedad"],
            "bloques_control": list(d.flujo.bloques_control),
            "rutinas": list(d.rutinas),
            "pines_entrada": d.pines_entrada,
            "pines_salida": d.pines_salida,
        }

    def tiene_control(self, tipo: str) -> bool:
        d = self.definiciones.get(tipo)
        return bool(d and d.flujo.bloques_control)
