"""Экспорт документа в PDF (reportlab, шрифты DejaVu с поддержкой кириллицы)."""
import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table as RLTable,
    TableStyle,
)

from . import resources
from .docwalk import iter_blocks, px_to_pt

_FONTS_READY = False
FONT_REG = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"
FONT_ITAL = "DejaVuSans-Oblique"
FONT_BI = "DejaVuSans-BoldOblique"

ALIGN_MAP = {
    "left": TA_LEFT,
    "center": TA_CENTER,
    "right": TA_RIGHT,
    "justify": TA_JUSTIFY,
}

STYLE_SIZES = {"h1": 18, "h2": 15, "h3": 13}
STYLE_COLORS = {"h1": "#2F5496", "h2": "#2F5496", "h3": "#1F4E79"}


def _register_fonts():
    global _FONTS_READY
    if _FONTS_READY:
        return
    fd = resources.fonts_dir()
    pdfmetrics.registerFont(TTFont(FONT_REG, os.path.join(fd, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(fd, "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_ITAL, os.path.join(fd, "DejaVuSans-Oblique.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BI, os.path.join(fd, "DejaVuSans-BoldOblique.ttf")))
    pdfmetrics.registerFontFamily(FONT_REG, normal=FONT_REG, bold=FONT_BOLD, italic=FONT_ITAL, boldItalic=FONT_BI)
    _FONTS_READY = True


def _fmt_to_markup(fmt, base_size):
    """Собрать XML-обёртку для run'а."""
    parts = []
    inner_open = ""
    inner_close = ""
    if fmt.get("bold"):
        inner_open += "<b>"
        inner_close = "</b>" + inner_close
    if fmt.get("italic"):
        inner_open += "<i>"
        inner_close = "</i>" + inner_close
    if fmt.get("underline"):
        inner_open += "<u>"
        inner_close = "</u>" + inner_close
    if fmt.get("strike"):
        inner_open += "<strike>"
        inner_close = "</strike>" + inner_close
    font_attrs = f' name="{FONT_REG}"'
    if fmt.get("color"):
        font_attrs += f' color="{fmt["color"]}"'
    size = fmt.get("size") or base_size
    font_attrs += f' size="{size}"'
    return f"<font{font_attrs}>{inner_open}", inner_close + "</font>"


def export_pdf(text, tables, images, path, title="Документ", margins_cm=None):
    _register_fonts()
    mt, mb, ml, mr = margins_cm or [2.0, 2.0, 2.0, 2.0]
    story = []
    page_w = A4[0] - (ml + mr) * cm
    number_counter = 0

    def base_style(pfmt):
        size = 11
        leading = 13.5
        st = {
            "fontName": FONT_REG,
            "fontSize": size,
            "leading": leading,
            "alignment": ALIGN_MAP.get(pfmt["align"], TA_LEFT),
            "spaceAfter": pfmt.get("space_after") or 0,
        }
        if pfmt["style"] in STYLE_SIZES:
            st["fontName"] = FONT_BOLD
            st["fontSize"] = STYLE_SIZES[pfmt["style"]]
            st["leading"] = STYLE_SIZES[pfmt["style"]] * 1.25
            st["textColor"] = colors.HexColor(STYLE_COLORS[pfmt["style"]])
            st["spaceBefore"] = 6
        if pfmt.get("line_spacing") and pfmt["style"] not in STYLE_SIZES:
            st["leading"] = size * pfmt["line_spacing"] * 1.2
        if pfmt.get("indent_left"):
            st["leftIndent"] = px_to_pt(pfmt["indent_left"])
        if pfmt.get("indent_first"):
            st["firstLineIndent"] = px_to_pt(pfmt["indent_first"])
        if pfmt["list"]:
            st["leftIndent"] = st.get("leftIndent", 0) + 18
        return ParagraphStyle("p", **st)

    for block in iter_blocks(text):
        if block["type"] == "table":
            tinfo = tables.get(block["table_id"])
            if not tinfo:
                continue
            rows, cols = tinfo["rows"], tinfo["cols"]
            data = []
            for i in range(rows):
                row = []
                for j in range(cols):
                    try:
                        cell_text = tinfo["cells"][i][j].get()
                    except Exception:
                        cell_text = ""
                    row.append(
                        Paragraph(
                            escape(cell_text).replace("\n", "<br/>"),
                            ParagraphStyle("c", fontName=FONT_REG, fontSize=10, leading=12),
                        )
                    )
                data.append(row)
            col_w = page_w / cols
            tbl = RLTable(data, colWidths=[col_w] * cols)
            tbl.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#808080")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(tbl)
            story.append(Spacer(1, 8))
            number_counter = 0
            continue

        pfmt = block["pfmt"]
        if pfmt.get("page_break"):
            story.append(PageBreak())
        if pfmt["list"] == "number":
            number_counter += 1
        else:
            number_counter = 0

        st = base_style(pfmt)
        xml_parts = []
        prefix = ""
        if pfmt["list"] == "bullet":
            prefix = "•  "
        elif pfmt["list"] == "number":
            prefix = f"{number_counter}.  "
        if prefix:
            xml_parts.append(escape(prefix))
        for item in block["flow"]:
            if item["kind"] == "text":
                txt = item["text"]
                if pfmt["list"] == "bullet" and xml_parts == [escape(prefix)]:
                    txt = txt.lstrip()
                    import re as _re

                    txt = _re.sub(r"^•\s*", "", txt)
                elif pfmt["list"] == "number" and xml_parts == [escape(prefix)]:
                    import re as _re

                    txt = _re.sub(r"^\d+[.)]\s*", "", txt)
                o, c = _fmt_to_markup(item["fmt"], st.fontSize)
                xml_parts.append(o + escape(txt) + c)
            elif item["kind"] == "image":
                info = images.get(item["name"])
                if not info or not os.path.exists(info["path"]):
                    continue
                try:
                    from PIL import Image as PILImage

                    with PILImage.open(info["path"]) as im:
                        w_px, h_px = im.size
                except Exception:
                    continue
                width_in = info.get("width_in") or 4.0
                max_w = page_w
                max_h = A4[1] - (mt + mb) * cm
                w_pt = width_in * 72.0
                h_pt = w_pt * h_px / max(w_px, 1)
                if w_pt > max_w:
                    h_pt = h_pt * max_w / w_pt
                    w_pt = max_w
                if h_pt > max_h:
                    w_pt = w_pt * max_h / h_pt
                    h_pt = max_h
                try:
                    story.append(RLImage(info["path"], width=w_pt, height=h_pt))
                except Exception as e:
                    print(f"[pdf] картинка не вставлена: {e}")
        para = Paragraph("".join(xml_parts), st)
        story.append(para)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT_REG, 9)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawCentredString(A4[0] / 2.0, 1.2 * cm, f"Стр. {doc.page}")
        canvas.drawString(2 * cm, 1.2 * cm, "WordFree")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        leftMargin=ml * cm,
        rightMargin=mr * cm,
        topMargin=mt * cm,
        bottomMargin=mb * cm,
        title=title,
        author="WordFree",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
