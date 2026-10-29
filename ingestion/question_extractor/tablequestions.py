"""Grouping a table's rows into questions, with one rectangle per run of rows.

:mod:`.tables` reads a table into rows; the manifest records questions. A
question's answer is every row from the one its number opens to the row before
the next number, and those rows can sit in more than one place: down a column
pair and on at the top of the next (the synthetic key's Q4), across two pairs
row by row (the FMS key's Q5), or over a page break (Clementi's Q5).

**One rectangle per run of rows, not one per question.** A run is the rows of
one question that sit one under the other in one column pair, on one page. Its rectangle runs from the grid corner above and left of its first
question cell to the bottom right of its last row, answer columns included (a
marking scheme's ``Marks`` and ``Remarks`` with them). Each run is one
:class:`.boundaries.Band`, numbered by ``segment`` as a question paper's page
breaks are. Nothing is trimmed: the rules are the question's edges.

**Rows are walked in reading order** across the whole section, page by page and
each page in its own order (:attr:`.tables.TablePage.sequence`). Each row is read
by its question cell with :mod:`.tokens`; there is no second classifier.

* A question number other than the open question's starts a new question.
* The same number (``1(a)`` then ``1(b)``), or a part label alone, continues it.
* An empty question cell continues it when the row's answer area holds ink. A
  blank row belongs to no question: Nan Hua WA1 leaves a pair-2 cell empty
  beside every question with one part.
* Any other text is a header (``Qn``, ``No.``, ``Qns Ans``) when it opens a
  pair or no question is open, and is skipped. Anywhere else it continues the
  open question, with a warning, since skipping the row could lose an answer.

**A garbled number is repaired only where the sequence vouches for it.** OCR
reads Yuying's ``1(a)`` as ``l(a)``. A label opening with no number, and not a
part label, goes through :func:`.tokens.repaired_label_number`. The repair is
accepted only when it is the open question's number or the next, and no more
than the next number read, and it is always warned.

**The sequence is checked, never corrected.** Numbers should rise by one
(``table_max_number_step``). A number lower than one already read, a number
read twice, or a larger step (a lost question) is warned, and the page it
happens on is flagged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pymupdf

from .boundaries import Band, PageResult, Question
from .config import ExtractConfig
from .tables import ColumnPair, RowBand, TablePage
from .tokens import is_part_label, leading_question_number, repaired_label_number

log = logging.getLogger(__name__)


@dataclass
class _Walk:
    """State carried from row to row through a section."""

    config: ExtractConfig
    questions: list[Question] = field(default_factory=list)
    open: Question | None = None
    started: set[int] = field(default_factory=set)


def build_table_questions(
    results: list[TablePage], config: ExtractConfig
) -> tuple[list[Question], list[PageResult]]:
    """Every question of a table section, and one page result per page.

    Problems found on a page — sequence trouble included — are added to that
    page's :attr:`TablePage.problems`, so ``tables.json`` and the manifest agree.
    """
    walk = _Walk(config)
    entries = [(result, pair, row) for result in results for pair, row in _in_order(result)]
    numbers = [_number(row) for _, _, row in entries]

    for position, (result, pair, row) in enumerate(entries):
        number = numbers[position]
        if number is None and row.label:
            upcoming = next((n for n in numbers[position + 1 :] if n is not None), None)
            number = _repair(walk, result, row, upcoming)
            numbers[position] = number
        _place(walk, result, pair, row, number)

    pages = [_page_result(result) for result in results]
    by_page = {page.page: page for page in pages}
    for question in walk.questions:
        for band in question.bands:
            by_page[band.page].bands.append(band)
    return walk.questions, pages


def _in_order(result: TablePage) -> list[tuple[ColumnPair, RowBand]]:
    pairs = {pair.index: pair for pair in result.pairs}
    return [(pairs[p], pairs[p].rows[r - 1]) for p, r in result.sequence]


def _number(row: RowBand) -> int | None:
    return leading_question_number(row.label) if row.label else None


def _repair(walk: _Walk, result: TablePage, row: RowBand, upcoming: int | None) -> int | None:
    """The number a garbled label stands for, when the sequence vouches for it."""
    if is_part_label(row.label.split()[0]):
        return None  # ``ii.`` is a part, not an ``11``
    repaired = repaired_label_number(row.label)
    if repaired is None or repaired < 1:
        return None
    current = walk.open.number if walk.open is not None else None
    fits = (current is None or repaired in (current, current + 1)) and (
        upcoming is None or repaired <= upcoming
    )
    if not fits:
        return None
    log.warning(
        "p%d: read the question label %r as question %d (an OCR repair the "
        "sequence agrees with); check it",
        result.page, row.label, repaired,
    )
    row.number = repaired
    return repaired


def _place(
    walk: _Walk, result: TablePage, pair: ColumnPair, row: RowBand, number: int | None
) -> None:
    """Start, continue or skip, for one row."""
    if number is not None:
        if walk.open is None or number != walk.open.number:
            _check_sequence(walk, result, number)
            walk.open = Question(number=number)
            walk.questions.append(walk.open)
            walk.started.add(number)
        _extend(walk, result, pair, row)
        return

    if walk.open is None:
        return  # a header, or a row before the first question: nothing to join
    if not row.label:
        if row.answer_ink:
            _extend(walk, result, pair, row)
        return
    if is_part_label(row.label.split()[0]):
        _extend(walk, result, pair, row)
        return
    if pair.rows[0] is row:
        return  # a pair's header row
    log.warning(
        "p%d: the question label %r is neither a number nor a part label; read "
        "as continuing question %d",
        result.page, row.label, walk.open.number,
    )
    _extend(walk, result, pair, row)


def _extend(walk: _Walk, result: TablePage, pair: ColumnPair, row: RowBand) -> None:
    """Add a row to the open question: onto its run ending just above the row in
    the same pair, or as a new run.

    Any run, not only the last: read across, a question's rows alternate between
    the pairs (Nan Hua WA1's ``4a | 4b(i)`` then ``  | 4b(ii)``), and each pair's
    rows still make one rectangle.
    """
    question = walk.open
    assert question is not None
    for band in question.bands:
        if (
            band.page == result.page
            and band.rect.x0 == pair.x0
            and band.rect.x1 == pair.x1
            and band.rect.y1 == row.top
        ):
            band.rect = pymupdf.Rect(band.rect.x0, band.rect.y0, band.rect.x1, row.bottom)
            band.partition = pymupdf.Rect(band.rect)
            return
    rect = pymupdf.Rect(pair.x0, row.top, pair.x1, row.bottom)
    band = Band(
        page=result.page,
        number=question.number,
        rect=rect,
        partition=pymupdf.Rect(rect),
        segment=len(question.bands) + 1,
        is_continuation=bool(question.bands),
    )
    question.bands.append(band)


def _check_sequence(walk: _Walk, result: TablePage, number: int) -> None:
    previous = walk.questions[-1].number if walk.questions else None
    if number in walk.started:
        problem = f"question {number} is read a second time"
    elif previous is None:
        return
    elif number < previous:
        problem = f"question {number} is read after question {previous}"
    elif number - previous > walk.config.table_max_number_step:
        missing = ", ".join(str(n) for n in range(previous + 1, number))
        problem = f"question {number} follows question {previous}: no row reads {missing}"
    else:
        return
    result.problems.append(problem)
    log.warning("p%d: %s", result.page, problem)


def _page_result(result: TablePage) -> PageResult:
    return PageResult(
        page=result.page,
        has_text=result.has_text,
        needs_review=result.needs_review,
        review_reason=result.review_reason,
        body_band=result.body_band,
    )
