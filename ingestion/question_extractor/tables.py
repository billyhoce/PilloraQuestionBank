"""Reading the geometry of a ruled answer table: its column pairs and row bands.

A tabulated answer key is a grid of ruled cells: a narrow question column holding
labels like ``5(iii)`` beside a wide answer column, often two such pairs side by
side on one sheet. Where the question pipeline has to *infer* a question's edges
from whitespace, a table prints them. This module reads them off the page's
vector rules; grouping its rows into whole questions is the next stage's job, so
everything here is a diagnostic of an intermediate result, not a crop.

**Rules arrive in pieces.** Both born-digital keys in ``samples/`` draw every
rule cell by cell — a row rule across a two-pair table is four fills with 0.5pt
between them — so collinear pieces are joined first (``table_rule_pos_tol``,
``table_rule_join_gap``) and nothing is measured on a raw piece.

**A table is a connected set of rules.** A horizontal and a vertical rule that
touch belong to the same table, which is what keeps two tables printed side by
side apart and lets an isolated underline or fraction bar fall away on its own.
A table needs at least two columns' worth of edges to be read at all.

**Column edges are the long verticals.** A cell can hold rule-like ink: the FMS
key draws a graph grid inside its 13(iii) answer cell, whose verticals touch the
row rules above and below and so join the table. They are told apart by length —
an edge runs most of its table (``table_edge_min_frac``), a figure one row.

**Which columns hold the question numbers is the layout's to say.** The segmenter
reports, per answer section, the 0-based index of each column that holds question
numbers and the reading order (:class:`TableLayout`). Given it, question column
*k* runs from edge *k* to edge *k+1*, and its answers run on to the next question
column or to the table's right edge, so a marking scheme's ``Marks`` or
``Remarks`` column belongs to the answer (``No. | Working | Remarks`` is ``[0]``).
A hinted column the table does not have is passed over. Without a layout the
edges are paired left to right, question column then answer column, and a table
whose columns do not pair, each question column narrower than its answer column,
is flagged rather than guessed at.

The layout is a hint, so it is checked: a table whose indexed column does not
mostly hold question numbers or part labels is no answer table (Bedok's
``Year | Level`` box) and is set aside. That is flagged only when it leaves the
page with no table, since a table lost that way also leaves a gap in the
question sequence for the next stage to flag. A table lying inside another's
box is a figure drawn in an answer cell (Bedok a1 Q9) and is ignored.

**Scanned pages** arrive here with rules read off their pixels
(:mod:`.scanpage`) and question-cell text read by OCR (:mod:`.ocr`), all in the
straightened page's points. Everything below is shared, with one limit: OCR
reads only the question cells, so on a scan the straddle and uncovered-text
checks see only those.

**A row rule spans the whole pair.** Each pair is its own stack of rows, because
the pairs of one table need not share a row grid: the CCHMS key's left pair has
rows its right pair lacks, and the right pair stops 171pt short of the left. A
row boundary is a horizontal rule covering the pair's full width, *question
column included* (``table_row_min_cover``). That second clause is what rejects
an underline: the widest one in the FMS key covers 93% of its answer column, but
it never crosses into the question column.

**Reading order is measured, then checked against the layout.** The CCHMS key
reads down its left pair and then down its right (1 ... 9(c) | 10(a) ... 12(c));
the FMS key reads across (1(i) | 1(ii), 2 | 3, 4 | 5(ii), ...). Geometry cannot
tell them apart — both are one four-column table — but the question cells can:
an order that sorts the labels' leading question numbers with fewer inversions
wins, and when it disagrees with the layout's order the page is flagged, since
one of the two is misread. A tie — one pair, or labels that sort neither way —
falls to the layout's order, then to down-then-across. Down means pair by pair,
each pair's column of the page (pairs overlapping in x) read top to bottom, so
two tables stacked on a page read in order even when their edges differ by a
point. The sequence is recorded row by row, so a column break is as visible in
the output as a row boundary.

**An unreadable page is flagged, never guessed.** A wrong row band silently
merges two answers, so the checks below turn every doubt into a review reason:
no table, columns that do not pair, a pair with no row rules, text crossing a
row rule, a question cell holding two question numbers (a missed rule), text
inside a table that no pair covers (a missed edge), and a measured reading
order the layout contradicts.

All rectangles are built with explicit ``min``/``max``: a rule drawn as a stroke
has zero thickness, which PyMuPDF calls empty, and ``Rect.__or__`` silently
drops an empty operand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pymupdf

from .config import ExtractConfig
from .furniture import BodyBand
from .geometry import PageGeometry, TextLine
from .tokens import is_part_label, leading_question_number

log = logging.getLogger(__name__)

DOWN = "down"
ACROSS = "across"


@dataclass(frozen=True)
class TableLayout:
    """What the segmenter says about a table section's columns: a hint, checked.

    Mirrors the ingester's ``Segment.question_columns``/``reading_order`` without
    importing the ingester; empty and ``None`` mean "not given", and the reader
    then measures.
    """

    question_columns: tuple[int, ...] = ()
    """0-based indices of the columns holding question numbers, left to right."""
    reading_order: str | None = None
    """``down`` or ``across``."""


@dataclass(frozen=True)
class Rule:
    """One horizontal or vertical rule, its pieces joined."""

    horizontal: bool
    pos: float
    """y of a horizontal rule, x of a vertical one."""
    lo: float
    hi: float
    """Where it starts and ends along its own axis."""

    @property
    def length(self) -> float:
        return self.hi - self.lo

    def overlap(self, lo: float, hi: float) -> float:
        """Length of this rule lying between ``lo`` and ``hi`` on its own axis."""
        return max(0.0, min(self.hi, hi) - max(self.lo, lo))

    def endpoints(self) -> tuple[pymupdf.Point, pymupdf.Point]:
        if self.horizontal:
            return pymupdf.Point(self.lo, self.pos), pymupdf.Point(self.hi, self.pos)
        return pymupdf.Point(self.pos, self.lo), pymupdf.Point(self.pos, self.hi)


@dataclass
class RowBand:
    """One row of a column pair: the band between two row rules."""

    top: float
    bottom: float
    label: str
    """Text of the row's question cell, ``""`` when it has none."""
    number: int | None
    """The question number the label opens with, if it opens with one."""
    order: int = 0
    """1-based position of this row in the page's reading order."""
    confidence: float | None = None
    """On a scanned page, the lowest word confidence (0-100) OCR gave the
    question cell; ``None`` when it read nothing, and on a digital page."""
    answer_ink: bool = True
    """Whether the row's answer area holds any ink: a row with neither a label
    nor an answer is blank, and belongs to no question."""


@dataclass
class ColumnPair:
    """A question column and the answer column to its right, as one row stack."""

    x0: float
    question_x1: float
    """The rule between the question column and the answer column."""
    x1: float
    top: float
    bottom: float
    rows: list[RowBand] = field(default_factory=list)
    index: int = 0
    """1-based, by the page's columns left to right, then top to bottom."""
    table: int = 0
    """0-based index of the table it belongs to, in :attr:`TablePage.tables`."""

    @property
    def rect(self) -> pymupdf.Rect:
        return pymupdf.Rect(self.x0, self.top, self.x1, self.bottom)

    def answer_area(self, row: RowBand, inset: float) -> pymupdf.Rect:
        """The row's answer columns, ``inset`` points inside their rules."""
        return pymupdf.Rect(
            self.question_x1 + inset, row.top + inset, self.x1 - inset, row.bottom - inset
        )


@dataclass
class TablePage:
    """Everything read off one page of a table-format answer section."""

    page: int
    has_text: bool
    body_band: BodyBand
    rules: list[Rule] = field(default_factory=list)
    """Every joined rule inside the body band, table or not — for ``--debug``."""
    tables: list[pymupdf.Rect] = field(default_factory=list)
    """The box of each ruled table found, whether or not its columns paired."""
    inferred_edges: list[Rule] = field(default_factory=list)
    """Outer edges a table left undrawn, inferred from where its rows end."""
    table_problems: list[list[str]] = field(default_factory=list)
    """The problems each table raised, parallel to :attr:`tables`, so a table set
    aside as no answer table can take its own with it."""
    pairs: list[ColumnPair] = field(default_factory=list)
    reading_order: str | None = None
    inversions: dict[str, int] = field(default_factory=dict)
    """Out-of-order question numbers each candidate order would read."""
    sequence: list[tuple[int, int]] = field(default_factory=list)
    """``(pair index, row index)`` for every row, both 1-based, in reading order."""
    straightened_deg: float | None = None
    """Set on a scanned page: the rotation it was straightened by
    (:attr:`ScanPage.angle_deg`), which every rectangle on it is measured after.
    ``None`` on a born-digital page."""
    problems: list[str] = field(default_factory=list)

    @property
    def scanned(self) -> bool:
        return self.straightened_deg is not None

    @property
    def needs_review(self) -> bool:
        return bool(self.problems)

    @property
    def review_reason(self) -> str | None:
        return "; ".join(self.problems) if self.problems else None

    @property
    def runs(self) -> list[tuple[int, int, int]]:
        """``(pair, first row, last row)`` for each unbroken run of the sequence.

        A new run starts wherever reading moves to another pair, so each boundary
        between runs is a column break — the place a question can split into two
        segments, just as it can across a page break.
        """
        runs: list[tuple[int, int, int]] = []
        for pair, row in self.sequence:
            if runs and runs[-1][0] == pair and runs[-1][2] == row - 1:
                runs[-1] = (pair, runs[-1][1], row)
            else:
                runs.append((pair, row, row))
        return runs


def read_table_page(
    geom: PageGeometry,
    band: BodyBand,
    body_lines: list[TextLine],
    config: ExtractConfig,
    layout: TableLayout | None = None,
) -> TablePage:
    """Read one page's ruled tables into column pairs and labelled row bands.

    ``body_lines`` are the page's lines inside the body band, furniture removed
    (:meth:`Furniture.body_lines`); the rules are clipped to the same band, so a
    running header or footer can neither join a table nor be read as a row.
    """
    result = find_tables(geom, band, config, layout)
    label_table_page(result, body_lines, config, layout)
    return result


def find_tables(
    geom: PageGeometry,
    band: BodyBand,
    config: ExtractConfig,
    layout: TableLayout | None = None,
    segments: list[pymupdf.Rect] | None = None,
) -> TablePage:
    """A page's tables, column pairs and row bands, before any text is read.

    The grid alone, so a scanned page's question cells are known before they are
    read: the pipeline OCRs every scanned page's cells in one batch between this
    and :func:`label_table_page`. ``segments`` replaces the page's own
    ``rule_segments``, which is how a scan's pixel rules come in.
    """
    result = TablePage(page=geom.number, has_text=geom.has_text, body_band=band)
    pieces = geom.rule_segments if segments is None else segments
    result.rules = join_rules(pieces, band, config)

    tables = [
        table
        for component in _connected(result.rules, config)
        if (table := _read_table(component, config, layout)) is not None
    ]
    nested = {
        id(inner)
        for inner in tables
        for outer in tables
        if inner is not outer
        and inner.bbox.get_area() < outer.bbox.get_area()
        and _inside(inner.bbox, outer.bbox, config.table_rule_join_gap)
    }
    for table in tables:
        if id(table) in nested:
            log.debug("p%d: ignoring the table inside another at %s", geom.number, table.bbox)
            continue
        for pair in table.pairs:
            pair.table = len(result.tables)
        result.tables.append(table.bbox)
        result.table_problems.append(table.problems)
        result.pairs.extend(table.pairs)
        result.problems.extend(table.problems)
        result.inferred_edges.extend(table.inferred)

    if not result.tables:
        result.problems.append(_no_table_reason(geom, config))
    return result


def label_table_page(
    result: TablePage,
    body_lines: list[TextLine],
    config: ExtractConfig,
    layout: TableLayout | None = None,
    labels_read: bool = True,
) -> None:
    """Label every row from ``body_lines``, check the reading, and order it.

    ``labels_read`` is ``False`` when the page's text could not be read at all
    (OCR unavailable): no table is then set aside for holding no labels, since
    unread is not empty, and the grid is kept for the reviewer.
    """
    if not result.tables:
        return
    for pair in result.pairs:
        _label_rows(pair, body_lines, config, result.problems)
    if labels_read and layout is not None and layout.question_columns:
        _drop_unlabelled_tables(result, config)
        if not result.pairs:
            return
    for pair in result.pairs:
        _check_straddles(pair, body_lines, config, result.problems)
    _check_uncovered(result, body_lines)
    _order(result, config, layout.reading_order if layout is not None else None)


def join_rules(
    segments: list[pymupdf.Rect], band: BodyBand, config: ExtractConfig
) -> list[Rule]:
    """Thin pieces inside the body band, joined into whole rules.

    A horizontal piece counts when its centre lies in the band; a vertical one is
    clipped to it, since a table's edges run as far as the table does and the
    band is where the table may be.
    """
    horizontals: list[tuple[float, float, float]] = []
    verticals: list[tuple[float, float, float]] = []
    for rect in segments:
        if rect.is_infinite:
            continue
        width, height = rect.x1 - rect.x0, rect.y1 - rect.y0
        if height <= config.table_rule_max_thickness and width > height:
            y = (rect.y0 + rect.y1) / 2.0
            if band.top <= y <= band.bottom:
                horizontals.append((y, rect.x0, rect.x1))
        elif width <= config.table_rule_max_thickness and height > width:
            lo, hi = max(rect.y0, band.top), min(rect.y1, band.bottom)
            if hi > lo:
                verticals.append(((rect.x0 + rect.x1) / 2.0, lo, hi))
    return _join(horizontals, True, config) + _join(verticals, False, config)


def _join(
    pieces: list[tuple[float, float, float]], horizontal: bool, config: ExtractConfig
) -> list[Rule]:
    """Group pieces by position, then join the ones that meet along their axis.

    A group spans at most ``table_rule_pos_tol`` from its first piece, and each
    joined rule sits at the mean of its own pieces, not of its group. Chained
    piece to piece, the halftone strokes of a shaded scanned cell, about 3pt
    apart, once bridged Bedok a2 p1's left border and the rule 27pt right of it
    into one group, and averaged both to the x between them.
    """
    rules: list[Rule] = []
    pieces = sorted(pieces)
    start = 0
    while start < len(pieces):
        end = start + 1
        while end < len(pieces) and pieces[end][0] - pieces[start][0] <= config.table_rule_pos_tol:
            end += 1
        run: list[tuple[float, float, float]] = []
        for piece in sorted(pieces[start:end], key=lambda p: (p[1], p[2])):
            if run and piece[1] > max(p[2] for p in run) + config.table_rule_join_gap:
                rules.append(_rule(run, horizontal))
                run = []
            run.append(piece)
        rules.append(_rule(run, horizontal))
        start = end
    return rules


def _rule(run: list[tuple[float, float, float]], horizontal: bool) -> Rule:
    """One rule from pieces that meet along their axis."""
    return Rule(
        horizontal,
        sum(p[0] for p in run) / len(run),
        min(p[1] for p in run),
        max(p[2] for p in run),
    )


def _connected(rules: list[Rule], config: ExtractConfig) -> list[list[Rule]]:
    """Rules grouped into sets that touch, a horizontal meeting a vertical."""
    parent = list(range(len(rules)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    gap = config.table_rule_join_gap
    horizontals = [i for i, r in enumerate(rules) if r.horizontal]
    verticals = [i for i, r in enumerate(rules) if not r.horizontal]
    for h in horizontals:
        hr = rules[h]
        for v in verticals:
            vr = rules[v]
            if hr.lo - gap <= vr.pos <= hr.hi + gap and vr.lo - gap <= hr.pos <= vr.hi + gap:
                parent[find(h)] = find(v)

    groups: dict[int, list[Rule]] = {}
    for i, rule in enumerate(rules):
        groups.setdefault(find(i), []).append(rule)
    return list(groups.values())


@dataclass
class _Table:
    """One connected set of rules read as a table, before it is kept or dropped."""

    bbox: pymupdf.Rect
    pairs: list[ColumnPair]
    problems: list[str]
    inferred: list[Rule] = field(default_factory=list)


def _read_table(
    component: list[Rule], config: ExtractConfig, layout: TableLayout | None
) -> _Table | None:
    """A table's box and its column pairs, or ``None`` if these rules are no table.

    Fewer than three edges — fewer than two columns — is not a table: an isolated
    rule, an underline, a box drawn round a figure. Such ink is ignored here and
    only matters if the page then has no table at all.
    """
    problems: list[str] = []
    verticals = [r for r in component if not r.horizontal]
    if not verticals:
        return None
    tallest = max(r.length for r in verticals)
    edges: list[Rule] = []
    for rule in sorted(verticals, key=lambda r: r.pos):
        if rule.length < config.table_edge_min_frac * tallest:
            continue
        if edges and rule.pos - edges[-1].pos <= config.table_rule_join_gap:
            # Two runs of one edge, interrupted by a merged cell: keep the longer.
            if rule.length > edges[-1].length:
                edges[-1] = rule
            continue
        edges.append(rule)
    horizontals = [r for r in component if r.horizontal]
    inferred = _open_edges(edges, horizontals, config)
    edges = sorted(edges + inferred, key=lambda r: r.pos)
    if len(edges) < 3:
        return None

    # The box is every rule of the table, not just its edges: a pair whose edges
    # were missed still has row rules reaching across it, and text there must
    # read as uncovered (:func:`_check_uncovered`) rather than as outside the table.
    horizontal_x = [x for r in component if r.horizontal for x in (r.lo, r.hi)]
    vertical_x = [r.pos for r in component if not r.horizontal]
    bbox = pymupdf.Rect(
        min(horizontal_x + vertical_x),
        min(r.pos if r.horizontal else r.lo for r in component),
        max(horizontal_x + vertical_x),
        max(r.pos if r.horizontal else r.hi for r in component),
    )
    widths = [b.pos - a.pos for a, b in zip(edges, edges[1:])]
    where = f"the ruled table at x={bbox.x0:.0f}-{bbox.x1:.0f}, y={bbox.y0:.0f}-{bbox.y1:.0f}"
    if layout is not None and layout.question_columns:
        spans = _layout_spans(len(edges), layout.question_columns)
        if not spans:
            problems.append(
                f"{where} has {len(widths)} column(s), too few for a question column at "
                f"index {list(layout.question_columns)} with answers beside it"
            )
            return _Table(bbox, [], problems, inferred)
    elif len(widths) % 2 or any(widths[i] >= widths[i + 1] for i in range(0, len(widths), 2)):
        problems.append(
            f"{where} has {len(widths)} column(s) of widths "
            f"{[round(w) for w in widths]}pt, which do not pair into a narrow question "
            "column beside a wider answer column"
        )
        return _Table(bbox, [], problems, inferred)
    else:
        spans = [(i, i + 1, i + 2) for i in range(0, len(widths), 2)]

    pairs = []
    for i, j, k in spans:
        left, middle, right = edges[i], edges[j], edges[k]
        pair = ColumnPair(
            x0=left.pos,
            question_x1=middle.pos,
            x1=right.pos,
            top=max(left.lo, right.lo),
            bottom=min(left.hi, right.hi),
        )
        bounds = _row_bounds(pair, horizontals, config)
        pair.rows = [RowBand(top, bottom, "", None) for top, bottom in zip(bounds, bounds[1:])]
        if not pair.rows:
            problems.append(
                f"the column pair at x={pair.x0:.0f}-{pair.x1:.0f} has no row rules "
                "spanning it"
            )
        pairs.append(pair)
    return _Table(bbox, pairs, problems, inferred)


def _open_edges(edges: list[Rule], horizontals: list[Rule], config: ExtractConfig) -> list[Rule]:
    """The outer edges a table leaves undrawn, where its row rules say they are.

    The scanned key in ``coverpage_formulae_blankpageinmiddle_endofpaper`` prints
    ``Qn No. | Solution`` with no right border: its row rules simply stop, all
    at one x, 300pt past the last vertical. Without that edge there are only two,
    and no table. An edge is inferred on either side when at least
    ``table_open_edge_min_frac`` of the row rules, and two at the least, run past
    the outermost edge and end together, within ``table_rule_pos_tol``. It sits
    on the furthest of those ends and runs from the first of them to the last.
    """
    if not edges or len(horizontals) < 2:
        return []
    inferred = []
    for right in (True, False):
        outer = edges[-1].pos if right else edges[0].pos
        ends = sorted(
            (r.hi if right else r.lo, r.pos)
            for r in horizontals
            if (r.hi > outer + config.table_rule_join_gap if right else r.lo < outer - config.table_rule_join_gap)
        )
        groups: list[list[tuple[float, float]]] = []
        for end in ends:
            if groups and end[0] - groups[-1][-1][0] <= config.table_rule_pos_tol:
                groups[-1].append(end)
            else:
                groups.append([end])
        best = max(groups, key=len, default=[])
        if len(best) < 2 or len(best) < config.table_open_edge_min_frac * len(horizontals):
            continue
        x = best[-1][0] if right else best[0][0]
        ys = [y for _, y in best]
        inferred.append(Rule(False, x, min(ys), max(ys)))
    return inferred


def _layout_spans(edge_count: int, columns: tuple[int, ...]) -> list[tuple[int, int, int]]:
    """``(left, middle, right)`` edge indices of each pair the layout describes.

    Question column *k* is edges *k* to *k+1*; its answers run to the next
    question column the table has, or to its last edge. A hinted column the table
    lacks, or one with no column beside it before the next, is passed over: the
    layout is the section's, and a page may print fewer column groups.
    """
    last = edge_count - 1
    present = [k for k in columns if k + 2 <= last]
    spans = []
    for n, k in enumerate(present):
        right = present[n + 1] if n + 1 < len(present) else last
        if right >= k + 2:
            spans.append((k, k + 1, right))
    return spans


def _row_bounds(
    pair: ColumnPair, horizontals: list[Rule], config: ExtractConfig
) -> list[float]:
    """The y of each row rule of a pair, top to bottom, double rules merged."""
    width = pair.x1 - pair.x0
    gap = config.table_rule_join_gap
    ys = sorted(
        r.pos
        for r in horizontals
        if pair.top - gap <= r.pos <= pair.bottom + gap
        and r.overlap(pair.x0, pair.x1) >= config.table_row_min_cover * width
    )
    bounds: list[list[float]] = []
    for y in ys:
        if bounds and y - bounds[-1][-1] < config.table_min_row_height:
            bounds[-1].append(y)
        else:
            bounds.append([y])
    return [sum(group) / len(group) for group in bounds]


def _question_cell_text(line: TextLine, pair: ColumnPair) -> str:
    """The spans of a line that start in a pair's question column.

    *Start*, not lie: the CCHMS key sets its header as one span, ``Qns Ans``,
    running across the column rule. A label is read for its leading number, so
    answer text carried along at the end of it is harmless.
    """
    return " ".join(
        span.text.strip()
        for span in line.spans
        if span.rect.x0 < pair.question_x1 and span.text.strip()
    )


def _label_rows(
    pair: ColumnPair, lines: list[TextLine], config: ExtractConfig, problems: list[str]
) -> None:
    """Fill in each row's question-cell label, flagging a cell with two numbers.

    A line belongs to the question cell when it *starts* there: an extracted line
    can run on into the answer cell beside it, and its centre would then sit in
    the wrong column.
    """
    for row in pair.rows:
        cell = sorted(
            (
                line
                for line in lines
                if pair.x0 <= line.leading_x < pair.question_x1
                and row.top <= (line.y0 + line.y1) / 2.0 <= row.bottom
            ),
            key=lambda line: (line.y0, line.x0),
        )
        texts = [text for text in (_question_cell_text(line, pair) for line in cell) if text]
        row.label = " ".join(texts)
        row.number = leading_question_number(row.label)

        numbered: list[TextLine] = []
        for line in cell:
            if leading_question_number(_question_cell_text(line, pair)) is None:
                continue
            if not any(line.shares_row_with(other, config.row_tol) for other in numbered):
                numbered.append(line)
        if len(numbered) > 1:
            problems.append(
                f"the row at y={row.top:.0f}-{row.bottom:.0f} holds "
                f"{len(numbered)} question labels "
                f"({', '.join(repr(_question_cell_text(ln, pair)) for ln in numbered)}): "
                "a row rule may be missing"
            )


def _drop_unlabelled_tables(result: TablePage, config: ExtractConfig) -> None:
    """Set aside each table whose question column does not hold question labels.

    The layout names a column by position, and any ruled box has a first column,
    so a table qualifies only when most of its non-empty question cells open with
    a question number or a part label (``table_label_min_frac``).
    """
    keep: set[int] = set()
    for index, table in enumerate(result.tables):
        labels = [row.label for pair in result.pairs if pair.table == index for row in pair.rows]
        filled = [label for label in labels if label]
        numbered = [label for label in filled if _is_question_label(label)]
        if filled and len(numbered) >= config.table_label_min_frac * len(filled):
            keep.add(index)
            continue
        log.info(
            "p%d: set aside the table at x=%.0f-%.0f, y=%.0f-%.0f: %d of its %d "
            "question cell(s) hold a question label",
            result.page, table.x0, table.x1, table.y0, table.y1, len(numbered), len(filled),
        )
    if len(keep) == len(result.tables):
        return
    if not keep:
        # Each table's own problems stay: they may be why none could be read.
        result.problems.append(
            "no table's question column holds question labels"
            if any(row.label for pair in result.pairs for row in pair.rows)
            else "no question labels were read in any table's question column"
        )
    else:
        for index, problems in enumerate(result.table_problems):
            if index not in keep:
                for problem in problems:
                    result.problems.remove(problem)
    result.pairs = [pair for pair in result.pairs if pair.table in keep]


def _is_question_label(label: str) -> bool:
    token = label.split()[0]
    return leading_question_number(label) is not None or is_part_label(token)


def _check_straddles(
    pair: ColumnPair, lines: list[TextLine], config: ExtractConfig, problems: list[str]
) -> None:
    """Flag text crossing one of the pair's row rules."""
    bounds = sorted({row.top for row in pair.rows} | {row.bottom for row in pair.rows})
    for line in lines:
        centre_x = (line.x0 + line.x1) / 2.0
        if not pair.x0 <= centre_x <= pair.x1:
            continue
        reach = config.table_straddle_frac * line.height
        crossed = [y for y in bounds if line.y0 + reach <= y <= line.y1 - reach]
        if crossed:
            problems.append(
                f"text {line.text[:30]!r} crosses the row rule at y={crossed[0]:.0f} "
                f"in the column pair at x={pair.x0:.0f}-{pair.x1:.0f}"
            )


def _check_uncovered(result: TablePage, lines: list[TextLine]) -> None:
    """Flag text inside a table that no column pair covers: a missed edge."""
    paired = [table for table in result.tables if any(_inside(p.rect, table) for p in result.pairs)]
    for line in lines:
        cx, cy = (line.x0 + line.x1) / 2.0, (line.y0 + line.y1) / 2.0
        if not any(_contains(table, cx, cy) for table in paired):
            continue
        if any(_contains(pair.rect, cx, cy) for pair in result.pairs):
            continue
        result.problems.append(
            f"text {line.text[:30]!r} at y={line.y0:.0f} lies inside a ruled table "
            "but outside every column pair"
        )


def _order(result: TablePage, config: ExtractConfig, hint: str | None = None) -> None:
    """Choose the reading order and number every pair and row by it."""
    if not result.pairs:
        return
    result.pairs = _page_columns(result.pairs)
    for index, pair in enumerate(result.pairs, start=1):
        pair.index = index

    down = [(pair, row) for pair in result.pairs for row in pair.rows]
    across = _across(result.pairs, config)
    result.inversions = {DOWN: _inversions(down), ACROSS: _inversions(across)}
    if len(result.pairs) > 1 and result.inversions[ACROSS] != result.inversions[DOWN]:
        measured = ACROSS if result.inversions[ACROSS] < result.inversions[DOWN] else DOWN
        if hint is not None and hint != measured:
            result.problems.append(
                f"the question numbers read {measured} (out-of-order pairs: "
                f"{result.inversions}), but the section's layout says {hint}"
            )
        result.reading_order = measured
    else:
        result.reading_order = hint if hint in (DOWN, ACROSS) else DOWN

    chosen = across if result.reading_order == ACROSS else down
    position = {id(row): i for pair in result.pairs for i, row in enumerate(pair.rows, start=1)}
    result.sequence = []
    for order, (pair, row) in enumerate(chosen, start=1):
        row.order = order
        result.sequence.append((pair.index, position[id(row)]))


def _page_columns(pairs: list[ColumnPair]) -> list[ColumnPair]:
    """Pairs in down-then-across order: the page's columns left to right, each top
    to bottom.

    A pair joins a column when it overlaps it in x by more than half the narrower
    width. Sorting on ``x0`` alone puts two stacked tables out of order whenever
    the lower one's left edge sits a point further left, as on Bedok a1 p2.
    """
    columns: list[list[ColumnPair]] = []
    for pair in sorted(pairs, key=lambda p: (p.x0, p.top)):
        for column in columns:
            x0, x1 = min(p.x0 for p in column), max(p.x1 for p in column)
            overlap = min(x1, pair.x1) - max(x0, pair.x0)
            if overlap > 0.5 * min(x1 - x0, pair.x1 - pair.x0):
                column.append(pair)
                break
        else:
            columns.append([pair])
    return [pair for column in columns for pair in sorted(column, key=lambda p: p.top)]


def _across(
    pairs: list[ColumnPair], config: ExtractConfig
) -> list[tuple[ColumnPair, RowBand]]:
    """Rows read line by line across the pairs, left to right within a line.

    Rows of different pairs belong to one line when their tops agree within the
    join gap — the tolerance already used for rules meeting.
    """
    entries = sorted(
        ((pair, row) for pair in pairs for row in pair.rows), key=lambda e: e[1].top
    )
    lines: list[list[tuple[ColumnPair, RowBand]]] = []
    for entry in entries:
        if lines and entry[1].top - lines[-1][0][1].top <= config.table_rule_join_gap:
            lines[-1].append(entry)
        else:
            lines.append([entry])
    return [entry for line in lines for entry in sorted(line, key=lambda e: e[0].x0)]


def _inversions(entries: list[tuple[ColumnPair, RowBand]]) -> int:
    """How many pairs of numbered rows this order reads out of sequence."""
    numbers = [row.number for _, row in entries if row.number is not None]
    return sum(
        1
        for i, a in enumerate(numbers)
        for b in numbers[i + 1 :]
        if a > b
    )


def _no_table_reason(geom: PageGeometry, config: ExtractConfig) -> str:
    """Why a page yielded no table, in the terms a reviewer can act on."""
    if geom.has_page_sized_image(config.figure_max_area_frac):
        return "no ruled table found among the lines read off the scanned page"
    if not geom.has_text:
        return "no ruled table found, and no extractable text on the page"
    return "no ruled table with question and answer columns found (borderless or irregular)"


def _contains(rect: pymupdf.Rect, x: float, y: float) -> bool:
    return rect.x0 <= x <= rect.x1 and rect.y0 <= y <= rect.y1


def _inside(inner: pymupdf.Rect, outer: pymupdf.Rect, tol: float = 0.0) -> bool:
    return (
        outer.x0 - tol <= inner.x0 <= inner.x1 <= outer.x1 + tol
        and outer.y0 - tol <= inner.y0 <= inner.y1 <= outer.y1 + tol
    )
