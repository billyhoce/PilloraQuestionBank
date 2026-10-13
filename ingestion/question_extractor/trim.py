"""Trimming the whitespace off a crop, once its boundaries are settled.

The boundary stage draws each crop on *calibrated* edges: left ``x_cut``, right
``content_right``, and horizontal cuts placed in the whitespace between one
question and the next. Those edges answer "where does this question's share of
the page begin and end", and the bands they produce tile the page with no gaps.
They leave a wide margin, because a question's share of the page is bigger than
the question.

This stage shrinks each rectangle onto the question's own ink, on three sides.
The bottom is left where the boundary stage put it: the blank space under a
question is the space the candidate writes in, so it belongs to the question it
was left for. A graph-grid page is the exception, and for the same reason: there
the grid is the writing space, so what lies below it is margin and goes.

It runs *after* the boundaries are decided and only ever makes a rectangle
smaller, so which content belongs to which question is settled before this module
sees it, and cannot be changed by it. Crops stop tiling the page horizontally:
the margin either side of a question now belongs to neither, and nothing is lost
by that, because ink outside every crop is either that whitespace or the running
header and footer the body band already excluded.

Two passes, in this order, and the order is the point:

1. **Ink geometry.** Text span boxes and figure boxes, which is where the paper's
   own structure is known — a divider rule is not content (``collect_figures``
   has already set them aside) and neither is the question number in the gutter.
2. **Rendered pixels**, inside the box the first pass produced. A pixel scan on
   its own cannot do this job: run over the untrimmed crop it stops dead on the
   divider rule sitting exactly on the bottom boundary, and on the sliver of
   question number that overhangs ``x_cut`` — 59 of 104 edges of the sample paper
   gained nothing at all that way. Once geometry has excluded both, the pixels
   are safe to trust, and they find the whitespace that glyph boxes and padded
   image bounding boxes overstate.

Where geometry has nothing to say, though, the pixels *are* the geometry. A
scanned paper is one page-sized image per page and no vector paths at all: the
image box is discarded as a background fill, because covering everything it
locates nothing, and what is left is the OCR'd text layer, which does not see a
single drawn line. On the sample scan's p13 that left the topmost "ink" in Q9's
band as the diagram's own label ``S``, and the crop clipped 12pt off the circle
above it. So on such a page — and only there, tested by the same page-sized image
that caused the blindness — a pixel scan of the *untrimmed* band is unioned into
the first pass's box.

That scan needs the floor the geometry pass would otherwise have provided.
Unfiltered it finds a two-pixel scanner speck 31.7pt above p6's real text, and
the 1-3px gutter sliver of question number that ``content_ink`` exists to
exclude, 12pt left of p17's text. Both are under a point of ink per row; the arc
it must find is 1.67pt on its first row and 40-80px five rows in, so a minimum
ink span per row and column separates them cleanly. ``trim_min_ink_span`` carries
the measurements. Note the union: a pale patch the scan misses still keeps
whatever the text layer knew about.

The floor answers the sliver only where the sliver is thin *along* the column it
occupies. A question number set hard against ``x_cut`` gives a different sliver:
one pixel column wide and a whole digit tall, which the floor passes and which
pins the left edge back on the cut — p15's ``10`` crosses it by 0.77pt and cost
the whole left trim. So the scan starts ``trim_gutter_inset`` right of the crop's
left edge, which is far enough past the widest overhang measured and nowhere near
the nearest content.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

from .boundaries import Band, PageResult
from .calibration import Calibration
from .config import ExtractConfig
from .figures import PageFigures, overlapping_figures
from .gridpage import GridPage
from .furniture import Furniture
from .geometry import PageGeometry, TextLine

log = logging.getLogger(__name__)


def trim_bands(
    pdf_path: Path,
    pages: list[PageGeometry],
    furniture: Furniture,
    calibration: Calibration,
    results: list[PageResult],
    config: ExtractConfig,
) -> None:
    """Shrink every band's rectangle onto its own ink, in place.

    The source PDF is opened for the pixel pass and never saved. A band whose
    rectangle holds no ink in the content column keeps its untrimmed rectangle.
    """
    geometry = {geom.number: geom for geom in pages}

    with pymupdf.open(pdf_path) as doc:
        for result in results:
            geom = geometry.get(result.page)
            if geom is None or not result.bands or result.figures is None:
                continue
            lines = furniture.body_lines(geom)
            page = doc[result.page - 1]
            for band in result.bands:
                _trim(
                    band,
                    page,
                    geom,
                    lines,
                    result.figures,
                    calibration,
                    config,
                    result.grid,
                )

    trimmed = sum(
        1
        for result in results
        for band in result.bands
        if band.partition is not None and band.rect != band.partition
    )
    log.info("trimmed %d band rectangle(s) onto their ink", trimmed)


def _trim(
    band: Band,
    page: pymupdf.Page,
    geom: PageGeometry,
    lines: list[TextLine],
    figures: PageFigures,
    calibration: Calibration,
    config: ExtractConfig,
    grid: GridPage | None = None,
) -> None:
    """Replace one band's rectangle with its trimmed version."""
    ink, pixel_ink = _ink_box(
        band.rect, page, geom, lines, figures, calibration, config, grid
    )
    if ink is None:
        log.warning(
            "page %d: question %d has no ink in the content column; "
            "keeping the untrimmed rectangle",
            band.page,
            band.number,
        )
        return

    trimmed = _shrink(band.rect, ink, config)

    if band.grid_page:
        # The one place the bottom is trimmed. The rule that keeps it - blank space
        # under a question is the space the candidate writes in - is exactly what a
        # grid page has no room for: the grid *is* the writing space, and what lies
        # below it is page margin. Measured against the ink rather than the grid, so
        # a mark allocation or an instruction printed under the grid still holds the
        # edge open.
        trimmed = pymupdf.Rect(
            trimmed.x0, trimmed.y0, trimmed.x1, min(trimmed.y1, ink.y1 + config.crop_pad)
        )

    # The pixel pass looks only at the region the ink occupies, not at the answer
    # space kept below it. That space is blank but for the divider rule marking the
    # boundary, and a rule running the full width of the page would stop the side
    # edges tightening at all — on the sample paper it cost 4pt on the right.
    probe = pymupdf.Rect(
        trimmed.x0, trimmed.y0, trimmed.x1, min(trimmed.y1, ink.y1 + config.crop_pad)
    )
    pixels = _pixel_box(page, probe, config)
    if pixels is not None:
        trimmed = _shrink(trimmed, pixels, config)

    if trimmed.is_empty or trimmed.height <= 1.0 or trimmed.width <= 1.0:
        log.warning(
            "page %d: question %d trimmed to a degenerate rectangle "
            "(%.1f x %.1f); keeping the untrimmed one",
            band.page,
            band.number,
            trimmed.width,
            trimmed.height,
        )
        return

    band.rect = trimmed
    band.pixel_ink_box = pixel_ink


def _ink_box(
    rect: pymupdf.Rect,
    page: pymupdf.Page,
    geom: PageGeometry,
    lines: list[TextLine],
    figures: PageFigures,
    calibration: Calibration,
    config: ExtractConfig,
    grid: GridPage | None = None,
) -> tuple[pymupdf.Rect | None, pymupdf.Rect | None]:
    """Box enclosing every piece of ink inside ``rect``, and the pixels' share of it.

    Returns the box, or ``None`` if ``rect`` holds no ink, together with the box
    the pixel fallback contributed, or ``None`` where it did not run.

    Every figure box counts, not just the ones big enough to read as a figure: a
    fraction bar is a few points tall and it is still ink. Which figures belong
    to the band is decided by the same rule the crop itself used, so the
    threshold lives in one place.

    A graph grid is added whole, before anything is clipped to ``x_cut``. That cut
    exists to keep the question number in the gutter out of the crop, and it is
    the wrong instrument here: the grid legitimately starts left of it, and
    clipping the grid to it is what left the left-hand columns outside the crop.

    On a scanned page none of those sources sees the drawn content, so the
    rendered pixels are read as well and unioned in — see the module docstring for
    why that is confined to such a page and why the scan carries an ink floor.
    """
    box: pymupdf.Rect | None = None

    if grid is not None:
        # Clipped to the band, like any figure: a grid page holding two questions
        # gives each of them its own slice of the grid, not the whole sheet.
        box = _grown(
            box,
            pymupdf.Rect(
                grid.bbox.x0,
                max(grid.bbox.y0, rect.y0),
                grid.bbox.x1,
                min(grid.bbox.y1, rect.y1),
            ),
        )

    for line in lines:
        if line.y1 <= rect.y0 or line.y0 >= rect.y1:
            continue
        ink = line.content_ink(calibration.x_cut)
        if ink is not None:
            box = _grown(box, ink)

    for figure in overlapping_figures(figures.figures, rect.y0, rect.y1, config):
        if figure.x1 <= calibration.x_cut:
            continue  # gutter decoration, outside the crop by design
        clipped = pymupdf.Rect(
            max(figure.x0, calibration.x_cut),
            max(figure.y0, rect.y0),
            figure.x1,
            min(figure.y1, rect.y1),
        )
        box = _grown(box, clipped)

    pixel_ink: pymupdf.Rect | None = None
    if config.trim_pixel_fallback and geom.has_page_sized_image(
        config.figure_max_area_frac
    ):
        # Started a little right of the crop's left edge, which is ``x_cut``: a
        # question number pressed against the cut spills a fraction of a point
        # over it, and a scan renders that spill as a column of ink the floor
        # below cannot reject. Clamped to the content column so the inset can
        # never eat into it; see ``trim_gutter_inset``.
        scan = pymupdf.Rect(
            max(rect.x0, min(rect.x0 + config.trim_gutter_inset, calibration.content_x)),
            rect.y0,
            rect.x1,
            rect.y1,
        )
        pixel_ink = _pixel_box(page, scan, config, min_ink=config.trim_min_ink_span)
        if pixel_ink is not None:
            box = _grown(box, pixel_ink)

    return box, pixel_ink


def _grown(box: pymupdf.Rect | None, addition: pymupdf.Rect) -> pymupdf.Rect:
    """``box`` widened to hold ``addition``, or ``addition`` if there is no box.

    Built from explicit ``min``/``max`` rather than ``Rect.__or__``, which returns
    the other operand untouched when one of them is what PyMuPDF calls empty — and
    a rule drawn as a stroke has no width or no height, so every one of them is
    empty by that definition. Unioning with ``|`` silently loses them, which is
    how a page of vertical rules came out trimmed to a strip of itself.
    """
    if box is None:
        return pymupdf.Rect(addition)
    return pymupdf.Rect(
        min(box.x0, addition.x0),
        min(box.y0, addition.y0),
        max(box.x1, addition.x1),
        max(box.y1, addition.y1),
    )


def _pixel_box(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    config: ExtractConfig,
    min_ink: float = 0.0,
) -> pymupdf.Rect | None:
    """Box enclosing the non-white pixels of ``rect``, or ``None`` if it is blank.

    The box is expanded outward onto the pixel grid, so it always contains the
    ink it found. A coarser ``--zoom`` therefore makes this pass less effective
    but never makes it clip, which is why the render scale is reused here instead
    of adding a resolution of its own.

    ``min_ink`` is the ink a row or column needs, in points, before it counts at
    all. It defaults to nothing, which is right after the geometry pass has
    already excluded the things a pixel scan would trip over. The fallback on a
    scanned page has no such pass in front of it and sets a floor instead; see
    the module docstring, and ``trim_min_ink_span`` for the measurements.
    """
    if rect.is_empty:
        return None

    zoom = config.zoom
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(zoom, zoom),
        clip=rect,
        colorspace=pymupdf.csGRAY,
        alpha=False,
    )
    width, height, stride = pixmap.width, pixmap.height, pixmap.stride
    if width == 0 or height == 0 or pixmap.n != 1:
        return None

    # One byte per pixel, thresholded by a translation table to 1 (ink) or 0
    # (paper), so a row's ink is counted by one C-level scan rather than a Python
    # loop over a couple of million pixels.
    table = bytes(1 if value < config.trim_luminance else 0 for value in range(256))
    floor = max(1, int(min_ink * zoom))
    samples = pixmap.samples

    first_row = last_row = None
    columns = [0] * width
    # A chunk of rows is added column-wise as a single big integer, each byte of
    # which is one column's running count. 255 rows is the most that can be added
    # before a byte could carry into the column next to it.
    chunk = 0
    chunk_rows = 0

    for y in range(height):
        row = samples[y * stride : y * stride + width].translate(table)
        if row.count(1) < floor:
            continue
        if first_row is None:
            first_row = y
        last_row = y
        chunk += int.from_bytes(row, "big")
        chunk_rows += 1
        if chunk_rows == 255:
            _add_columns(columns, chunk, width)
            chunk, chunk_rows = 0, 0

    if first_row is None:
        return None
    if chunk_rows:
        _add_columns(columns, chunk, width)

    inked = [x for x, count in enumerate(columns) if count >= floor]
    if not inked:
        return None

    return pymupdf.Rect(
        rect.x0 + inked[0] / zoom,
        rect.y0 + first_row / zoom,
        rect.x0 + (inked[-1] + 1) / zoom,
        rect.y0 + (last_row + 1) / zoom,
    )


def _add_columns(columns: list[int], chunk: int, width: int) -> None:
    """Fold one packed chunk of row counts into the running column totals."""
    packed = chunk.to_bytes(width, "big")
    for x, count in enumerate(packed):
        columns[x] += count


def _shrink(
    rect: pymupdf.Rect, ink: pymupdf.Rect, config: ExtractConfig
) -> pymupdf.Rect:
    """``rect`` pulled in to ``ink`` plus a pad, never growing.

    Three edges only - :func:`_trim` takes the fourth on a grid page, where the
    reasoning below inverts. The blank space *below* a question is the space the
    candidate is meant to write in, so it belongs to the question it was left for
    — the same reasoning :func:`boundaries._snap_boundary` already applies to a
    large undivided gap. Trimming it turns a question with a page of working space
    into a sliver holding nothing but the sentence. The whitespace at the sides
    and above belongs to nobody, and goes.

    Every other edge is clamped against ``rect``, which is what keeps the crop
    inside the share of the page it was given: it can never reach left of
    ``x_cut``, past ``content_right``, or into the question above.
    """
    pad = config.crop_pad
    return pymupdf.Rect(
        max(rect.x0, ink.x0 - pad),
        max(rect.y0, ink.y0 - pad),
        min(rect.x1, ink.x1 + pad),
        rect.y1,
    )
