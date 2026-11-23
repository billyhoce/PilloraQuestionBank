"""Regenerate the synthetic table-format answer key in this folder.

    .venv/Scripts/python samples/answer_tables/generate.py

Writes ``two_pairs_column_break.pdf``, four pages built to exercise what the two
real table keys in ``samples/s4_a_math/`` do not:

1. Two column pairs with independent row grids, read down then across, where
   question 4's rows run off the foot of pair 1 (``4(a)``, ``4(b)``) and resume
   at the top of pair 2 (``4(c)``) — one question across a column break. The
   whole grid is **one stroked path of lines**, so a single drawing box covers
   the table, and an answer cell carries an underline.
2. Two pairs sharing one row grid, read across (``8(a) | 8(b)``, ``9 | 10(i)``,
   ...), with every cell drawn as a **stroked rectangle**.
3. A single pair whose rules are **thin fills drawn cell by cell** with 0.5pt
   gaps, the way the real keys draw them.
4. A borderless answer list: no rules at all, so the page must be flagged.

Every page repeats a running header and footer, which furniture detection has to
keep out of the table. The PDF is committed; rerun this only to change it.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

OUT = Path(__file__).with_name("two_pairs_column_break.pdf")
W, H = 595.0, 842.0
HEADER = "Synthetic Sec 4 Additional Mathematics - Answer Key"


def furniture(page: pymupdf.Page, number: int) -> None:
    page.insert_text((72, 40), HEADER, fontsize=9, fontname="helv")
    page.draw_line((72, 800), (523, 800), width=0.5)
    page.insert_text((72, 815), f"Answer Key   Page {number}", fontsize=9, fontname="helv")


def cell_text(page: pymupdf.Page, x: float, y: float, text: str, bold: bool = False) -> None:
    page.insert_text((x + 4, y + 14), text, fontsize=11, fontname="hebo" if bold else "helv")


def page_one(doc: pymupdf.Document) -> None:
    """Independent row grids, read down; question 4 crosses the column break."""
    page = doc.new_page(width=W, height=H)
    furniture(page, 1)
    page.insert_text((72, 80), "Answer Key", fontsize=13, fontname="hebo")
    left = [("1", "x = 3"), ("2(a)", "y = 2x - 1"), ("2(b)", "(4, 7)"),
            ("3", "12 cm"), ("4(a)", "k > 2"), ("4(b)", "k = 5")]
    right = [("4(c)", "2 solutions"), ("5", "0.631"), ("6(a)", "A = 1, B = -5"),
             ("6(b)", "minimum point (3, 0)")]
    shape = page.new_shape()
    for x0, xq, x1, rows, height in ((72, 112, 290, left, 60), (305, 345, 523, right, 45)):
        top = 100
        ys = [top + i * height for i in range(len(rows) + 1)]
        for y in ys:
            shape.draw_line((x0, y), (x1, y))
        for x in (x0, xq, x1):
            shape.draw_line((x, ys[0]), (x, ys[-1]))
        for (label, answer), y in zip(rows, ys):
            cell_text(page, x0, y, label, bold=True)
            cell_text(page, xq, y, answer)
    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()
    # An underline inside an answer cell: rule-like, but not a row.
    page.draw_line((116, 197), (240, 197), width=0.5)


def page_two(doc: pymupdf.Document) -> None:
    """One row grid shared by two pairs, read across; cells are stroked rects."""
    page = doc.new_page(width=W, height=H)
    furniture(page, 2)
    rows = [(("7", "x = 1 or x = -4"), ("8(a)", "p = 3")),
            (("8(b)", "q = -2"), ("9", "45 degrees")),
            (("10(i)", "gradient = 2"), ("10(ii)", "y = 2x + 3")),
            (("11", "1601 years"), ("12", "C(5, 4), r = 5"))]
    edges = (72, 112, 290, 330, 523)
    top, height = 90, 55
    for i, pairs in enumerate(rows):
        y0, y1 = top + i * height, top + (i + 1) * height
        for a, b in zip(edges, edges[1:]):
            page.draw_rect(pymupdf.Rect(a, y0, b, y1), color=(0, 0, 0), width=0.5)
        for (label, answer), x0 in zip(pairs, (72, 290)):
            cell_text(page, x0, y0, label, bold=True)
            cell_text(page, x0 + 40, y0, answer)


def page_three(doc: pymupdf.Document) -> None:
    """A single pair; rules drawn as thin fills, cell by cell, 0.5pt apart."""
    page = doc.new_page(width=W, height=H)
    furniture(page, 3)
    rows = [("13", "2p^2 - 1"), ("14(a)", "Show question"), ("14(b)", "a = 4, b = -2"),
            ("15", "3 metres")]
    x0, xq, x1, top, height, t = 72, 120, 400, 90, 70, 0.48
    ys = [top + i * height for i in range(len(rows) + 1)]
    black = (0, 0, 0)
    for y in ys:
        for a, b in ((x0, xq), (xq + 0.5, x1)):
            page.draw_rect(pymupdf.Rect(a, y, b, y + t), color=None, fill=black, width=0)
    for y0, y1 in zip(ys, ys[1:]):
        for x in (x0, xq, x1):
            page.draw_rect(pymupdf.Rect(x, y0 + 0.5, x + t, y1), color=None, fill=black, width=0)
    for (label, answer), y in zip(rows, ys):
        cell_text(page, x0, y, label, bold=True)
        cell_text(page, xq, y, answer)


def page_four(doc: pymupdf.Document) -> None:
    """A borderless answer list: no table to read."""
    page = doc.new_page(width=W, height=H)
    furniture(page, 4)
    for i, (label, answer) in enumerate((("16", "x = 2"), ("17(a)", "27"), ("17(b)", "4.5 m"))):
        cell_text(page, 72, 90 + i * 30, label, bold=True)
        cell_text(page, 130, 90 + i * 30, answer)


def main() -> None:
    doc = pymupdf.open()
    for build in (page_one, page_two, page_three, page_four):
        build(doc)
    doc.save(OUT, garbage=4, deflate=True)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
