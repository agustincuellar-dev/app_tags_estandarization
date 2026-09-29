"""Trazador profundo de lazos sobre L5X (Fase 1/2/4 del sprint de numeracion masiva).

PROBLEMA QUE RESUELVE
---------------------
`exports/frontera_210_controladores.csv` declara 40 controladores de prioridad 1 y 2 que tienen
el PID y un extremo demostrados pero les falta el otro. La causa dominante (31 de 40) es
`ALIAS_NO_RESUELTO`: el pin PV del PID se cablea a un IRef con forma de referencia cruzada
(`\\FAB_ESCALADOS.CCV_PT_10_5BAR`) o a un tag interno REAL cuyo escritor nunca se trazo.

Este modulo cierra esa brecha:
  1. Carga el L5X completo: tags (con AliasFor), programas, rutinas y hojas FBD con nodos y wires.
  2. Traza el extremo faltante DESDE el pin del controlador, siguiendo wires y escritores.
  3. Acepta como terminal VALIDO solo una direccion fisica (tag Alias con AliasFor).
  4. Clasifica cada lazo y deja la evidencia del camino.

REGLAS DE HONESTIDAD (no negociables en este proyecto)
------------------------------------------------------
- Terminal valido = tag `TagType="Alias"` con `AliasFor` no vacio. Un tag Base REAL NO es un
  instrumento: hay que seguir su escritor. Si no se encuentra escritor, el lazo NO es cerrable.
- Si el trazado alcanza MAS DE UNA direccion fisica distinta para el mismo extremo, el lazo queda
  BLOQUEADO_EXTREMO_COMPARTIDO (no se elige una "ganadora").
- Si el trazado se corta en una construccion no soportada (escalera, bloque sin wires), queda
  BLOQUEADO_ANALIZADOR. Si se corta sin evidencia XML, BLOQUEADO_DOCUMENTAL.
- Nada de esto prueba ejecucion runtime: es evidencia XML, igual que el resto del proyecto.

Uso:
    python src/trazador_lazos_profundo.py                    # analiza los 40 de prioridad 1 y 2
    python src/trazador_lazos_profundo.py --plc FABRICA      # solo un PLC
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import OrderedDict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DIR_L5X = RAIZ / "L5X_Produccion"
FRONTERA = RAIZ / "exports" / "frontera_210_controladores.csv"
SALIDA = RAIZ / "exports" / "analisis_40_lazos.csv"

# Modulo hermano (envoltorios AOI). Se importa con la ruta del propio script para que funcione
# tanto ejecutandolo directo (`python src/trazador_lazos_profundo.py`) como desde los tests.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from envoltorios_l5x import (RE_CDATA, DefinicionesAOI, FlujoInterno,  # noqa: E402
                             destino_y_origenes, es_operando, instrucciones)

RE_NODO = re.compile(r"<(IRef|ORef|Block|AddOnInstruction)\b([^>]*)>")
RE_ATRIB = re.compile(r'(\w+)="([^"]*)"')
RE_WIRE = re.compile(r'<Wire\s+FromID="(\d+)"(?:\s+FromParam="([^"]+)")?\s+ToID="(\d+)"(?:\s+ToParam="([^"]+)")?\s*/>')
RE_TAG = re.compile(r'<Tag\s+Name="([^"]+)"([^>]*?)(/?)>')
RE_MODULO = re.compile(r'<Module\s+Name="([^"]+)"([^>]*?)>')
RE_RUNG = re.compile(r'<Rung\s+Number="(\d+)"[^>]*>(.*?)</Rung>', re.S)
RE_RUTINA_TEXTO = re.compile(r'<Routine\s+Name="([^"]+)"\s+Type="(RLL|ST)"(.*?)</Routine>', re.S)
RE_PROGRAMA = re.compile(r'<Program Name="([^"]+)"(.*?)(?=<Program Name="|\Z)', re.S)

PIN_SALIDA_PREFIJO = "MV"      # MV, MV_VALV_NC, MV_VALV_NA ...
PROFUNDIDAD_MAXIMA = 8

# Envoltorios de gobernanza (sprint v4, FASE 1): bloques AOI que envuelven al control real y que
# hay que atravesar cuando el camino interno es unico.
ENVOLTORIOS = ("PROPORCION_AM", "ALIMENTADOR_BAGAZO", "LIMITADOR", "LIMITADOR_2", "Limitador_Txt",
               "SEL", "B_SELECTORA", "RELACAO", "RELACION_4_PUNTOS", "Relacao")
# Pines de salida de bloques nativos (no AOI): no hay definicion que consultar.
PINES_SALIDA_NATIVOS = ("Out", "Dest", "")


def resultado(clasificacion: str, nota: str, **extra) -> dict:
    """Resultado con TODAS las claves siempre presentes: las salidas tempranas tambien tienen
    que traer la forma completa, no solo las que llegan al final del trazado."""
    base = {"clasificacion": clasificacion, "nota": nota, "entrada_operando": "",
            "entrada_fisica": "", "entrada_camino": "", "salida_fisica": "", "salida_camino": "",
            "pin_salida": "", "camino": ""}
    base.update(extra)
    return base


class Hoja:
    __slots__ = ("programa", "rutina", "numero", "nodos", "wires")

    def __init__(self, programa, rutina, numero):
        self.programa, self.rutina, self.numero = programa, rutina, numero
        self.nodos: "OrderedDict[str, dict]" = OrderedDict()
        self.wires: list[tuple] = []

    def entradas_de(self, nodo_id):
        """(from_id, from_param, to_param) de las conexiones que ENTRAN al nodo."""
        return [(w[0], w[1], w[3]) for w in self.wires if w[2] == nodo_id]

    def salidas_de(self, nodo_id, prefijo_param=None):
        """(to_id, from_param, to_param) de las conexiones que SALEN del nodo."""
        filas = [(w[2], w[1], w[3]) for w in self.wires if w[0] == nodo_id]
        if prefijo_param:
            filas = [f for f in filas if (f[1] or "").startswith(prefijo_param)]
        return filas


class L5X:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self.texto = self.ruta.read_text(encoding="utf-8", errors="replace")
        self.tags: "OrderedDict[str, dict]" = OrderedDict()
        self.hojas: list[Hoja] = []
        self.modulos: "OrderedDict[str, dict]" = OrderedDict()
        self._parsear_tags()
        self._parsear_modulos()
        self._parsear_hojas()
        self.lecturas: dict[str, list[tuple]] = {}
        self.escrituras: dict[str, list[tuple]] = {}
        self.escrituras_ladder: dict[str, list[tuple]] = {}
        self.flujos_ladder: dict[tuple, object] = {}
        self._indexar_operandos()
        self._indexar_ladder_y_st()
        self.aois = DefinicionesAOI(self.texto)

    # ---------- parseo ----------
    def _parsear_modulos(self):
        """Modulos declarados (drives, adaptadores): un tag suyo es un dispositivo fisico.

        Sin esto, `Cal_8_Dosificador_1:O.FreqCommand` (PowerFlex 525 en el anillo) no resolvia a
        ningun destino fisico y la salida del lazo quedaba sin terminal.
        """
        for m in RE_MODULO.finditer(self.texto):
            a = dict(RE_ATRIB.findall(m.group(2)))
            self.modulos[m.group(1)] = {
                "CatalogNumber": a.get("CatalogNumber", ""), "ParentModule": a.get("ParentModule", ""),
                "Vendor": a.get("Vendor", ""), "ProductType": a.get("ProductType", ""),
            }

    def _parsear_tags(self):
        for m in RE_TAG.finditer(self.texto):
            nombre, attrs, cierre = m.group(1), m.group(2), m.group(3)
            a = dict(RE_ATRIB.findall(attrs))
            self.tags[nombre] = {
                "TagType": a.get("TagType", ""),
                "DataType": a.get("DataType", ""),
                "AliasFor": (a.get("AliasFor") or "").strip(),
                "Radix": a.get("Radix", ""),
            }

    def _parsear_hojas(self):
        programa = rutina = None
        for m in re.finditer(r'<Program Name="([^"]+)"|<Routine Name="([^"]+)"|<Sheet Number="(\d+)">(.*?)</Sheet>',
                             self.texto, re.S):
            if m.group(1):
                programa, rutina = m.group(1), None
            elif m.group(2):
                rutina = m.group(2)
            else:
                hoja = Hoja(programa, rutina, m.group(3))
                cuerpo = m.group(4)
                for n in RE_NODO.finditer(cuerpo):
                    a = dict(RE_ATRIB.findall(n.group(2)))
                    if "ID" not in a:
                        continue
                    hoja.nodos[a["ID"]] = {
                        "kind": n.group(1), "operand": a.get("Operand", ""),
                        "type": a.get("Type", ""), "name": a.get("Name", ""),
                        "pins": a.get("VisiblePins", ""),
                    }
                hoja.wires = RE_WIRE.findall(cuerpo)
                self.hojas.append(hoja)

    def _indexar_operandos(self):
        for i, hoja in enumerate(self.hojas):
            for nodo_id, nodo in hoja.nodos.items():
                base = self.nombre_tag(nodo["operand"])
                if not base:
                    continue
                if nodo["kind"] == "IRef":
                    self.lecturas.setdefault(base, []).append((i, nodo_id))
                elif nodo["kind"] == "ORef":
                    # Solo los ORef ESCRIBEN un tag. El Operand de un Block/AOI es el nombre de la
                    # instancia, no un tag escrito: indexarlo como escritor era ruido.
                    self.escrituras.setdefault(base, []).append((i, nodo_id))

    def _indexar_ladder_y_st(self):
        """Indexa quien escribe en ESCALERA y en ST (FASE 2 del sprint v4).

        El indice de ORef solo ve hojas FBD. La mayoria de las rutinas de estos PLC son RLL
        (Calderas 29, DIBACCO 33, FABRICA 33), asi que un tag escalado en escalera quedaba
        'sin escritor en el XML' aunque el escritor estuviera a la vista.
        """
        for pm in RE_PROGRAMA.finditer(self.texto):
            programa, cuerpo = pm.group(1), pm.group(2)
            for rm in RE_RUTINA_TEXTO.finditer(cuerpo):
                rutina, tipo, contenido = rm.group(1), rm.group(2), rm.group(3)
                flujo = FlujoInterno()
                clave = (programa, rutina)
                for numero, bruto in RE_RUNG.findall(contenido):
                    texto = " ".join((" ".join(RE_CDATA.findall(bruto)) or bruto).split())
                    if not texto:
                        continue
                    for nombre, args in instrucciones(texto):
                        destino, origenes = destino_y_origenes(nombre, args)
                        if not destino or not es_operando(destino):
                            continue
                        flujo.agregar(destino, [o for o in origenes if es_operando(o)],
                                       tipo, "%s(%s) -> %s" % (nombre, ",".join(args)[:44], destino))
                        self.escrituras_ladder.setdefault(destino.split(".")[0], []).append(
                            (clave, numero, nombre, destino, [o for o in origenes if es_operando(o)]))
                if tipo == "ST":
                    for texto in RE_CDATA.findall(contenido):
                        for linea in re.split(r"[;\n]", texto):
                            m = re.match(r"\s*([A-Za-z_][\w.:\[\]]*)\s*:?=\s*(.+)$", linea.strip())
                            if not m:
                                continue
                            destino, expresion = m.group(1), m.group(2)
                            origenes = [t for t in re.findall(r"[A-Za-z_][\w.:\[\]]*", expresion)
                                        if es_operando(t)]
                            flujo.agregar(destino, origenes, "ST", "ST %s <- %s" % (destino, expresion[:40]))
                            self.escrituras_ladder.setdefault(destino.split(".")[0], []).append(
                                (clave, "", "ST", destino, origenes))
                if flujo.fuentes:
                    self.flujos_ladder[clave] = flujo

    # ---------- utilidades ----------
    RE_DIRECCION = re.compile(r"^[A-Za-z0-9_]+:\d+:[IO]\.")
    RE_CONSTANTE = re.compile(r"^-?\d+(\.\d+)?$")

    @classmethod
    def clasificar_operando(cls, operando: str) -> tuple:
        """Clasifica un operando tal como aparece en un IRef/ORef.

        Devuelve (tipo, valor, programa):
          ('DIRECCION', 'Desaireador:2:I.Ch[4].Data', '')   -> direccion fisica de modulo
          ('CRUZADO',   'CCV_PT_10_5BAR', 'FAB_ESCALADOS')   -> \\PROGRAMA.TAG
          ('TAG',       'FT_AGUA', '')                       -> tag (puede traer .Miembro)
          ('CONSTANTE', '100.0', '')                         -> literal
          ('VACIO',     '', '')
        """
        op = (operando or "").strip()
        if not op:
            return ("VACIO", "", "")
        if cls.RE_CONSTANTE.match(op):
            return ("CONSTANTE", op, "")
        if op.startswith("\\"):
            resto = op.lstrip("\\")
            partes = resto.split(".")
            if len(partes) >= 2:
                return ("CRUZADO", partes[1], partes[0])
            return ("TAG", resto, "")
        if cls.RE_DIRECCION.match(op):
            return ("DIRECCION", op, "")
        return ("TAG", op.split(".")[0], "")

    @classmethod
    def nombre_tag(cls, operando: str) -> str:
        """Nombre del tag si el operando referencia uno; '' para direcciones y constantes."""
        tipo, valor, _ = cls.clasificar_operando(operando)
        return valor if tipo in ("TAG", "CRUZADO") else ""

    def tag(self, nombre: str) -> dict:
        return self.tags.get(nombre, {})

    def es_alias_fisico(self, nombre: str) -> bool:
        t = self.tag(nombre)
        return t.get("TagType") == "Alias" and bool(t.get("AliasFor"))

    def modulo_de(self, operando: str) -> tuple:
        """(modulo, catalogo) si el operando es un miembro de un modulo declarado (`Drive:O.X`).

        Un PowerFlex 525 en el anillo es un dispositivo real: su comando de frecuencia ES una
        direccion fisica aunque el tag no sea un Alias. Se exige que el modulo exista en el L5X.
        """
        op = (operando or "").strip()
        if ":" not in op:
            return ("", "")
        nombre = op.split(":")[0].strip()
        if not nombre:
            return ("", "")
        info = self.modulos.get(nombre)
        if not info:
            return ("", "")
        return (nombre, info.get("CatalogNumber", ""))

    def es_terminal_fisico(self, operando: str) -> tuple | None:
        """(etiqueta, direccion, via) si el operando termina en un dispositivo real; si no, None.

        via: 'alias' | 'direccion' | 'modulo'. Los modulos se aceptan porque el sprint los
        necesita para clasificar bomba/motor como elemento final (regla R-A); la evidencia queda
        registrada con el catalogo del modulo.
        """
        tipo, valor, _ = self.clasificar_operando(operando)
        if tipo == "DIRECCION":
            return (valor, valor, "direccion")
        if tipo in ("TAG", "CRUZADO"):
            if self.es_alias_fisico(valor):
                return (valor, self.tag(valor)["AliasFor"], "alias")
            modulo, catalogo = self.modulo_de(operando)
            if modulo:
                m = re.match(r"^[A-Za-z0-9_]+:([IO])(?:\.|$)", (operando or "").strip(), re.I)
                direccion_io = (m.group(1).upper() if m else "O")
                return (operando, "%s:%s.%s" % (modulo, direccion_io, catalogo or "modulo"), "modulo")
        return None

    def es_pin_salida_de_bloque(self, tipo: str, pin: str) -> bool:
        """Pin de salida segun la DECLARACION del AOI; para bloques nativos, la convencion de casa.

        Antes solo se seguian los pines que empezaban con MV/Out, asi que `SALIDA_MV` (los
        envoltorios del sprint) y `VALOR_SALIDA` quedaban afuera y el trazado se cortaba.
        """
        declarado = self.aois.es_pin_salida(tipo, pin)
        if declarado is not None:
            return bool(declarado)
        p = pin or ""
        return p in PINES_SALIDA_NATIVOS or p.startswith(("MV", "Out"))

    def programa_de(self, operando: str) -> str:
        op = (operando or "").strip().lstrip("\\")
        if "." in op:
            return op.split(".")[0]
        return ""

    def pin_salida_de(self, hoja: Hoja, nodo_id: str):
        cands = hoja.salidas_de(nodo_id, PIN_SALIDA_PREFIJO)
        exacto = [c for c in cands if (c[1] or "") == "MV"]
        return (exacto or cands), cands

    # ---------- trazado ----------
    def _trazar_origen(self, idx, nodo_id, visitados, profundidad, camino, vistos_nodos=None):
        """Terminales fisicos alcanzados desde un NODO (IRef / ORef / Block).

        CLAVE: si el nodo es un bloque (SCL, MOV, ...), hay que seguir SUS entradas cableadas. Su
        `Operand` es el nombre de la instancia (SCL_45), no un tag: tratarlo como tag cortaba el
        trazado justo en el escalado, que es donde vive la direccion fisica.
        """
        vistos_nodos = vistos_nodos or set()
        hoja = self.hojas[idx]
        nodo = hoja.nodos.get(nodo_id)
        if not nodo or (idx, nodo_id) in vistos_nodos or profundidad > PROFUNDIDAD_MAXIMA:
            return []
        vistos_nodos = vistos_nodos | {(idx, nodo_id)}

        if nodo["kind"] in ("Block", "AddOnInstruction"):
            etiqueta = nodo.get("type") or nodo.get("name") or nodo["kind"]
            fisicos = []
            for (fid, fparam, tparam) in hoja.entradas_de(nodo_id):
                camino.append("bloque %s (pin %s) en %s/%s" % (etiqueta, tparam or "in", hoja.programa, hoja.rutina))
                fisicos += self._trazar_origen(idx, fid, visitados, profundidad + 1, camino, vistos_nodos)
            return fisicos
        r = self.resolver_terminal(nodo.get("operand") or nodo.get("name"), visitados, profundidad + 1)
        camino += r["camino"]
        return r["fisicos"]

    def _trazar_escritores_escalera(self, nombre, visitados, profundidad, camino, etiqueta):
        """Origen fisico de un tag escrito en ESCALERA o ST (FASE 2). None si no hay escritor.

        Recorre el flujo de la rutina donde vive el tag: si la instruccion que lo escribe toma su
        valor de otro tag escrito en la misma rutina, sigue la cadena; si toma un tag de campo o
        una direccion, la resuelve con `resolver_terminal`.
        """
        hallados = []
        for clave, flujo in self.flujos_ladder.items():
            for destino, origenes in flujo.escritores_de(nombre):
                if destino.split(".")[0] != nombre.split(".")[0]:
                    continue
                pasos = [p for p in flujo.pasos if p.endswith("-> %s" % destino)]
                hallados.append((clave, destino, origenes, pasos[:1]))
        if not hallados:
            return None

        fisicos, notas = [], []
        for (programa, rutina), destino, origenes, pasos in hallados:
            notas.append("%s <- %s en %s/%s" % (etiqueta, (pasos or ["escalera"])[0], programa, rutina))
            for o in origenes:
                base = o.split(".")[0]
                if base in visitados:
                    continue
                flujo = self.flujos_ladder.get((programa, rutina))
                interno = flujo.escritores_de(base) if flujo else []
                if interno:
                    # El valor viene de otro calculo de la misma rutina: se resuelve esa rama.
                    sub = self._trazar_escritores_escalera(base, visitados | {nombre}, profundidad + 1,
                                                           camino, base)
                    if sub and sub["fisicos"]:
                        fisicos += sub["fisicos"]
                        continue
                r = self.resolver_terminal(o, visitados | {nombre}, profundidad + 1)
                camino += r["camino"]
                fisicos += r["fisicos"]
        unicos = []
        for f in fisicos:
            if f not in unicos:
                unicos.append(f)
        camino.extend(notas)
        return {"estado": "FISICO" if unicos else "SIN_DATOS", "fisicos": unicos, "camino": camino}

    def _trazar_salida(self, idx, nodo_id, profundidad=0, vistos_nodos=None, camino=None,
                       pin_entrada=None):
        """Terminales fisicos que reciben la salida, aguas abajo. Sigue bloques intermedios
        (cascadas, comparadores) ademas de los ORef directos.

        `pin_entrada` es el pin por el que el valor ENTRO al nodo actual: es lo que permite
        atravesar un envoltorio AOI verificando que el paso interno hacia su pin de salida sea
        unico (FASE 1 del sprint v4).
        """
        vistos_nodos = vistos_nodos or set()
        camino = camino if camino is not None else []
        hoja = self.hojas[idx]
        nodo = hoja.nodos.get(nodo_id)
        if not nodo or (idx, nodo_id) in vistos_nodos or profundidad > PROFUNDIDAD_MAXIMA:
            return []
        vistos_nodos = vistos_nodos | {(idx, nodo_id)}

        tipo, valor, _ = self.clasificar_operando(nodo.get("operand", ""))
        if nodo["kind"] == "ORef":
            terminal = self.es_terminal_fisico(nodo.get("operand", ""))
            if terminal:
                etiqueta, direccion, via = terminal
                if via == "modulo":
                    camino.append("ORef %s (modulo %s)" % (etiqueta, direccion))
                elif via == "alias":
                    camino.append("ORef %s (AliasFor %s)" % (etiqueta, direccion))
                else:
                    camino.append("ORef %s (direccion fisica)" % etiqueta)
                return [(etiqueta, direccion)]
            if tipo in ("TAG", "CRUZADO"):
                camino.append("ORef %s no es alias ni modulo fisico" % valor)
            return []
        if nodo["kind"] in ("Block", "AddOnInstruction"):
            etiqueta = nodo.get("type") or nodo.get("name")
            fisicos = []
            for (tid, fparam, tparam) in hoja.salidas_de(nodo_id):
                destino = hoja.nodos.get(tid)
                if not destino:
                    continue
                if not self.es_pin_salida_de_bloque(etiqueta, fparam):
                    continue
                # Envoltorio AOI: antes de seguir, el paso interno pin_entrada -> pin_salida tiene
                # que ser UNICO. Si es ambiguo, el lazo no se cierra por aca (no se elige ganador).
                if pin_entrada and self.aois.hay(etiqueta):
                    paso = self.aois.paso_interno(etiqueta, pin_entrada, fparam)
                    if paso is not None:
                        if not paso["unico"] and not paso["bloques_control"]:
                            camino.append("envoltorio %s: paso %s->%s no unico (%s)"
                                          % (etiqueta, pin_entrada, fparam, paso["motivo"][:60]))
                            continue
                        if paso["unico"]:
                            camino.append("envoltorio %s: %s" % (etiqueta, " <- ".join(paso["camino"])))
                        elif paso["bloques_control"]:
                            camino.append("envoltorio %s con control interno %s"
                                          % (etiqueta, ",".join(sorted(set(paso["bloques_control"]))[:2])))
                camino.append("bloque %s (pin %s -> %s)" % (etiqueta, fparam or "out", tparam or "in"))
                fisicos += self._trazar_salida(idx, tid, profundidad + 1, vistos_nodos, camino, tparam)
            return fisicos
        return []

    def resolver_terminal(self, operando: str, visitados=None, profundidad=0):
        """Devuelve {'estado', 'fisicos': [(etiqueta, direccion, via)], 'camino': [...]}.

        estado: FISICO (alcanzo direcciones fisicas) | SIN_ESCRITOR | SIN_DATOS | CONSTANTE | LIMITE
        """
        visitados = visitados or set()
        camino = []
        tipo, valor, programa = self.clasificar_operando(operando)

        if tipo == "VACIO":
            return {"estado": "SIN_DATOS", "fisicos": [], "camino": camino}
        if tipo == "CONSTANTE":
            camino.append("constante %s" % valor)
            return {"estado": "CONSTANTE", "fisicos": [], "camino": camino}
        if tipo == "DIRECCION":
            camino.append("%s (direccion fisica de modulo)" % valor)
            return {"estado": "FISICO", "fisicos": [(valor, valor, "direccion")], "camino": camino}
        terminal_modulo = self.es_terminal_fisico(operando)
        if terminal_modulo and terminal_modulo[2] == "modulo":
            camino.append("%s (referencia de I/O de modulo declarado; catalogo %s)"
                          % (operando, self.modulo_de(operando)[1] or "no declarado"))
            return {"estado": "FISICO", "fisicos": [terminal_modulo], "camino": camino}

        nombre = valor
        etiqueta = ("%s.%s" % (programa, nombre)) if tipo == "CRUZADO" else nombre
        if not nombre or nombre in visitados or profundidad > PROFUNDIDAD_MAXIMA:
            return {"estado": "LIMITE", "fisicos": [], "camino": camino}
        visitados = visitados | {nombre}

        t = self.tag(nombre)
        if t.get("TagType") == "Alias":
            if t.get("AliasFor"):
                camino.append("%s (AliasFor %s)" % (etiqueta, t["AliasFor"]))
                return {"estado": "FISICO", "fisicos": [(etiqueta, t["AliasFor"], "alias")], "camino": camino}
            camino.append("%s (Alias SIN AliasFor: no es direccion fisica)" % etiqueta)
            return {"estado": "SIN_DATOS", "fisicos": [], "camino": camino}
        if not t:
            camino.append("%s (tag no declarado en el L5X)" % etiqueta)
            return {"estado": "SIN_DATOS", "fisicos": [], "camino": camino}

        escritores = self.escrituras.get(nombre, [])
        if not escritores:
            por_escalera = self._trazar_escritores_escalera(nombre, visitados, profundidad, camino, etiqueta)
            if por_escalera is not None:
                return por_escalera
            camino.append("%s (REAL interno sin escritor trazable: ni ORef, ni escalera, ni ST)" % etiqueta)
            return {"estado": "SIN_ESCRITOR", "fisicos": [], "camino": camino}

        fisicos = []
        for (idx, nodo_id) in escritores:
            hoja = self.hojas[idx]
            entrantes = hoja.entradas_de(nodo_id)
            if not entrantes:
                camino.append("%s escrito por ORef sin wire entrante (hoja %s/%s)"
                              % (etiqueta, hoja.programa, hoja.rutina))
                continue
            for (fid, fparam, tparam) in entrantes:
                camino.append("%s <- nodo %s (pin %s) en %s/%s"
                              % (etiqueta, fid, tparam or "in", hoja.programa, hoja.rutina))
                fisicos += self._trazar_origen(idx, fid, visitados, profundidad + 1, camino)
        unicos = []
        for f in fisicos:
            if f not in unicos:
                unicos.append(f)
        return {"estado": "FISICO" if unicos else "SIN_DATOS", "fisicos": unicos, "camino": camino}

    def analizar(self, plc: str, programa: str, rutina: str, instancia: str) -> dict:
        """Traza entrada (pin PV) y salida (pin MV*) de la instancia AOI en la hoja de su rutina."""
        candidatas = [h for h in self.hojas
                      if h.programa == programa and h.rutina == rutina
                      and any(n.get("operand") == instancia for n in h.nodos.values())]
        if not candidatas:
            return resultado("BLOQUEADO_ANALIZADOR",
                             "no se encontro la instancia %s en %s/%s" % (instancia, programa, rutina))
        hoja = candidatas[0]
        bloque = next(nid for nid, n in hoja.nodos.items()
                      if n.get("operand") == instancia and n["kind"] == "AddOnInstruction")

        # --- ENTRADA: pin PV ---
        entradas_pv = [(w[0], w[3]) for w in hoja.wires if w[2] == bloque and (w[3] or "") == "PV"]
        if not entradas_pv:
            return resultado("BLOQUEADO_ANALIZADOR",
                             "el bloque %s no tiene wire al pin PV en la hoja %s/%s (bloque FBD sin mapeo direccional)"
                             % (instancia, hoja.programa, hoja.rutina))
        origen_ent = hoja.nodos.get(entradas_pv[0][0], {})
        operando_ent = origen_ent.get("operand") or origen_ent.get("name") or ""
        r_ent = self.resolver_terminal(operando_ent)

        # --- SALIDA: pines MV* (con trazado hacia adelante por bloques intermedios) ---
        wires_sal, todas_sal = self.pin_salida_de(hoja, bloque)
        idx_hoja = self.hojas.index(hoja)
        salidas_fisicas, notas_sal = [], []
        pin_usado = ""
        for (tid, fparam, tparam) in wires_sal:
            alcanzados = self._trazar_salida(idx_hoja, tid, 0, None, notas_sal, tparam)
            for (nom, dir_fis) in alcanzados:
                if (nom, dir_fis) not in salidas_fisicas:
                    salidas_fisicas.append((nom, dir_fis))
            if alcanzados:
                pin_usado = pin_usado or (fparam or "")
        if not salidas_fisicas and todas_sal:
            notas_sal.append("pines MV cableados: %s" % ",".join(sorted({c[1] or "" for c in todas_sal})))

        # --- CONTROL INTERNO (FASE 1): el controlador puede ser el mismo un AOI envoltorio ---
        tipo_aoi = hoja.nodos.get(bloque, {}).get("type") or instancia
        control_interno = ""
        if self.aois.hay(tipo_aoi):
            paso = self.aois.paso_interno(tipo_aoi, "PV", pin_usado or "MV")
            if paso and paso["bloques_control"]:
                control_interno = ",".join(sorted(set(paso["bloques_control"])))

        # --- clasificacion ---
        fisicos_ent = r_ent["fisicos"]
        if len(fisicos_ent) == 1 and len(salidas_fisicas) == 1:
            clase = "CERRABLE_HOY"
            nota = "entrada y salida con direccion fisica unica"
            if control_interno:
                nota += "; control interno %s" % control_interno
        elif len(fisicos_ent) > 1:
            clase = "BLOQUEADO_EXTREMO_COMPARTIDO"
            nota = "la entrada alcanza %d direcciones fisicas distintas: %s" % (
                len(fisicos_ent), "; ".join("%s=%s" % (a, b) for a, b, _ in fisicos_ent))
        elif len(salidas_fisicas) > 1:
            clase = "BLOQUEADO_EXTREMO_COMPARTIDO"
            nota = "la salida alcanza %d direcciones fisicas distintas" % len(salidas_fisicas)
        elif r_ent["estado"] == "SIN_ESCRITOR":
            clase = "BLOQUEADO_DOCUMENTAL"
            nota = "la entrada es un tag REAL interno sin escritor en el XML; " + "; ".join(notas_sal[:2])
        elif r_ent["estado"] == "LIMITE":
            clase = "BLOQUEADO_ANALIZADOR"
            nota = "trazado cortado por limite de profundidad o ciclo"
        elif fisicos_ent and not salidas_fisicas:
            # La entrada SI tiene direccion fisica: lo que no cierra es la salida. Decirlo asi.
            clase = "BLOQUEADO_ANALIZADOR"
            detalle = "; ".join(notas_sal[:2])
            nota = "salida sin direccion fisica resuelta" + ("; " + detalle if detalle else "")
        else:
            clase = "BLOQUEADO_ANALIZADOR"
            nota = ("entrada sin direccion fisica resuelta (%s); %s"
                    % (r_ent["estado"], "; ".join(notas_sal[:2]) or "sin nota de salida"))
        return {
            "clasificacion": clase, "nota": nota,
            "entrada_operando": operando_ent,
            "entrada_fisica": " | ".join("%s (%s)" % (a, b) for a, b, _ in fisicos_ent),
            "entrada_camino": " <- ".join(r_ent["camino"][:6]),
            "salida_fisica": " | ".join("%s (%s)" % (a, b) for a, b in salidas_fisicas),
            "salida_camino": " ; ".join(notas_sal),
            "pin_salida": pin_usado,
            "camino": "%s -> %s" % (self.ruta.name, operando_ent),
        }


def l5x_de(plc: str, cache: dict) -> L5X:
    if plc not in cache:
        ruta = DIR_L5X / ("%s.L5X" % plc)
        if not ruta.exists():
            raise FileNotFoundError("Falta el L5X del PLC %s" % plc)
        cache[plc] = L5X(ruta)
    return cache[plc]


def leer_frontera(prioridades=("1", "2"), ruta=FRONTERA) -> list[dict]:
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    return [x for x in filas if x["Prioridad"] in prioridades]


def analizar_filas(filas, solo_plc=None) -> list[dict]:
    cache, salida = {}, []
    vistos = set()
    for fila in filas:
        if solo_plc and fila["PLC"] != solo_plc:
            continue
        clave = (fila["PLC"], fila["Program"], fila["Routine"], fila["Instancia"])
        if clave in vistos:
            continue
        vistos.add(clave)
        try:
            lx = l5x_de(fila["PLC"], cache)
            r = lx.analizar(fila["PLC"], fila["Program"], fila["Routine"], fila["Instancia"])
        except Exception as error:
            r = {"clasificacion": "BLOQUEADO_ANALIZADOR", "nota": "error: %s" % error,
                 "entrada_operando": "", "entrada_fisica": "", "entrada_camino": "",
                 "salida_fisica": "", "salida_camino": "", "pin_salida": "", "camino": ""}
        salida.append({
            "PLC": fila["PLC"], "Program": fila["Program"], "Routine": fila["Routine"],
            "Instancia": fila["Instancia"], "Prioridad": fila["Prioridad"],
            "Tipo_AOI": fila["Tipo"], "Submotivo_Frontera": fila["Submotivo_Bloqueo"],
            "Clasificacion": r["clasificacion"], "Nota": r["nota"],
            "Entrada_Operando": r.get("entrada_operando", ""),
            "Entrada_Fisica": r.get("entrada_fisica", ""),
            "Entrada_Camino": r.get("entrada_camino", ""),
            "Salida_Fisica": r.get("salida_fisica", ""),
            "Salida_Camino": r.get("salida_camino", ""),
            "Pin_Salida": r.get("pin_salida", ""),
        })
    return salida


def escribir(analisis, destino: Path = SALIDA) -> Path:
    columnas = ["PLC", "Program", "Routine", "Instancia", "Prioridad", "Tipo_AOI", "Submotivo_Frontera",
                "Clasificacion", "Nota", "Entrada_Operando", "Entrada_Fisica", "Entrada_Camino",
                "Salida_Fisica", "Salida_Camino", "Pin_Salida"]
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, delimiter=";", lineterminator="\n")
        w.writeheader()
        for fila in analisis:
            w.writerow({c: fila.get(c, "") for c in columnas})
    return destino


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Trazador profundo de lazos (solo lectura de L5X y CSV).")
    p.add_argument("--plc")
    p.add_argument("--salida", default=str(SALIDA))
    p.add_argument("--todas", action="store_true",
                   help="Analiza las 210 filas de la frontera, no solo las de prioridad 1 y 2.")
    args = p.parse_args(argv)

    filas = leer_frontera(prioridades=("1", "2", "3", "4") if args.todas else ("1", "2"))
    analisis = analizar_filas(filas, args.plc)
    destino = escribir(analisis, Path(args.salida))

    from collections import Counter
    conteo = Counter(a["Clasificacion"] for a in analisis)
    print("Analizados: %d lazos (prioridad 1 y 2)" % len(analisis))
    for clase, n in sorted(conteo.items()):
        print("  %-34s %d" % (clase, n))
    print()
    for a in analisis:
        if a["Clasificacion"] == "CERRABLE_HOY":
            print("  CERRABLE %-14s %-14s %-24s" % (a["PLC"], a["Program"], a["Instancia"]))
            print("     entrada: %s" % a["Entrada_Fisica"][:120])
            print("     salida : %s (pin %s)" % (a["Salida_Fisica"][:110], a["Pin_Salida"]))
    print()
    print("[OK] %s" % destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
