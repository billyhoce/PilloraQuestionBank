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
from dataclasses import dataclass, field

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# A4 @ 300 DPI. PAGE_W_PX matches the standardized image canvas width; PAGE_H_PX
# follows from the A4 aspect ratio so px map 1:1 onto the page after scaling.
PAGE_W_PX = 2480
PAGE_H_PX = 3508
_TOP_MARGIN_PX = 120
_BOTTOM_MARGIN_PX = 120
_DEFAULT_CAPACITY_PX = PAGE_H_PX - _TOP_MARGIN_PX - _BOTTOM_MARGIN_PX

# Page margins. Both variants leave a 360px gutter on the left where the question
# number sits. Question images are scaled to a fixed 1760px content width and sit
# centered on the page (1760 + 360 + 360 = 2480). Answer images keep their
# original size (≤ 1760px from ingestion), flush to the left margin, so they never
# extend past the right edge (360 + 1760 < 2480).
_TARGET_CONTENT_W_PX = 1760           # question-variant content width
_LEFT_MARGIN_PX = (PAGE_W_PX - _TARGET_CONTENT_W_PX) // 2  # 360
_ANSWER_GAP_PX = 100                   # vertical gap between consecutive answer blocks

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
_CREDIT_FONT_PX = 34  # ~10pt at 300 DPI
_CREDIT_GAP_PX = 18   # gap between the credit line and the image below it
_CREDIT_BAND_PX = _CREDIT_FONT_PX + _CREDIT_GAP_PX  # vertical space one credit reserves
_CREDIT_GREY = 0.35


def _header_height_px(header_text: str) -> int:
    """Vertical band reserved for the header on the first page (0 if no header)."""
    if not header_text:
        return 0
    lines = header_text.splitlines() or [header_text]
    return len(lines) * _HEADER_LINE_PX + _HEADER_PAD_PX


@dataclass
class Block:
    """One question's worth of pages for a single PDF variant."""

    label: str            # renumbered position: "1", "2", …
    source_label: str     # e.g. "Raffles Institution 2024 Sec 3 EOY Q5" (kept for future use)
    pages: list           # QuestionPage-like rows (image_key, width_px, height_px), in order
    page_index: int = 0   # first page this block appears on; set by compute_layout


@dataclass
class LayoutPlan:
    page_count: int
    blocks: list[Block]
    header_text: str = ""


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
        self.block_gap_px = 0 if fit_width else _ANSWER_GAP_PX

    def _image_scale(self, pg) -> float:
        """Uniform scale factor applied to an image for the current variant."""
        if self.fit_width:
            return _TARGET_CONTENT_W_PX / pg.width_px
        return 1.0

    def compute_layout(self, blocks: list[Block], header_text: str = "") -> LayoutPlan:
        """Assign each block the page it starts on, packing greedily by height.

        ``page_count`` is a lower bound — a block taller than a page overflows onto
        further pages at render time, which this pagination does not count.
        """
        header_px = _header_height_px(header_text)
        page = 0
        cursor = header_px  # px used on the current page (header reserved on page 0)
        for block in blocks:
            h = self._block_height_px(block)
            gap = self.block_gap_px if cursor > 0 else 0
            if cursor > 0 and cursor + gap + h > self.page_capacity_px:
                page += 1
                cursor = 0
                gap = 0
            block.page_index = page
            cursor += gap + h
        page_count = page + 1 if blocks else 1
        return LayoutPlan(page_count=page_count, blocks=blocks, header_text=header_text)

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

        used = 0.0  # px consumed in the content area of the current page

        header_px = _header_height_px(plan.header_text)
        if header_px:
            self._draw_header(c, plan.header_text, scale, y_pt)
            used = header_px

        for block in plan.blocks:
            block_h = self._block_height_px(block)
            gap = self.block_gap_px if used > 0 else 0
            if used > 0 and used + gap + block_h > self.page_capacity_px:
                c.showPage()
                used = 0.0
                gap = 0
            used += gap

            if self._credit_for(block):
                c.setFont(_CREDIT_FONT, _CREDIT_FONT_PX * scale)
                c.setFillGray(_CREDIT_GREY)
                c.drawString(
                    _LEFT_MARGIN_PX * scale,
                    y_pt(_TOP_MARGIN_PX + used + _CREDIT_FONT_PX),
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
                if used > 0 and used + eff_h > self.page_capacity_px:
                    c.showPage()
                    used = 0.0

                reader = self._image_reader(fetch_bytes(pg.image_key))
                top = _TOP_MARGIN_PX + used
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

    def _credit_for(self, block: Block) -> bool:
        """Whether this block gets a provenance credit line drawn above it."""
        return self.show_credit and bool(block.source_label)

    def _draw_header(self, c, header_text, scale, y_pt) -> None:
        c.setFont(_HEADER_FONT, _HEADER_FONT_PX * scale)
        top = _TOP_MARGIN_PX + _HEADER_FONT_PX
        for line in (header_text.splitlines() or [header_text]):
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
