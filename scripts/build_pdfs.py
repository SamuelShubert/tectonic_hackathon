"""Render every document in data/documents to a professional-looking PDF in data/pdf.

Run after changing a document:  python scripts/build_pdfs.py

The PDFs are build artifacts: the app only serves these files, by source ID,
and never builds a path from a request. reportlab is a dev dependency only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.config import load_rules  # noqa: E402
from engine.loader import _split_front_matter, load_knowledge_base  # noqa: E402
from engine.models import SourceType  # noqa: E402

OUT_DIR = ROOT / "data" / "pdf"

NAVY = colors.HexColor("#1F3A5F")
INK = colors.HexColor("#1C1B19")
MUTED = colors.HexColor("#6B6A64")
LINE = colors.HexColor("#D9DCE1")
TINT = colors.HexColor("#F3F5F8")
STATUS_COLORS = {
    "current": colors.HexColor("#2E7D4F"),
    "draft": colors.HexColor("#A86A0C"),
    "unknown": colors.HexColor("#B42318"),
}
TYPE_LABEL = {
    SourceType.POLICY: "Policy",
    SourceType.PROCEDURE: "Procedure",
    SourceType.CLIENT_NOTE: "Client file",
    SourceType.UNKNOWN: "Document",
}
COUNTRY_NAME = {"BE": "Belgium", "NL": "Netherlands", "DE": "Germany", "ALL": "All countries"}
NOTICE = "SYNTHETIC DEMO DATA. Fictional content for a hackathon demo. Not legal or payroll advice."

styles = {
    "kicker": ParagraphStyle("kicker", fontName="Helvetica-Bold", fontSize=8.5, leading=11,
                             textColor=NAVY, spaceAfter=4),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=21, leading=25,
                            textColor=INK, spaceAfter=4),
    "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10, leading=14,
                               textColor=MUTED, spaceAfter=14),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, leading=16,
                         textColor=NAVY, spaceBefore=12, spaceAfter=5),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=15,
                           textColor=INK, alignment=TA_LEFT, spaceAfter=6),
    "meta_key": ParagraphStyle("meta_key", fontName="Helvetica", fontSize=8, leading=10, textColor=MUTED),
    "meta_val": ParagraphStyle("meta_val", fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=INK),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=MUTED),
}


def inline(text: str) -> str:
    """Escape text for reportlab, then turn **bold** into <b>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(text))


def body_flowables(markdown: str, title: str) -> list:
    """A small Markdown subset: #, ##, paragraphs, - bullets, 1. numbered lists, > notice."""
    flow: list = []
    bullets: list[str] = []
    numbered: list[str] = []

    def flush() -> None:
        nonlocal bullets, numbered
        for items, kind in ((bullets, "bullet"), (numbered, "1")):
            if items:
                flow.append(ListFlowable(
                    [ListItem(Paragraph(inline(i), styles["body"]), leftIndent=14) for i in items],
                    bulletType=kind, start="•" if kind == "bullet" else 1,
                    bulletFontSize=9, bulletColor=NAVY, leftIndent=14, spaceAfter=6))
        bullets, numbered = [], []

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith(">"):
            continue  # the synthetic-data notice is printed in the footer of every page
        if line.startswith("## "):
            flush()
            flow.append(Paragraph(inline(line[3:]), styles["h2"]))
        elif line.startswith("# "):
            flush()
            heading = line[2:].strip()
            if heading.lower() != title.lower():
                flow.append(Paragraph(inline(heading), styles["h2"]))
        elif line.startswith("- "):
            bullets.append(line[2:])
        elif re.match(r"^\d+\.\s", line):
            numbered.append(re.sub(r"^\d+\.\s", "", line))
        else:
            flush()
            flow.append(Paragraph(inline(line), styles["body"]))
    flush()
    return flow


def meta_table(rows: list[tuple[str, str, colors.Color | None]]) -> Table:
    cells, style_cmds = [], []
    pairs = [rows[i:i + 2] for i in range(0, len(rows), 2)]
    for r, pair in enumerate(pairs):
        row = []
        for c, (key, value, color) in enumerate(pair):
            val_style = styles["meta_val"]
            if color is not None:
                val_style = ParagraphStyle(f"v{r}{c}", parent=val_style, textColor=color)
            row.append([Paragraph(escape(key), styles["meta_key"]), Paragraph(escape(value), val_style)])
        if len(row) == 1:
            row.append("")
        cells.append(row)
    table = Table(cells, colWidths=[85 * mm, 85 * mm])
    style_cmds += [
        ("BACKGROUND", (0, 0), (-1, -1), TINT),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    table.setStyle(TableStyle(style_cmds))
    return table


def control_block(approved: bool, owner_name: str, updated: str) -> Table:
    text = (f"Approved for use by <b>{escape(owner_name)}</b> on {escape(updated)}."
            if approved else "<b>Not approved.</b> This document has no approved status and must be "
                             "verified before it is used for payroll decisions.")
    table = Table([[Paragraph("Document control", styles["meta_key"])],
                   [Paragraph(text, styles["small"])]], colWidths=[170 * mm])
    table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


class NumberedCanvas(rl_canvas.Canvas):
    """Two-pass canvas so every page can print 'Page x of y'."""

    def __init__(self, *args, footer_left: str = "", watermark: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages: list[dict] = []
        self._footer_left = footer_left
        self._watermark = watermark

    def showPage(self):  # noqa: N802 - reportlab API
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total: int) -> None:
        width, height = A4
        # Header band
        self.setFillColor(NAVY)
        self.rect(0, height - 14 * mm, width, 14 * mm, stroke=0, fill=1)
        self.setFillColor(colors.white)
        self.setFont("Helvetica-Bold", 9)
        self.drawString(20 * mm, height - 8.8 * mm, "PAYROLL SERVICES  |  KNOWLEDGE BASE")
        self.setFont("Helvetica", 8)
        self.drawRightString(width - 20 * mm, height - 8.8 * mm, "Internal use  ·  Synthetic demo")
        # Watermark
        if self._watermark:
            self.saveState()
            self.setFillColor(colors.HexColor("#B42318"), alpha=0.07)
            self.setFont("Helvetica-Bold", 72)
            self.translate(width / 2, height / 2)
            self.rotate(35)
            self.drawCentredString(0, -20, self._watermark)
            self.restoreState()
        # Footer
        self.setStrokeColor(LINE)
        self.setLineWidth(0.6)
        self.line(20 * mm, 16 * mm, width - 20 * mm, 16 * mm)
        self.setFillColor(MUTED)
        self.setFont("Helvetica", 7.5)
        self.drawString(20 * mm, 11 * mm, NOTICE)
        self.drawRightString(width - 20 * mm, 11 * mm,
                             f"{self._footer_left}  ·  Page {self._pageNumber} of {total}")


def build(source, meta: dict, kb) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{source.id}.pdf"

    status = source.status.value
    owner = kb.experts.get(source.owner or "")
    owner_name = owner.name if owner else (source.owner or "No owner")
    company = kb.companies.get(source.company) if source.company else None
    version = str(meta.get("version") or "").strip() or "not versioned"
    updated = source.last_updated.strftime("%d %B %Y").lstrip("0")

    watermark = None
    if source.superseded_by:
        watermark = "SUPERSEDED"
    elif status == "draft":
        watermark = "DRAFT"
    elif status == "unknown" or not source.owner:
        watermark = "UNCONTROLLED COPY"

    kind = TYPE_LABEL.get(source.source_type, "Document")
    kicker = f"{kind.upper()}  ·  {COUNTRY_NAME.get(source.country, source.country).upper()}"
    if company:
        kicker = f"CLIENT FILE  ·  {company.name.upper()}"
    subtitle = (f"{company.sector}, {company.city}  ·  {company.joint_committee}  ·  about {company.employees} employees"
                if company else f"{meta.get('domain', '').replace('_', ' ').capitalize()} · {kind}")

    rows = [
        ("Document ID", source.id, None),
        ("Version", version, None),
        ("Status", status.capitalize() if status != "unknown" else "Unknown (not set)", STATUS_COLORS.get(status)),
        ("Owner", owner_name, None if source.owner else STATUS_COLORS["unknown"]),
        ("Last updated", updated, None),
        ("Applies to", company.name if company else COUNTRY_NAME.get(source.country, source.country), None),
        ("Location", str(meta.get("source") or "Unknown"), None),
    ]
    if source.supersedes:
        rows.append(("Replaces", source.supersedes, None))
    if source.superseded_by:
        rows.append(("Replaced by", f"{source.superseded_by} (do not use this version)", STATUS_COLORS["unknown"]))

    story = [
        Paragraph(escape(kicker), styles["kicker"]),
        Paragraph(escape(source.title), styles["title"]),
        Paragraph(escape(subtitle), styles["subtitle"]),
        meta_table(rows),
        Spacer(1, 8 * mm),
        *body_flowables(source.content, source.title),
        Spacer(1, 8 * mm),
        KeepTogether([control_block(status == "current" and bool(owner) and not source.superseded_by,
                                    owner_name, updated)]),
    ]

    doc = SimpleDocTemplate(
        str(out), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=26 * mm, bottomMargin=24 * mm,
        title=f"{source.id} {source.title}", author=owner_name, subject="Synthetic demo document",
        creator="TrustLens build_pdfs.py",
    )
    footer = f"{source.id}  ·  v{version}" if meta.get("version") else source.id
    doc.build(story, canvasmaker=lambda *a, **k: NumberedCanvas(
        *a, footer_left=footer, watermark=watermark, **{**k, "invariant": 1}))  # invariant: reproducible bytes
    return out


def main() -> None:
    kb = load_knowledge_base(ROOT / "data", load_rules(ROOT / "config" / "rules.yaml"))
    count = 0
    for path in sorted((ROOT / "data" / "documents").glob("*.md")):
        meta, _ = _split_front_matter(path.read_text(encoding="utf-8"))
        source = kb.sources.get(str(meta.get("id", "")).strip())
        if source is None:
            continue
        print("built", build(source, meta, kb).relative_to(ROOT))
        count += 1
    print(f"{count} PDFs in {OUT_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
