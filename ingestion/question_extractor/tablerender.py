"""The ``--debug`` view of a table page: its column pairs and row bands drawn on.

The question rectangles are drawn by :mod:`.render`, as for a question paper.
This is the row-level reading behind them, which is what shows why a page was
flagged or a question grouped the way it was:

======================  ==========================================
Blue box                a column pair, labelled ``pair N``
Blue dashed vertical    the rule between its question and answer column
Shaded bands            its rows, alternating, ``#k`` (right) its reading order
Red line, ``break``     where reading leaves one pair for the next
Magenta lines           every joined rule
Grey dashed box         each table found
Magenta dashed vertical an outer edge inferred, labelled ``inferred``
======================  ==========================================

Breaks are drawn only when reading runs down the pairs. Read across, every row
ends a run and the ``#k`` numbers zig-zagging between the pairs already say so.
A scanned page is drawn on its straightened image, the frame its rules are in.
"""

from __future__ import annotations

import pymupdf

from .debug import shade_furniture
from .raster import Draw
from .tables import DOWN, ColumnPair, TablePage

BLUE = (0.1, 0.35, 0.9)
RED = (0.85, 0.05, 0.05)
MAGENTA = (0.8, 0.0, 0.8)
GREY = (0.45, 0.45, 0.45)
ROW_FILLS = ((0.2, 0.7, 0.3), (0.95, 0.6, 0.1))


def table_debug_draws(results: list[TablePage]) -> dict[int, Draw]:
    """Each page's ``--debug`` marks: its table geometry, drawn by :func:`.render.render_outputs`.

    A straightened scan's geometry is in its straightened frame, so the caller
    draws it on the straightened image rather than the page as filed.
    """
    draws: dict[int, Draw] = {}
    for result in results:

        def draw(page: pymupdf.Page, result=result) -> None:
            _draw_debug(page, result)
            _draw_geometry(page, result)
            _draw_legend(page, result)

        draws[result.page] = draw
    return draws


def _draw_geometry(page: pymupdf.Page, result: TablePage) -> None:
    for pair in result.pairs:
        _draw_pair(page, pair)
    _draw_breaks(page, result)


def _draw_pair(page: pymupdf.Page, pair: ColumnPair) -> None:
    for i, row in enumerate(pair.rows):
        page.draw_rect(
            pymupdf.Rect(pair.x0, row.top, pair.x1, row.bottom),
            color=None,
            fill=ROW_FILLS[i % 2],
            fill_opacity=0.12,
            width=0,
        )
        page.insert_text(
            pymupdf.Point(pair.x1 - 16.0, row.bottom - 2.0),
            f"#{row.order}",
            fontsize=6,
            fontname="hebo",
            color=GREY,
        )
    page.draw_rect(pair.rect, color=BLUE, width=1.0)
    page.draw_line(
        pymupdf.Point(pair.question_x1, pair.top),
        pymupdf.Point(pair.question_x1, pair.bottom),
        color=BLUE,
        width=0.6,
        dashes="[3 3] 0",
    )
    page.insert_text(
        pymupdf.Point(pair.x0 + 2.0, max(pair.top - 2.5, 8.0)),
        f"pair {pair.index}",
        fontsize=7,
        fontname="hebo",
        color=BLUE,
    )


def _draw_breaks(page: pymupdf.Page, result: TablePage) -> None:
    """Mark the bottom of each run that reading leaves for another pair.

    Down-then-across, that is one mark per pair, at the foot of its last row.
    """
    if result.reading_order != DOWN:
        return
    pairs = {pair.index: pair for pair in result.pairs}
    runs = result.runs
    for pair_index, _, last in runs[:-1]:
        pair = pairs[pair_index]
        y = pair.rows[last - 1].bottom
        page.draw_line(
            pymupdf.Point(pair.x0, y), pymupdf.Point(pair.x1, y), color=RED, width=1.4
        )
        page.insert_text(
            pymupdf.Point(pair.x1 - 22.0, y + 7.0),
            "break",
            fontsize=6,
            fontname="hebo",
            color=RED,
        )


def _draw_debug(page: pymupdf.Page, result: TablePage) -> None:
    """Furniture, every joined rule, each table's box, and inferred edges."""
    shade_furniture(page, page.rect, result.body_band)
    for rule in result.rules:
        start, end = rule.endpoints()
        page.draw_line(start, end, color=MAGENTA, width=0.5)
    for table in result.tables:
        page.draw_rect(table, color=GREY, width=0.6, dashes="[4 3] 0")
    for edge in result.inferred_edges:
        start, end = edge.endpoints()
        page.draw_line(start, end, color=MAGENTA, width=1.2, dashes="[2 2] 0")
        page.insert_text(
            pymupdf.Point(edge.pos + 2.0, edge.lo + 8.0),
            "inferred",
            fontsize=6,
            fontname="helv",
            color=MAGENTA,
        )


def _draw_legend(page: pymupdf.Page, result: TablePage) -> None:
    rect = page.rect
    if result.needs_review:
        text = f"p{result.page}  needs review - {result.review_reason}"
    else:
        text = (
            f"p{result.page}  pairs={len(result.pairs)}  "
            f"rows={[len(pair.rows) for pair in result.pairs]}  "
            f"order={result.reading_order}  inversions={result.inversions}"
        )
    if result.straightened_deg is not None:
        text = f"{text}  straightened={result.straightened_deg:+.2f}deg"
    page.insert_text(
        pymupdf.Point(rect.x0 + 6.0, rect.y1 - 5.0),
        text[:180],
        fontsize=6,
        fontname="helv",
        color=BLUE,
    )
