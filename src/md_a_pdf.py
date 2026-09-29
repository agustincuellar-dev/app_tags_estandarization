"""
md_a_pdf.py
=============
Conversor Markdown -> PDF para los informes del proyecto (los Resumenes
Ejecutivos de docs/). Usa solo reportlab, que ya esta disponible en el
entorno -- sin pandoc, wkhtmltopdf ni weasyprint, que no estan instalados
y requeririan permisos de administrador en la PC del Ingenio.

Soporta el subconjunto de Markdown que usan los informes:
  # / ## / ### encabezados, parrafos, **negrita**, `codigo inline`,
  tablas GFM (| a | b |), bloques ``` , <pre>, listas - y 1., y ---.

Uso:
    python md_a_pdf.py docs/Resumen_Ejecutivo_Avance_270826.md
    python md_a_pdf.py entrada.md salida.pdf
"""

import os
import re
import sys
import html

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (HRFlowable, KeepTogether, ListFlowable,
                                ListItem, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

AZUL = colors.HexColor("#1F4E79")
GRIS = colors.HexColor("#F2F2F2")
GRIS_BORDE = colors.HexColor("#BFBFBF")


def _estilos():
    ss = getSampleStyleSheet()
    e = {
        "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontSize=17, leading=21,
                              textColor=AZUL, spaceBefore=6, spaceAfter=8, keepWithNext=1),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13.5, leading=17,
                              textColor=AZUL, spaceBefore=14, spaceAfter=6, keepWithNext=1),
        "h3": ParagraphStyle("h3", parent=ss["Heading3"], fontSize=11.5, leading=14,
                              textColor=colors.HexColor("#2E5F8A"), spaceBefore=10, spaceAfter=4,
                              keepWithNext=1),
        "p": ParagraphStyle("p", parent=ss["BodyText"], fontSize=9.5, leading=13.5,
                             alignment=TA_LEFT, spaceAfter=6),
        "p_kw": ParagraphStyle("p_kw", parent=ss["BodyText"], fontSize=9.5, leading=13.5,
                               alignment=TA_LEFT, spaceAfter=6, keepWithNext=1),
        "celda": ParagraphStyle("celda", parent=ss["BodyText"], fontSize=8, leading=10.5),
        "celda_h": ParagraphStyle("celda_h", parent=ss["BodyText"], fontSize=8, leading=10.5,
                                   textColor=colors.white, fontName="Helvetica-Bold"),
        "code": ParagraphStyle("code", parent=ss["Code"], fontSize=7.6, leading=9.8,
                                textColor=colors.HexColor("#222222")),
    }
    return e


def _inline(texto):
    """Markdown inline -> markup de reportlab. Escapa XML primero para que
    un '<' o '&' del texto no rompa el Paragraph."""
    t = html.escape(texto, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`(.+?)`", r'<font face="Courier" size="8.5">\1</font>', t)
    # Links [texto](url) -> solo el texto (el PDF es para imprimir/leer)
    t = re.sub(r"\[(.+?)\]\([^)]*\)", r"\1", t)
    return t


def _fila_tabla(linea):
    """'| a | b |' -> ['a', 'b']"""
    return [c.strip() for c in linea.strip().strip("|").split("|")]


def _es_separador(linea):
    """'|---|:---:|' -> True"""
    return bool(re.match(r"^\|[\s:\-|]+\|$", linea.strip()))


def convertir(path_md, path_pdf=None):
    if path_pdf is None:
        path_pdf = os.path.splitext(path_md)[0] + ".pdf"

    with open(path_md, encoding="utf-8") as fh:
        lineas = fh.read().split("\n")

    e = _estilos()
    story = []
    i = 0
    n = len(lineas)

    while i < n:
        ln = lineas[i]
        s = ln.strip()

        # --- bloque de codigo ``` o <pre> ---
        if s.startswith("```") or s.startswith("<pre"):
            cierre = "```" if s.startswith("```") else "</pre>"
            buf = []
            i += 1
            while i < n and cierre not in lineas[i]:
                buf.append(lineas[i])
                i += 1
            i += 1
            texto = html.escape("\n".join(buf), quote=False)
            texto = texto.replace(" ", "&nbsp;").replace("\n", "<br/>")
            tabla = Table([[Paragraph(texto, e["code"])]], colWidths=[16.6 * cm])
            tabla.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), GRIS),
                ("BOX", (0, 0), (-1, -1), 0.5, GRIS_BORDE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(tabla)
            story.append(Spacer(1, 7))
            continue

        # --- tabla GFM ---
        if s.startswith("|") and i + 1 < n and _es_separador(lineas[i + 1]):
            encabezado = _fila_tabla(s)
            i += 2
            cuerpo = []
            while i < n and lineas[i].strip().startswith("|"):
                cuerpo.append(_fila_tabla(lineas[i]))
                i += 1
            ncols = len(encabezado)
            datos = [[Paragraph(_inline(c), e["celda_h"]) for c in encabezado]]
            for fila in cuerpo:
                fila = (fila + [""] * ncols)[:ncols]
                datos.append([Paragraph(_inline(c), e["celda"]) for c in fila])
            ancho_total = 16.6 * cm
            tabla = Table(datos, colWidths=[ancho_total / ncols] * ncols, repeatRows=1)
            tabla.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), AZUL),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS]),
                ("GRID", (0, 0), (-1, -1), 0.4, GRIS_BORDE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(tabla)
            story.append(Spacer(1, 9))
            continue

        # --- encabezados ---
        m = re.match(r"^(#{1,3})\s+(.*)$", s)
        if m:
            nivel = len(m.group(1))
            story.append(Paragraph(_inline(m.group(2)), e[f"h{nivel}"]))
            i += 1
            continue

        # --- regla horizontal ---
        if s in ("---", "***", "___"):
            story.append(Spacer(1, 3))
            story.append(HRFlowable(width="100%", thickness=0.6, color=GRIS_BORDE))
            story.append(Spacer(1, 7))
            i += 1
            continue

        # --- listas ---
        if re.match(r"^([-*]|\d+\.)\s+", s):
            items = []
            while i < n and re.match(r"^([-*]|\d+\.)\s+", lineas[i].strip()):
                txt = re.sub(r"^([-*]|\d+\.)\s+", "", lineas[i].strip())
                items.append(ListItem(Paragraph(_inline(txt), e["p"]), leftIndent=12))
                i += 1
            ordenada = bool(re.match(r"^\d+\.", s))
            inicio = re.match(r"^(\d+)\.", s).group(1) if ordenada else None
            story.append(ListFlowable(items, bulletType="1" if ordenada else "bullet",
                                       start=inicio, leftIndent=14))
            story.append(Spacer(1, 5))
            continue

        # --- cita > ---
        if s.startswith(">"):
            buf = []
            while i < n and lineas[i].strip().startswith(">"):
                buf.append(lineas[i].strip().lstrip(">").strip())
                i += 1
            p = Paragraph(_inline(" ".join(buf)),
                          ParagraphStyle("cita", parent=e["p"], leftIndent=14,
                                          textColor=colors.HexColor("#444444")))
            story.append(p)
            story.append(Spacer(1, 5))
            continue

        # --- linea en blanco ---
        if not s:
            i += 1
            continue

        # --- parrafo (junta lineas consecutivas; respeta el salto duro de 2 espacios) ---
        buf = []
        while i < n and lineas[i].strip() and not re.match(
                r"^(#{1,3}\s|\||```|<pre|>|[-*]\s|\d+\.\s|---$|\*\*\*$|___$)", lineas[i].strip()):
            buf.append(lineas[i].rstrip("\n"))
            i += 1
        if buf:
            piezas = []
            for j, cruda in enumerate(buf):
                piezas.append(_inline(cruda.strip()))
                if j < len(buf) - 1:
                    piezas.append("<br/>" if cruda.endswith("  ") else " ")
            texto_plano = " ".join(t.strip() for t in buf)
            # Un parrafo que termina en ':' introduce el bloque siguiente (tabla, lista, codigo):
            # si queda solo al pie de pagina se lo empuja junto con lo que anuncia.
            estilo = e["p_kw"] if texto_plano.rstrip().endswith(":") else e["p"]
            story.append(Paragraph("".join(piezas), estilo))
        else:
            i += 1

    # keepWithNext de reportlab no siempre alcanza (falla con ListFlowable y con titulo->titulo):
    # se pega explicitamente cada flowable que pide keepWithNext con el bloque siguiente. El
    # recorrido va de atras hacia adelante, asi las cadenas titulo->titulo->bloque quedan cubiertas
    # por pares encadenados y no queda ningun titulo solo al pie de pagina.
    for indice in range(len(story) - 2, -1, -1):
        actual, siguiente = story[indice], story[indice + 1]
        estilo = getattr(actual, "style", None)
        if estilo is None or not getattr(estilo, "keepWithNext", 0):
            continue
        if isinstance(siguiente, (Spacer, HRFlowable, PageBreak)):
            continue
        story[indice:indice + 2] = [KeepTogether([actual, siguiente])]

    doc = SimpleDocTemplate(
        path_pdf, pagesize=A4,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title=os.path.basename(path_md), author="Ingenio La Florida",
    )

    def _pie(canvas, documento):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(2.2 * cm, 1.1 * cm, "Ingenio La Florida - Estandarizacion ISA-5.1")
        canvas.drawRightString(A4[0] - 2.2 * cm, 1.1 * cm, f"Pag. {documento.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_pie, onLaterPages=_pie)
    return path_pdf


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    entrada = sys.argv[1]
    salida = sys.argv[2] if len(sys.argv) > 2 else None
    ruta = convertir(entrada, salida)
    print(f"PDF generado: {ruta}")
