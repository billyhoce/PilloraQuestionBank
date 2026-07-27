"""PDF layout engine — packs question (or answer) page-images onto A4 pages.

Each ``LayoutEngine`` lays out ONE PDF variant. Callers either invoke ``render``
twice — once with each question's ``question`` pages, once with its ``answer``
pages — to produce separate question and answer papers, or pass both plans to
``render_combined`` to get a single PDF with the answer paper appended after the
question paper. Both variants follow identical layout rules.

Layout rules:
  * Blocks (one per question) are laid out in the order given.
  * Consecutive blocks are packed onto the same page while they fit the page's
    vertical budget (``page_capacity_px``); a block that would overflow starts a
    new page. A block taller than a whole page starts fresh and its individual
    page-images flow across as many pages as needed.
  * Each block is numbered (``label`` = "1", "2", …) in the left margin. Stored
    images are content-only (see ``app/pdf/image_processing.py``); the margin is
    created here, and the number is drawn into it, just left of the content.
"""
import io
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import Image
from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from app.pdf.cover_body import to_paragraphs

# A4 @ 300 DPI. PAGE_W_PX matches the standardized image canvas width; PAGE_H_PX
# follows from the A4 aspect ratio so px map 1:1 onto the page after scaling.
PAGE_W_PX = 2480
PAGE_H_PX = 3508

# Page chrome (drawn on every page): purple rule lines near the top and bottom,
# the Pillora logo top-left, the admin-configured header right-aligned on the top
# rule (multi-line, last line on the rule), a footer label flush-left below the
# footer line, and a page number bottom-right. The content band sits between the
# two rule lines.
PURPLE = Color(119 / 255, 102 / 255, 135 / 255)
_MARGIN_X_PX = 213                     # horizontal inset of the header/footer rule lines
_HEADER_LINE_Y_PX = 250                # header rule, px from the top
_FOOTER_LINE_Y_PX = PAGE_H_PX - 250    # footer rule, px from the top
_CHROME_FONT = "Helvetica"
_CHROME_FONT_PX = 42                   # ~12pt at 300 DPI (header / footer / page number)
_CHROME_HEADER_LINE_PX = 52            # line advance for the multi-line page header
# Tokens in the page header that look like a web address are turned into
# clickable links (matches "https://…", "www.pillora.com.sg", "pillora.com.sg").
# A bare domain needs a 2+ letter TLD, so ordinary text like "e.g." is left alone.
_URL_TOKEN = re.compile(
    r"https?://\S+|www\.\S+|[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:/\S*)?",
    re.I,
)


def _link_target(token: str) -> str:
    """Normalize a matched header token to an absolute URL for ``linkURL``."""
    stripped = token.rstrip(".,;:!?)")
    if stripped.lower().startswith(("http://", "https://")):
        return stripped
    return "https://" + stripped
_CHROME_RULE_PX = 4                    # rule line thickness
_LOGO_W_PX = 250                       # header logo width (aspect preserved)
_LOGO_RULE_GAP_PX = 12                 # gap between the logo's visible bottom and the header rule
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
LOGO_PATH = os.path.join(_ASSETS_DIR, "pillora_logo.png")

# Content band: between the two rule lines, with a little breathing room.
_CONTENT_TOP_PX = _HEADER_LINE_Y_PX + 60
_CONTENT_BOTTOM_PX = _FOOTER_LINE_Y_PX - 60
_DEFAULT_CAPACITY_PX = _CONTENT_BOTTOM_PX - _CONTENT_TOP_PX

# Cover page.
_COVER_LOGO_W_PX = 525
_COVER_TITLE_FONT_PX = 70
_COVER_SUBTITLE_FONT_PX = 60
_COVER_BODY_FONT_PX = 45
_COVER_BODY_LINE_PX = 66        # line advance within the letter paragraph
_COVER_BODY_W_PX = 1500         # wrap width for the letter paragraph
_COVER_COPYRIGHT_FONT_PX = 40
_COVER_COPYRIGHT = "© Pillora Learning — All worksheets are strictly for personal use."
# Marks box (top-right of the cover content area).
_MARKS_BOX_W_PX = 460
_MARKS_BOX_H_PX = 150
_MARKS_BOX_FONT_PX = 52

# Page margins. Both variants leave a 360px gutter on the left where the question
# number sits. Question images are scaled to a fixed 1760px content width and sit
# centered on the page (1760 + 360 + 360 = 2480). Answer images keep their
# original size (≤ 1760px from ingestion), flush to the left margin, so they never
# extend past the right edge (360 + 1760 < 2480).
_TARGET_CONTENT_W_PX = 1760           # question-variant content width
_LEFT_MARGIN_PX = (PAGE_W_PX - _TARGET_CONTENT_W_PX) // 2  # 360
_ANSWER_GAP_PX = 100                   # vertical gap between consecutive answer blocks
_QUESTION_GAP_PX = 59                  # 0.5 cm at 300 DPI (0.5/2.54*300 ≈ 59): question-paper
                                       # padding between any two images stacked on the same page

_LABEL_GAP_PX = 70
_LABEL_FONT = "Helvetica-Bold"
_LABEL_FONT_PX = 46  # ~14pt at 300 DPI
_LABEL_TOP_PAD_PX = 34  # nudge the number slightly below the question's top edge

_HEADER_FONT = "Helvetica"
_HEADER_FONT_PX = 42  # ~12pt at 300 DPI
_HEADER_LINE_PX = 58
_HEADER_PAD_PX = 40

# Per-question provenance credit (question paper only). Drawn just above each
# question in small grey type; the whole band is reserved in the block height so
# packing and rendering agree.
_CREDIT_FONT = "Helvetica"
_CREDIT_FONT_PX = 40  # ~11.5pt at 300 DPI
_CREDIT_GAP_PX = 18   # gap between the credit line and the image below it
_CREDIT_BAND_PX = _CREDIT_FONT_PX + _CREDIT_GAP_PX  # vertical space one credit reserves
_CREDIT_GREY = 0.35


def _instructions_height_px(additional_instructions: str) -> int:
    """Vertical band reserved for the instructions on the first page (0 if none)."""
    if not additional_instructions:
        return 0
    lines = additional_instructions.splitlines() or [additional_instructions]
    return len(lines) * _HEADER_LINE_PX + _HEADER_PAD_PX


@dataclass
class Block:
    """One question's worth of pages for a single PDF variant."""

    label: str            # renumbered position: "1", "2", …
    source_label: str     # e.g. "Raffles Institution 2024 Sec 3 EOY Q5" (kept for future use)
    pages: list           # QuestionPage-like rows (image_key, width_px, height_px), in order
    page_index: int = 0   # first page this block appears on; set by compute_layout


@dataclass
class CoverSpec:
    """Editable cover-page content for one section (question or answer paper)."""

    title: str            # e.g. "Topical Worksheets"
    subtitle1: str        # topic/subject line; " – Questions/Answers" appended per variant
    subtitle2: str        # e.g. "2024 Prelim"
    body: str             # the letter: rich-text HTML (<p>/<b>/<i>/<u>/<a href>,
                          # sanitized by app/pdf/cover_body.py) or legacy plain text
    total_marks: int      # shown in the top-right marks box
    is_questions: bool    # True → "Questions", False → "Answers"


@dataclass
class LayoutPlan:
    page_count: int
    blocks: list[Block]
    # header_text: branding drawn right-aligned on the top rule of every page.
    # additional_instructions: exam instructions drawn below the top rule on page 1.
    header_text: str = ""
    additional_instructions: str = ""
    footer_label: str = ""   # flush-left under the footer rule on every page of this section
    cover: "CoverSpec | None" = None  # optional cover page rendered as the section's first page


@lru_cache(maxsize=2)
def _load_logo(target_w_px: int = _LOGO_W_PX):
    """Load the Pillora logo as ``(ImageReader, w_px, h_px, bottom_pad_px)``
    scaled to ``target_w_px`` (aspect preserved), or ``None`` if the asset is
    missing/unreadable — chrome then simply renders without a logo.

    ``bottom_pad_px`` is the transparent margin below the visible mark (scaled
    to ``target_w_px``); the asset is a square canvas with the wordmark inset,
    so callers use it to sit the *visible* logo — not its padded box — on the
    header rule. Cached, so adding or changing the logo file takes effect on
    process restart."""
    try:
        img = Image.open(LOGO_PATH)
        img.load()
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        s = target_w_px / img.width
        h_px = round(img.height * s)
        bbox = img.getbbox()  # bounds of the non-transparent content; None if blank
        bottom_pad_px = (img.height - bbox[3]) * s if bbox else 0
        return ImageReader(img), target_w_px, h_px, bottom_pad_px
    except Exception:
        return None


class LayoutEngine:
    def __init__(
        self,
        page_capacity_px: int = _DEFAULT_CAPACITY_PX,
        fit_width: bool = True,
        show_credit: bool = False,
    ):
        # fit_width=True  -> scale image to a fixed 1760px content width, centered
        #                    on the page (question paper).
        # fit_width=False -> keep the image at native size, flush to the left
        #                    margin, with a gap between blocks (answer paper).
        # show_credit     -> draw each block's source_label above it (question paper).
        self.page_capacity_px = page_capacity_px
        self.fit_width = fit_width
        self.show_credit = show_credit
        # block_gap_px separates one question from the next; intra_gap_px separates
        # stacked page-images within a single multi-page question. The question paper
        # pads both by 0.5 cm; the answer paper keeps a wider block gap and no
        # intra-block gap (its pages stack flush).
        if fit_width:
            self.block_gap_px = _QUESTION_GAP_PX
            self.intra_gap_px = _QUESTION_GAP_PX
        else:
            self.block_gap_px = _ANSWER_GAP_PX
            self.intra_gap_px = 0

    def _image_scale(self, pg) -> float:
        """Uniform scale factor applied to an image for the current variant."""
        if self.fit_width:
            return _TARGET_CONTENT_W_PX / pg.width_px
        return 1.0

    def compute_layout(self, blocks: list[Block], additional_instructions: str = "") -> LayoutPlan:
        """Assign each block the page it starts on, packing greedily by height.

        A block starts a new page only when its *first* page-image (plus the
        credit band) won't fit in the remaining space; a multi-page block then
        flows its later pages onto following pages, exactly as ``render_onto``
        renders it. This walk mirrors that flow, so ``page_count`` counts those
        overflow pages too.
        """
        header_px = _instructions_height_px(additional_instructions)
        page = 0
        cursor = header_px  # px used on the current page (instructions reserved on page 0)
        for block in blocks:
            gap = self.block_gap_px if cursor > 0 else 0
            if cursor > 0 and cursor + gap + self._first_unit_height_px(block) > self.page_capacity_px:
                page += 1
                cursor = 0.0
                gap = 0
            block.page_index = page
            cursor += gap
            if self._credit_for(block):
                cursor += _CREDIT_BAND_PX
            for i, pg in enumerate(block.pages):
                eff_h = self._page_height_px(pg)
                igap = self.intra_gap_px if (cursor > 0 and i > 0) else 0
                if cursor > 0 and cursor + igap + eff_h > self.page_capacity_px:
                    page += 1
                    cursor = 0.0
                    igap = 0
                cursor += igap + eff_h
        page_count = page + 1 if blocks else 1
        return LayoutPlan(
            page_count=page_count,
            blocks=blocks,
            additional_instructions=additional_instructions,
        )

    def render(self, plan: LayoutPlan, fetch_bytes) -> bytes:
        """Render the plan to PDF bytes. ``fetch_bytes(image_key) -> bytes``."""
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        self.render_onto(c, plan, fetch_bytes)
        c.save()
        return buf.getvalue()

    def render_onto(self, c, plan: LayoutPlan, fetch_bytes) -> None:
        """Draw the plan onto an existing canvas, ending on a fresh page.

        Finishes with ``showPage()`` so a subsequent section (see
        ``render_combined``) starts on its own page.
        """
        scale = A4[0] / PAGE_W_PX  # points per px

        def y_pt(dist_from_top_px: float) -> float:
            return (PAGE_H_PX - dist_from_top_px) * scale

        page_num = 1

        def new_page() -> None:
            """Close the current page and start a fresh one, re-drawing chrome."""
            nonlocal page_num
            c.showPage()
            page_num += 1
            self._draw_chrome(c, page_num, plan.header_text, plan.footer_label, scale, y_pt)

        # Optional cover as the section's first page; content then starts on the
        # next page (skipped when there is nothing to render, so a cover-only
        # section is a single page). Otherwise draw chrome for the first content
        # page directly.
        if plan.cover is not None:
            self._draw_cover(c, plan.cover, plan.header_text, plan.footer_label, page_num, scale, y_pt)
            if plan.blocks:
                new_page()
        else:
            self._draw_chrome(c, page_num, plan.header_text, plan.footer_label, scale, y_pt)

        used = 0.0  # px consumed in the content area of the current page

        instructions_px = _instructions_height_px(plan.additional_instructions)
        if instructions_px:
            self._draw_instructions(c, plan.additional_instructions, scale, y_pt)
            used = instructions_px

        for block in plan.blocks:
            # Start a new page only if the block's first page (plus its credit
            # band) won't fit here; a multi-page block then flows its remaining
            # pages onto following pages via the per-image loop below.
            gap = self.block_gap_px if used > 0 else 0
            if used > 0 and used + gap + self._first_unit_height_px(block) > self.page_capacity_px:
                new_page()
                used = 0.0
                gap = 0
            used += gap

            if self._credit_for(block):
                c.setFont(_CREDIT_FONT, _CREDIT_FONT_PX * scale)
                c.setFillGray(_CREDIT_GREY)
                c.drawString(
                    _LEFT_MARGIN_PX * scale,
                    y_pt(_CONTENT_TOP_PX + used + _CREDIT_FONT_PX),
                    block.source_label,
                )
                c.setFillGray(0)
                used += _CREDIT_BAND_PX

            first_page = True
            for pg in block.pages:
                s_img = self._image_scale(pg)
                eff_h = pg.height_px * s_img
                if eff_h > self.page_capacity_px:
                    # Image taller than a page: fit to page height (both variants).
                    s_img *= self.page_capacity_px / eff_h
                    eff_h = float(self.page_capacity_px)
                # Pad above every page after the block's first (the block gap
                # already separated the first); the pad is dropped when this page
                # starts a fresh physical page.
                igap = self.intra_gap_px if (used > 0 and not first_page) else 0
                if used > 0 and used + igap + eff_h > self.page_capacity_px:
                    new_page()
                    used = 0.0
                    igap = 0
                used += igap

                reader = self._image_reader(fetch_bytes(pg.image_key))
                top = _CONTENT_TOP_PX + used
                c.drawImage(
                    reader,
                    _LEFT_MARGIN_PX * scale,  # left edge at the 360px margin
                    y_pt(top + eff_h),
                    width=pg.width_px * s_img * scale,
                    height=eff_h * scale,
                )

                if first_page:
                    # Number in the left margin, right-aligned just left of the
                    # image's left edge. Drawn after the image so it's never
                    # covered. Same placement for both variants (both flush at
                    # the 360px margin).
                    c.setFont(_LABEL_FONT, _LABEL_FONT_PX * scale)
                    c.drawRightString(
                        (_LEFT_MARGIN_PX - _LABEL_GAP_PX) * scale,
                        y_pt(top + _LABEL_TOP_PAD_PX + _LABEL_FONT_PX),
                        block.label,
                    )
                    first_page = False

                used += eff_h

        c.showPage()

    # -- helpers ------------------------------------------------------------

    def _block_height_px(self, block: Block) -> float:
        images = sum(pg.height_px * self._image_scale(pg) for pg in block.pages)
        credit = _CREDIT_BAND_PX if self._credit_for(block) else 0
        return images + credit

    def _page_height_px(self, pg) -> float:
        """Rendered height of one page-image for the current variant: scaled to
        the variant's content width, then clamped to the page capacity for an
        image taller than a whole page (mirrors the clamp in ``render_onto``)."""
        eff_h = pg.height_px * self._image_scale(pg)
        return min(eff_h, float(self.page_capacity_px))

    def _first_unit_height_px(self, block: Block) -> float:
        """Height that must fit in the current page's remaining space for this
        block to *start* here: its credit band (drawn once, above the first
        page) plus the first page-image. Later pages flow onto following pages
        at render time, so they don't gate the block's start."""
        credit = _CREDIT_BAND_PX if self._credit_for(block) else 0
        first = self._page_height_px(block.pages[0]) if block.pages else 0.0
        return credit + first

    def _credit_for(self, block: Block) -> bool:
        """Whether this block gets a provenance credit line drawn above it."""
        return self.show_credit and bool(block.source_label)

    def _draw_chrome(self, c, page_num, header_text, footer_label, scale, y_pt) -> None:
        """Draw the page furniture: purple rule lines, logo, the right-aligned
        header on the top rule, the flush-left footer label, and the page number.
        Called once per page (page 1 restarts each section, so combined PDFs
        number the question and answer papers 1..N independently)."""
        left = _MARGIN_X_PX * scale
        right = (PAGE_W_PX - _MARGIN_X_PX) * scale

        # Rule lines.
        c.setStrokeColor(PURPLE)
        c.setLineWidth(_CHROME_RULE_PX * scale)
        c.line(left, y_pt(_HEADER_LINE_Y_PX), right, y_pt(_HEADER_LINE_Y_PX))
        c.line(left, y_pt(_FOOTER_LINE_Y_PX), right, y_pt(_FOOTER_LINE_Y_PX))

        # Logo top-left, with its *visible* bottom edge a small gap above the
        # header rule. The asset has transparent padding below the mark, so we
        # offset the padded box by that padding to sit the mark on the line.
        logo = _load_logo()
        if logo is not None:
            reader, w_px, h_px, bottom_pad_px = logo
            top_px = _HEADER_LINE_Y_PX - _LOGO_RULE_GAP_PX - h_px + bottom_pad_px
            c.drawImage(
                reader,
                left,
                y_pt(top_px + h_px),
                width=w_px * scale,
                height=h_px * scale,
                mask="auto",
            )

        # Header right-aligned on the top rule; footer label flush-left and the
        # page number flush-right below the footer rule.
        c.setFillGray(0)
        self._draw_page_header(c, header_text, right, scale, y_pt)
        c.setFont(_CHROME_FONT, _CHROME_FONT_PX * scale)
        footer_baseline = y_pt(_FOOTER_LINE_Y_PX + _CHROME_FONT_PX + 20)
        if footer_label:
            c.drawString(left, footer_baseline, footer_label)
        c.drawRightString(right, footer_baseline, f"Page {page_num}")

    def _draw_page_header(self, c, header_text, right, scale, y_pt) -> None:
        """Draw the admin-configured header right-aligned on the top rule.

        Lines stack upward so the *last* line sits on the rule (matching the
        website's former baseline). Any web-address token is turned into a
        clickable link positioned within its right-aligned line."""
        if not header_text:
            return
        lines = header_text.splitlines() or [header_text]
        font_pt = _CHROME_FONT_PX * scale
        c.setFont(_CHROME_FONT, font_pt)
        for i, line in enumerate(reversed(lines)):
            baseline = y_pt(_HEADER_LINE_Y_PX - 15 - i * _CHROME_HEADER_LINE_PX)
            c.drawRightString(right, baseline, line)
            line_left = right - c.stringWidth(line, _CHROME_FONT, font_pt)
            for m in _URL_TOKEN.finditer(line):
                x0 = line_left + c.stringWidth(line[: m.start()], _CHROME_FONT, font_pt)
                x1 = line_left + c.stringWidth(line[: m.end()], _CHROME_FONT, font_pt)
                c.linkURL(
                    _link_target(m.group()),
                    (x0, baseline, x1, baseline + font_pt),
                    relative=0,
                )

    def _draw_cover(self, c, cover, header_text, footer_label, page_num, scale, y_pt) -> None:
        """Render the branded cover page: logo, title, subtitles, the letter
        paragraph, a marks box top-right, a copyright line, and the standard
        page chrome. Drawn as the section's first page."""
        cx = PAGE_W_PX / 2 * scale
        c.setFillGray(0)

        # Logo centered near the top of the content band.
        y = _CONTENT_TOP_PX + 40
        logo = _load_logo(_COVER_LOGO_W_PX)
        if logo is not None:
            reader, w_px, h_px, _ = logo
            c.drawImage(
                reader,
                (PAGE_W_PX - w_px) / 2 * scale,
                y_pt(y + h_px),
                width=w_px * scale,
                height=h_px * scale,
                mask="auto",
            )
            y += h_px + 90
        else:
            y += 200

        # Title + subtitles, centered.
        variant_word = "Questions" if cover.is_questions else "Answers"
        sub1 = f"{cover.subtitle1} – {variant_word}" if cover.subtitle1 else variant_word
        c.setFont(_LABEL_FONT, _COVER_TITLE_FONT_PX * scale)
        c.drawCentredString(cx, y_pt(y + _COVER_TITLE_FONT_PX), cover.title)
        y += _COVER_TITLE_FONT_PX + 60
        c.setFont(_LABEL_FONT, _COVER_SUBTITLE_FONT_PX * scale)
        c.drawCentredString(cx, y_pt(y + _COVER_SUBTITLE_FONT_PX), sub1)
        y += _COVER_SUBTITLE_FONT_PX + 30
        if cover.subtitle2:
            c.drawCentredString(cx, y_pt(y + _COVER_SUBTITLE_FONT_PX), cover.subtitle2)
            y += _COVER_SUBTITLE_FONT_PX + 30

        # Marks box, top-right of the content area.
        self._draw_marks_box(c, cover.total_marks, scale, y_pt)

        # Letter body: sanitized rich text (see app/pdf/cover_body.py) rendered
        # as Platypus Paragraphs in a centered column — Paragraph handles the
        # word-wrap and emits clickable link annotations for <a href> markup.
        col_x = (PAGE_W_PX - _COVER_BODY_W_PX) / 2 * scale
        col_w = _COVER_BODY_W_PX * scale
        by = y + 90
        style = ParagraphStyle(
            "cover_body",
            fontName=_HEADER_FONT,
            fontSize=_COVER_BODY_FONT_PX * scale,
            leading=_COVER_BODY_LINE_PX * scale,
        )
        for markup in to_paragraphs(cover.body):
            if not markup:  # empty <p></p> -> blank-line gap
                by += _COVER_BODY_LINE_PX
                continue
            para = Paragraph(markup, style)
            _, h = para.wrap(col_w, y_pt(0))
            para.drawOn(c, col_x, y_pt(by) - h)
            # Advance past the paragraph, plus one blank line between paragraphs.
            by += h / scale + _COVER_BODY_LINE_PX

        # Copyright, just above the footer rule.
        c.setFont(_HEADER_FONT, _COVER_COPYRIGHT_FONT_PX * scale)
        c.drawCentredString(cx, y_pt(_CONTENT_BOTTOM_PX - 20), _COVER_COPYRIGHT)

        self._draw_chrome(c, page_num, header_text, footer_label, scale, y_pt)

    def _draw_marks_box(self, c, total_marks, scale, y_pt) -> None:
        """A bordered score box top-right of the cover: ``____ / {total}``."""
        right = PAGE_W_PX - _MARGIN_X_PX
        left = right - _MARKS_BOX_W_PX
        top = _CONTENT_TOP_PX
        c.setStrokeColor(PURPLE)
        c.setLineWidth(_CHROME_RULE_PX * scale)
        c.rect(
            left * scale,
            y_pt(top + _MARKS_BOX_H_PX),
            _MARKS_BOX_W_PX * scale,
            _MARKS_BOX_H_PX * scale,
        )
        c.setFillGray(0)
        c.setFont(_LABEL_FONT, _MARKS_BOX_FONT_PX * scale)
        c.drawCentredString(
            (left + _MARKS_BOX_W_PX / 2) * scale,
            y_pt(top + _MARKS_BOX_H_PX / 2 + _MARKS_BOX_FONT_PX / 2),
            f"______ / {total_marks}",
        )

    def _draw_instructions(self, c, additional_instructions, scale, y_pt) -> None:
        c.setFont(_HEADER_FONT, _HEADER_FONT_PX * scale)
        top = _CONTENT_TOP_PX + _HEADER_FONT_PX
        for line in (additional_instructions.splitlines() or [additional_instructions]):
            c.drawString(_LEFT_MARGIN_PX * scale, y_pt(top), line)
            top += _HEADER_LINE_PX

    @staticmethod
    def _image_reader(raw: bytes) -> ImageReader:
        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.mode != "RGB":
            img = img.convert("RGB")
        return ImageReader(img)


def render_combined(sections: list[tuple[LayoutEngine, LayoutPlan]], fetch_bytes) -> bytes:
    """Render several (engine, plan) sections into one PDF, each starting on a
    fresh page — e.g. the question paper followed by the answer paper."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for engine, plan in sections:
        engine.render_onto(c, plan, fetch_bytes)
    c.save()
    return buf.getvalue()
