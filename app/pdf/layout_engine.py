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
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import Image
from reportlab.lib.colors import Color
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from app.pdf.rich_text import is_blank, to_paragraphs

# A4 @ 300 DPI. PAGE_W_PX matches the standardized image canvas width; PAGE_H_PX
# follows from the A4 aspect ratio so px map 1:1 onto the page after scaling.
PAGE_W_PX = 2480
PAGE_H_PX = 3508

# Points per pixel. Every length in this module is in 300-DPI px; ReportLab
# works in points, so anything handed to the canvas (or to a ParagraphStyle) is
# multiplied by this. It is a constant of the page geometry, which lets text be
# measured at import time and at layout time, not just at render time.
PT_PER_PX = A4[0] / PAGE_W_PX

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
_CHROME_LINE_PX = 52                   # line advance for the header and footer text
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
# Appended to the cover title so the two papers are told apart at a glance. It is
# the *only* difference between the two covers' headings — title and subtitles
# are otherwise identical — and the letter body is question-paper-only.
_QUESTION_TITLE_SUFFIX = "Question Paper"
_ANSWER_TITLE_SUFFIX = "Answer Key"
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

# Additional instructions: the exam instructions band on the first content page.
_INSTRUCTIONS_FONT = "Helvetica"
_INSTRUCTIONS_FONT_PX = 42  # ~12pt at 300 DPI
_INSTRUCTIONS_LINE_PX = 58
_INSTRUCTIONS_PAD_PX = 40   # clearance between the band and the first question

# Per-question provenance credit (question paper only). Drawn just above each
# question in small grey type; the whole band is reserved in the block height so
# packing and rendering agree.
_CREDIT_FONT = "Helvetica"
_CREDIT_FONT_PX = 40  # ~11.5pt at 300 DPI
_CREDIT_GAP_PX = 18   # gap between the credit line and the image below it
_CREDIT_BAND_PX = _CREDIT_FONT_PX + _CREDIT_GAP_PX  # vertical space one credit reserves
_CREDIT_GREY = 0.35

# -- rich text ---------------------------------------------------------------
# The page header, the additional instructions, the footer and the cover body are
# all authored in the same editor and sanitized to Platypus markup by
# app/pdf/rich_text.py, so all four support bold/italic/underline and blue
# clickable links. They differ only in their style and the column they fill.


def _rich_style(name, font_px, line_px, alignment=TA_LEFT, font=_CHROME_FONT):
    """A ParagraphStyle from 300-DPI px sizes."""
    return ParagraphStyle(
        name,
        fontName=font,
        fontSize=font_px * PT_PER_PX,
        leading=line_px * PT_PER_PX,
        alignment=alignment,
    )


_PAGE_HEADER_STYLE = _rich_style("page_header", _CHROME_FONT_PX, _CHROME_LINE_PX, TA_RIGHT)
_FOOTER_STYLE = _rich_style("footer", _CHROME_FONT_PX, _CHROME_LINE_PX)
_INSTRUCTIONS_STYLE = _rich_style(
    "instructions", _INSTRUCTIONS_FONT_PX, _INSTRUCTIONS_LINE_PX, font=_INSTRUCTIONS_FONT
)
_COVER_BODY_STYLE = _rich_style("cover_body", _COVER_BODY_FONT_PX, _COVER_BODY_LINE_PX)

# Header column: right-aligned, running from just right of the logo to the right
# margin, so a long line wraps instead of colliding with the logo. The block's
# bottom edge sits _PAGE_HEADER_RULE_GAP_PX above the rule, which is what puts
# the *last* line on the rule however many lines there are.
_PAGE_HEADER_X_PX = _MARGIN_X_PX + _LOGO_W_PX + 60
_PAGE_HEADER_W_PX = PAGE_W_PX - _MARGIN_X_PX - _PAGE_HEADER_X_PX
_PAGE_HEADER_RULE_GAP_PX = 5

# Footer text: flush-left below the footer rule, its column stopping short of the
# bottom-right page number. A Paragraph's first baseline sits one fontSize below
# its top edge, which is how the footer text and the page number — drawn as a
# bare string at that baseline — end up on one line.
_FOOTER_TOP_PX = _FOOTER_LINE_Y_PX + 20
_FOOTER_BASELINE_PX = _FOOTER_TOP_PX + _CHROME_FONT_PX
_PAGE_NUM_W_PX = 300
_FOOTER_W_PX = PAGE_W_PX - 2 * _MARGIN_X_PX - _PAGE_NUM_W_PX


def _measure_rich(body: str, style: ParagraphStyle, width_px: float, gap_px: float = 0):
    """Wrap rich text into drawable paragraphs for a ``width_px``-wide column.

    Returns ``(items, total_height_px)``, each item ``(Paragraph | None,
    advance_px)`` — ``None`` for an empty paragraph, which advances one blank
    line. ``gap_px`` follows every paragraph. Measuring and drawing go through
    this one call, so the space a block reserves during layout is the space it
    occupies when rendered.
    """
    items: list[tuple[Paragraph | None, float]] = []
    total = 0.0
    line_px = style.leading / PT_PER_PX
    for markup in to_paragraphs(body or ""):
        if not markup:
            items.append((None, line_px))
            total += line_px
            continue
        para = Paragraph(markup, style)
        _, h_pt = para.wrap(width_px * PT_PER_PX, PAGE_H_PX * PT_PER_PX)
        advance = h_pt / PT_PER_PX + gap_px
        items.append((para, advance))
        total += advance
    return items, total


def _draw_rich(c, items, x_px: float, top_px: float, y_pt) -> None:
    """Draw measured paragraphs down the page from ``top_px``, at ``x_px``."""
    y = top_px
    for para, advance in items:
        if para is not None:
            para.drawOn(c, x_px * PT_PER_PX, y_pt(y + para.height / PT_PER_PX))
        y += advance


def _instructions_height_px(additional_instructions: str) -> float:
    """Vertical band reserved for the instructions on the first page (0 if none)."""
    if is_blank(additional_instructions):
        return 0
    _, total = _measure_rich(
        additional_instructions, _INSTRUCTIONS_STYLE, _TARGET_CONTENT_W_PX
    )
    return total + _INSTRUCTIONS_PAD_PX


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

    title: str            # e.g. "Topical Worksheets"; the variant suffix is appended
    subtitle1: str        # topic/subject line, drawn verbatim on both variants
    subtitle2: str        # e.g. "2024 Prelim"
    body: str             # the letter: rich-text HTML (<p>/<b>/<i>/<u>/<a href>,
                          # sanitized by app/pdf/rich_text.py) or legacy plain text.
                          # Drawn on the question cover only.
    total_marks: int      # shown in the top-right marks box
    is_questions: bool    # True → "… - Question Paper", False → "… - Answer Key"


def _cover_title(cover: "CoverSpec") -> str:
    """The cover heading: the chosen title plus the per-variant suffix. With no
    title configured the suffix stands alone rather than dangling off a dash."""
    suffix = _QUESTION_TITLE_SUFFIX if cover.is_questions else _ANSWER_TITLE_SUFFIX
    return f"{cover.title} - {suffix}" if cover.title else suffix


@dataclass(frozen=True)
class PageChrome:
    """The branded furniture drawn around a section's content.

    Passed into ``compute_layout`` so the plan it returns is complete. These
    fields used to be assigned onto the returned plan by each caller, which made
    forgetting one a silent defect — the PDF renders fine, just with no header —
    and only visible by eye in the output.
    """

    header_text: str = ""    # branding, right-aligned on the top rule of every page
    footer_label: str = ""   # flush-left under the footer rule on every page
    cover: "CoverSpec | None" = None  # rendered as the section's first page


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

    def compute_layout(
        self,
        blocks: list[Block],
        additional_instructions: str = "",
        chrome: "PageChrome | None" = None,
    ) -> LayoutPlan:
        """Assign each block the page it starts on, packing greedily by height.

        A block starts a new page only when its *first* page-image (plus the
        credit band) won't fit in the remaining space; a multi-page block then
        flows its later pages onto following pages, exactly as ``render_onto``
        renders it. This walk mirrors that flow, so ``page_count`` counts those
        overflow pages too.

        ``chrome`` carries the header/footer/cover so the returned plan is ready
        to render; omitting it yields an unchromed plan (bare pages), which is
        what the layout-only tests want.
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
        chrome = chrome or PageChrome()
        return LayoutPlan(
            page_count=page_count,
            blocks=blocks,
            additional_instructions=additional_instructions,
            header_text=chrome.header_text,
            footer_label=chrome.footer_label,
            cover=chrome.cover,
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

        # Header right-aligned on the top rule; footer text flush-left and the
        # page number flush-right below the footer rule.
        c.setFillGray(0)
        self._draw_page_header(c, header_text, y_pt)
        self._draw_footer(c, footer_label, y_pt)
        c.setFont(_CHROME_FONT, _CHROME_FONT_PX * scale)
        c.drawRightString(right, y_pt(_FOOTER_BASELINE_PX), f"Page {page_num}")

    def _draw_page_header(self, c, header_text, y_pt) -> None:
        """Draw the admin-configured header, right-aligned on the top rule.

        Rich text (see app/pdf/rich_text.py): links render blue, underlined and
        clickable. The block is bottom-aligned to the rule, so its lines stack
        *upward* and the last one sits on the rule however many there are."""
        if is_blank(header_text):
            return
        items, total_px = _measure_rich(header_text, _PAGE_HEADER_STYLE, _PAGE_HEADER_W_PX)
        top_px = _HEADER_LINE_Y_PX - _PAGE_HEADER_RULE_GAP_PX - total_px
        _draw_rich(c, items, _PAGE_HEADER_X_PX, top_px, y_pt)

    def _draw_footer(self, c, footer_label, y_pt) -> None:
        """Draw the footer rich text flush-left below the footer rule, in a
        column that stops short of the bottom-right page number."""
        if is_blank(footer_label):
            return
        items, _ = _measure_rich(footer_label, _FOOTER_STYLE, _FOOTER_W_PX)
        _draw_rich(c, items, _MARGIN_X_PX, _FOOTER_TOP_PX, y_pt)

    def _draw_cover(self, c, cover, header_text, footer_label, page_num, scale, y_pt) -> None:
        """Render the branded cover page: logo, title, subtitles, the letter
        paragraph, a marks box top-right, and the standard page chrome. Drawn as
        the section's first page.

        The two sections' covers are deliberately near-identical: same subtitles,
        same title bar the ``" - Question Paper"`` / ``" - Answer Key"`` suffix,
        and the letter body on the question paper only."""
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

        # Title + subtitles, centered. The variant only shows in the title.
        c.setFont(_LABEL_FONT, _COVER_TITLE_FONT_PX * scale)
        c.drawCentredString(cx, y_pt(y + _COVER_TITLE_FONT_PX), _cover_title(cover))
        y += _COVER_TITLE_FONT_PX + 60
        c.setFont(_LABEL_FONT, _COVER_SUBTITLE_FONT_PX * scale)
        if cover.subtitle1:
            c.drawCentredString(cx, y_pt(y + _COVER_SUBTITLE_FONT_PX), cover.subtitle1)
            y += _COVER_SUBTITLE_FONT_PX + 30
        if cover.subtitle2:
            c.drawCentredString(cx, y_pt(y + _COVER_SUBTITLE_FONT_PX), cover.subtitle2)
            y += _COVER_SUBTITLE_FONT_PX + 30

        # Marks box, top-right of the content area.
        self._draw_marks_box(c, cover.total_marks, scale, y_pt)

        # Letter body: sanitized rich text (see app/pdf/rich_text.py) rendered as
        # Platypus Paragraphs in a centered column — Paragraph handles the
        # word-wrap and emits clickable link annotations for <a href> markup.
        # Question paper only: the answer key's cover carries no letter.
        if cover.is_questions:
            items, _ = _measure_rich(
                cover.body, _COVER_BODY_STYLE, _COVER_BODY_W_PX, gap_px=_COVER_BODY_LINE_PX
            )
            _draw_rich(c, items, (PAGE_W_PX - _COVER_BODY_W_PX) / 2, y + 90, y_pt)

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
        """Draw the instructions rich text across the content width, at the top
        of the first content page. ``_instructions_height_px`` reserved exactly
        this much space during layout."""
        items, _ = _measure_rich(
            additional_instructions, _INSTRUCTIONS_STYLE, _TARGET_CONTENT_W_PX
        )
        _draw_rich(c, items, _LEFT_MARGIN_PX, _CONTENT_TOP_PX, y_pt)

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
