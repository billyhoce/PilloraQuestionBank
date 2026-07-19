"""Synthetic sample data for driving the PDF layout engine without a database.

Used by ``scripts/generate_sample_pdf.py`` (and its tests) to build engine-ready
``Block``s backed by deterministic placeholder images generated in memory with
PIL. The placeholder heights cycle through a schedule chosen to exercise the
layout edge cases: small blocks that pack together, a near-page-filling block,
a multi-page block that overflows ``compute_layout``'s page estimate, and a
single image taller than a page (which the renderer shrinks to fit).

Everything here is deterministic: the same inputs always produce the same
images, so rendered pages can be compared pixel-for-pixel across code changes.
"""
import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from app.pdf.layout_engine import PAGE_W_PX, Block

# Question pages use the standardized 2480px canvas width (see
# docs/DATA_MODEL.md); answer pages keep their native size at render time and
# are ≤1760px wide from ingestion, so the sample widths respect that too.
_QUESTION_W_PX = PAGE_W_PX

# Per-question page heights (question variant), cycled by question position.
# At the question-variant scale (1760/2480 ≈ 0.71) and a ~2948px page budget:
#   800/1500/400  — small blocks that pack several to a page
#   2900          — nearly page-filling
#   2000 + 2900   — a two-image block taller than a page, so its images flow
#                   onto an extra page that compute_layout's estimate misses
#   4500          — one image taller than a page; the renderer shrinks it
_QUESTION_HEIGHTS = [
    (800,),
    (1500,),
    (400,),
    (2900,),
    (2000, 2900),
    (4500,),
]

# Per-question answer pages as (width, height), cycled by question position.
# Widths vary (answers render at native size, flush left); position 3 has no
# answer pages, so the answer paper skips it while reserving its number —
# mirroring _blocks_for in app/routes/generate.py.
_ANSWER_PAGES = [
    ((1200, 600),),
    ((1760, 900),),
    (),
    ((1500, 2900),),
    ((1000, 500), (1600, 800)),
    ((1760, 1200),),
]

_BORDER_PX = 4
_RULE_SPACING_PX = 120
_ANSWER_TINT = (243, 243, 252)  # faint blue-grey so answer pages stand apart


@dataclass
class SamplePage:
    """Duck-type stand-in for a ``QuestionPage`` ORM row.

    The engine reads ``image_key``/``width_px``/``height_px``; ``page_order``
    and ``page_type`` mirror the real row so callers can sort/filter the same
    way the route does.
    """

    image_key: str
    width_px: int
    height_px: int
    page_order: int
    page_type: str


def _label_font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1: no size support on the default font
        return ImageFont.load_default()


def make_page_png(width_px: int, height_px: int, label: str, tint=None) -> bytes:
    """A deterministic placeholder page image as PNG bytes.

    Bordered, with light horizontal rules (stand-ins for text lines), a
    diagonal cross so cropping/scaling mistakes are visible, and ``label``
    drawn top-left and centered so every page identifies itself in the output.
    """
    img = Image.new("RGB", (width_px, height_px), color=tint or (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle(
        (0, 0, width_px - 1, height_px - 1), outline=(60, 60, 60), width=_BORDER_PX
    )
    for y in range(_RULE_SPACING_PX, height_px - _BORDER_PX, _RULE_SPACING_PX):
        d.line((60, y, width_px - 60, y), fill=(225, 225, 225), width=2)
    d.line((0, 0, width_px, height_px), fill=(210, 210, 210), width=2)
    d.line((0, height_px, width_px, 0), fill=(210, 210, 210), width=2)
    font = _label_font(min(90, max(24, height_px // 8)))
    d.text((40, 24), label, fill=(120, 120, 120), font=font)
    d.text(
        (width_px / 2, height_px / 2),
        label,
        fill=(170, 170, 170),
        font=font,
        anchor="mm",
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _pages_spec(position: int, variant: str) -> list[tuple[int, int]]:
    """(width, height) list for question ``position`` (1-based) in ``variant``."""
    if variant == "question":
        heights = _QUESTION_HEIGHTS[(position - 1) % len(_QUESTION_HEIGHTS)]
        return [(_QUESTION_W_PX, h) for h in heights]
    return list(_ANSWER_PAGES[(position - 1) % len(_ANSWER_PAGES)])


def build_sample_blocks(
    n_questions: int, variant: str, image_paths: list[str] | None = None
) -> tuple[list[Block], dict[str, bytes]]:
    """Engine-ready ``Block``s plus their backing images.

    Returns ``(blocks, images)`` where ``images`` maps each page's
    ``image_key`` to its bytes — pass ``fetch_bytes=images.__getitem__`` to
    ``LayoutEngine.render``. ``variant`` is ``"question"`` or ``"answer"``.
    With ``image_paths``, real image files (cycled) replace the synthetic
    pages, one page per question.
    """
    if variant not in ("question", "answer"):
        raise ValueError(f"variant must be 'question' or 'answer', got {variant!r}")
    blocks: list[Block] = []
    images: dict[str, bytes] = {}
    tint = _ANSWER_TINT if variant == "answer" else None
    prefix = "A" if variant == "answer" else "Q"
    for i in range(1, n_questions + 1):
        pages: list[SamplePage] = []
        if image_paths:
            path = image_paths[(i - 1) % len(image_paths)]
            raw = open(path, "rb").read()
            with Image.open(io.BytesIO(raw)) as img:
                w, h = img.size
            key = f"sample/{variant}-{i}-p1"
            images[key] = raw
            pages.append(SamplePage(key, w, h, page_order=1, page_type=variant))
        else:
            for order, (w, h) in enumerate(_pages_spec(i, variant), start=1):
                key = f"sample/{variant}-{i}-p{order}"
                # ASCII only: PIL's default font has no glyphs for em dash etc.
                label = f"{prefix}{i} page {order} - {w}x{h}px"
                images[key] = make_page_png(w, h, label, tint=tint)
                pages.append(SamplePage(key, w, h, page_order=order, page_type=variant))
        if variant == "answer" and not pages:
            continue  # no answer pages: skip the block, its number stays reserved
        blocks.append(
            Block(
                label=str(i),
                source_label=f"[Sample School/2025/Prelim/1/Q{i}]",
                pages=pages,
            )
        )
    return blocks, images


def sample_marks(n_questions: int) -> int:
    """Deterministic plausible marks total for the cover's marks box."""
    return sum(2 + (i % 4) for i in range(1, n_questions + 1))
