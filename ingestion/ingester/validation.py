"""Checking a model's answer against the document. See ingester/README.md."""

from __future__ import annotations

from collections.abc import Sequence

from .config import IngestConfig
from .segments import (
    KIND_PREFIXES,
    READING_ORDERS,
    TEMPLATES,
    Segment,
    format_label,
    parse_label,
)


def validate(
    segments: Sequence[Segment], page_count: int, config: IngestConfig
) -> list[str]:
    """Every reason this plan cannot describe the document; empty if none."""
    problems: list[str] = []
    problems.extend(_check_each(segments, page_count, config))
    problems.extend(_check_order(segments))
    problems.extend(_check_overlap(segments))
    problems.extend(_check_indices(segments))
    return problems


def _check_each(
    segments: Sequence[Segment], page_count: int, config: IngestConfig
) -> list[str]:
    problems: list[str] = []
    for position, segment in enumerate(segments, 1):
        where = f"segment {position} ({segment.label!r})"

        parsed = parse_label(segment.label)
        if parsed is None:
            problems.append(
                f"{where}: label is not a kind letter followed by an index "
                f"(expected e.g. 'q1' or 'a2')"
            )
        if segment.kind not in KIND_PREFIXES:
            problems.append(
                f"{where}: kind {segment.kind!r} is not one of "
                f"{sorted(KIND_PREFIXES)}"
            )
        if not isinstance(segment.index, int) or segment.index < 1:
            problems.append(f"{where}: index {segment.index!r} is not a positive whole number")
        elif segment.index > config.max_segment_index:
            problems.append(
                f"{where}: index {segment.index} is above the largest plausible "
                f"index ({config.max_segment_index})"
            )

        if parsed is not None and segment.kind in KIND_PREFIXES:
            expected = format_label(segment.kind, segment.index)
            if expected != segment.label:
                problems.append(
                    f"{where}: label disagrees with kind {segment.kind!r} and "
                    f"index {segment.index} (which spell {expected!r})"
                )

        problems.extend(_check_template(segment, where))
        problems.extend(_check_layout(segment, where, config))
        problems.extend(_check_pages(segment, where, page_count))
    return problems


def _check_template(segment: Segment, where: str) -> list[str]:
    if segment.template is not None and segment.template not in TEMPLATES:
        return [f"{where}: template {segment.template!r} is not one of {list(TEMPLATES)}"]
    if segment.kind == "question" and (segment.template or segment.needs_review):
        return [f"{where}: a question section carries a template"]
    if segment.kind == "answer" and segment.template is None and not segment.needs_review:
        return [f"{where}: an answer section is missing its template"]
    return []


def _check_layout(segment: Segment, where: str, config: IngestConfig) -> list[str]:
    """A table's column layout must be usable; nothing else may carry one.

    An answer section the model was unsure of may carry a layout: it is not
    routed, so the layout is never read, and rejecting it would escalate a plan
    for nothing.
    """
    columns, order = segment.question_columns, segment.reading_order
    if segment.kind == "question" or segment.template == "annotated_booklet":
        if columns or order is not None:
            return [f"{where}: a section that is not a table carries a column layout"]
        return []

    problems: list[str] = []
    if order is not None and order not in READING_ORDERS:
        problems.append(
            f"{where}: reading_order {order!r} is not one of {list(READING_ORDERS)}"
        )
    if any(not isinstance(c, int) or isinstance(c, bool) or c < 0 for c in columns):
        problems.append(
            f"{where}: question_columns {list(columns)} are not all 0-based column indices"
        )
    elif list(columns) != sorted(set(columns)):
        problems.append(f"{where}: question_columns {list(columns)} do not strictly ascend")
    if len(columns) > config.max_question_columns:
        problems.append(
            f"{where}: {len(columns)} question columns is more than the "
            f"{config.max_question_columns} a page can hold"
        )
    return problems


def _check_pages(segment: Segment, where: str, page_count: int) -> list[str]:
    problems: list[str] = []
    for name, value in (("first_page", segment.first_page), ("last_page", segment.last_page)):
        if not isinstance(value, int) or isinstance(value, bool):
            problems.append(f"{where}: {name} {value!r} is not a whole number")
            return problems
    if segment.first_page > segment.last_page:
        problems.append(
            f"{where}: pages {segment.first_page}-{segment.last_page} run backwards"
        )
    if segment.first_page < 1 or segment.last_page > page_count:
        problems.append(
            f"{where}: pages {segment.first_page}-{segment.last_page} fall outside "
            f"the document (1-{page_count})"
        )
    return problems


def _check_order(segments: Sequence[Segment]) -> list[str]:
    problems: list[str] = []
    for previous, segment in zip(segments, segments[1:]):
        if segment.first_page < previous.first_page:
            problems.append(
                f"segments are out of page order: {segment.label!r} starts on page "
                f"{segment.first_page}, after {previous.label!r} on page "
                f"{previous.first_page}"
            )
    return problems


def _check_overlap(segments: Sequence[Segment]) -> list[str]:
    problems: list[str] = []
    ordered = sorted(segments, key=lambda segment: (segment.first_page, segment.last_page))
    for previous, segment in zip(ordered, ordered[1:]):
        if segment.first_page <= previous.last_page:
            problems.append(
                f"{previous.label!r} (pages {previous.first_page}-{previous.last_page}) "
                f"and {segment.label!r} (pages {segment.first_page}-{segment.last_page}) "
                f"overlap"
            )
    return problems


def _check_indices(segments: Sequence[Segment]) -> list[str]:
    problems: list[str] = []
    for kind in sorted(KIND_PREFIXES):
        indices = [segment.index for segment in segments if segment.kind == kind]
        if not indices:
            continue
        if sorted(indices) != list(range(1, len(indices) + 1)):
            problems.append(
                f"{kind} indices {indices} are not 1..{len(indices)}; each kind must "
                f"be numbered from 1 with no gaps or repeats"
            )
        elif indices != sorted(indices):
            problems.append(
                f"{kind} indices {indices} do not ascend down the document; the "
                f"first {kind} section must be index 1"
            )
    return problems


def anomalies(
    segments: Sequence[Segment], page_count: int, config: IngestConfig
) -> list[str]:
    """Unusual readings of a valid plan, worth a human's eye."""
    notes: list[str] = []

    if not segments:
        notes.append(
            "no sections found: the document was read but nothing in it was "
            "recognised as a question or answer paper"
        )
        return notes

    question_indices = {
        segment.index for segment in segments if segment.kind == "question"
    }
    for segment in segments:
        if segment.kind == "answer" and segment.index not in question_indices:
            notes.append(
                f"{segment.label!r} (pages {segment.first_page}-{segment.last_page}) "
                f"has no matching question paper "
                f"{format_label('question', segment.index)!r}"
            )
        if segment.kind == "answer" and segment.template is None:
            notes.append(
                f"{segment.label!r} (pages {segment.first_page}-{segment.last_page}) "
                f"could not be classified as {' or '.join(TEMPLATES)}; flagged "
                f"for review"
            )
        if segment.template == "table" and (
            not segment.question_columns or segment.reading_order is None
        ):
            notes.append(
                f"{segment.label!r} (pages {segment.first_page}-{segment.last_page}) "
                f"gives no full column layout; the table reader measures what is "
                f"missing"
            )

    notes.extend(_uncovered(segments, page_count))
    return notes


def _uncovered(segments: Sequence[Segment], page_count: int) -> list[str]:
    """Pages between sections that none claims (leading/trailing are expected)."""
    covered = set()
    for segment in segments:
        covered.update(segment.pages)

    first = min(segment.first_page for segment in segments)
    last = max(segment.last_page for segment in segments)
    interior = [page for page in range(first, last + 1) if page not in covered]
    if not interior:
        return []

    runs = _runs(interior)
    described = ", ".join(
        f"{start}" if start == end else f"{start}-{end}" for start, end in runs[:3]
    )
    more = "" if len(runs) <= 3 else f" and {len(runs) - 3} more"
    return [
        f"{len(interior)} page(s) between sections belong to none of them "
        f"({described}{more}); front matter for the section that follows reads "
        f"this way, and so does a section left out altogether"
    ]


def _runs(pages: Sequence[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for page in pages:
        if runs and page == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], page)
        else:
            runs.append((page, page))
    return runs
