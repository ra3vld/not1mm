"""Render the Russian setup guide. Requires reportlab; uses system DejaVu fonts.

From the repository root:
    python3 tools/build_vladimir_guide_pdf.py
"""

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, KeepTogether, PageBreak, Paragraph, Preformatted,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/vladimir-test-setup-ru.md"
OUTPUT = ROOT / "output/pdf/not1mm-vladimir-test-ru.pdf"
FONTS = Path("/usr/share/fonts/truetype/dejavu")
for name, filename in [("Guide", "DejaVuSans.ttf"),
                       ("GuideBold", "DejaVuSans-Bold.ttf"),
                       ("GuideMono", "DejaVuSansMono.ttf")]:
    pdfmetrics.registerFont(TTFont(name, str(FONTS / filename)))
pdfmetrics.registerFontFamily("Guide", normal="Guide", bold="GuideBold", italic="Guide", boldItalic="GuideBold")
styles = getSampleStyleSheet()
styles.add(ParagraphStyle("Body", fontName="Guide", fontSize=9.4, leading=13.3, spaceAfter=7))
styles.add(ParagraphStyle("TitleRu", parent=styles["Body"], fontName="GuideBold", fontSize=19, leading=24, spaceAfter=12))
styles.add(ParagraphStyle("H2Ru", parent=styles["Body"], fontName="GuideBold", fontSize=14, leading=18, spaceBefore=5, spaceAfter=10, keepWithNext=True))
styles.add(ParagraphStyle("H3Ru", parent=styles["Body"], fontName="GuideBold", fontSize=10.5, leading=14, spaceBefore=7, keepWithNext=True))
styles.add(ParagraphStyle("CellRu", parent=styles["Body"], fontSize=8.5, leading=11.5, spaceAfter=0))
styles.add(ParagraphStyle("CaptionRu", parent=styles["Body"], fontSize=8, leading=10.5, textColor=colors.HexColor("#465368"), alignment=TA_CENTER))
styles.add(ParagraphStyle("CodeRu", fontName="GuideMono", fontSize=8, leading=11, backColor=colors.HexColor("#eef2f6"), borderPadding=6, spaceAfter=10))


def inline(text):
    """Escape prose and preserve the guide's basic inline Markdown."""
    text = html.escape(text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                  lambda m: f'<a href="{m[2]}" color="#24578c">{m[1]}</a>' if m[2].startswith(("https://", "http://")) else m[1], text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`([^`]+)`", r'<font name="GuideMono">\1</font>', text)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#ced5df"))
    canvas.line(42, 34, A4[0] - 42, 34)
    canvas.setFont("Guide", 7.5)
    canvas.setFillColor(colors.HexColor("#465368"))
    canvas.drawString(42, 22, "Not1MM • Владимирский тест • 04.10.2026")
    canvas.drawRightString(A4[0] - 42, 22, str(doc.page))
    canvas.restoreState()


def build():
    width = A4[0] - 84
    story = []
    lines = SOURCE.read_text().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line == "<!-- pagebreak -->":
            story.append(PageBreak())
            i += 1
        elif line.startswith("```"):
            code = []
            i += 1
            while not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            story.append(Preformatted("\n".join(code), styles["CodeRu"]))
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [s.strip() for s in lines[i].strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", c) for c in cells):
                    rows.append([Paragraph(inline(c), styles["CellRu"]) for c in cells])
                i += 1
            table = Table(rows, colWidths=[width * .31, width * .69], hAlign="LEFT", repeatRows=1)
            table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4ecf5")),
                ("LINEBELOW", (0, 0), (-1, 0), .5, colors.HexColor("#aab8c9")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.extend([table, Spacer(1, 10)])
        elif line.startswith("!["):
            match = re.fullmatch(r"!\[([^]]*)\]\(([^)]+)\)", line)
            picture = Image(str(SOURCE.parent / match[2]))
            max_height = 335 if match[2].endswith("03-contest.png") else 375
            scale = min(width / picture.imageWidth, max_height / picture.imageHeight)
            picture.drawWidth = picture.imageWidth * scale
            picture.drawHeight = picture.imageHeight * scale
            story.append(KeepTogether([picture, Spacer(1, 5), Paragraph(inline(match[1]), styles["CaptionRu"]), Spacer(1, 8)]))
            i += 1
        elif line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            style = {1: "TitleRu", 2: "H2Ru", 3: "H3Ru"}[level]
            story.append(Paragraph(inline(line.lstrip("# ")), styles[style]))
            i += 1
        else:
            parts = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||!\[|```|<!--|- |\d+\.)", lines[i]):
                parts.append(lines[i].strip())
                i += 1
            story.append(Paragraph(inline(" ".join(parts)), styles["Body"]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=42, rightMargin=42, topMargin=38, bottomMargin=46,
                            title="Not1MM: установка и настройка для Владимирского теста", author="Not1MM contributors")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUTPUT)


if __name__ == "__main__":
    build()
