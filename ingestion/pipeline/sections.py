"""Reading a section back from the job's artefacts.

A section stage gets only a label, so it rebuilds the ``ingester`` section from
what ``segment`` and ``split`` left in the job folder: the segment from
``segments.json`` and the page map from ``_split/split.json``. It is the same
:class:`ingester.splitter.Section` the one-process ``ingest`` hands its router.
"""

from __future__ import annotations

from ingester.router import QUESTION_EXTRACTOR, TABLE_EXTRACTOR, Route, choose_route
from ingester.segments import read_plan
from ingester.splitter import Section

from . import artefacts
from .outcome import StageContext
from .registry import QUESTION, TABLE, UNROUTED


def load_section(ctx: StageContext) -> Section:
    """The section ``ctx.section`` names; raises ``KeyError`` if it is not in the plan."""
    plan = read_plan(ctx.path(artefacts.SEGMENTS_NAME), pdf=ctx.source)
    segment = next(s for s in plan.segments if s.label == ctx.section)
    split = artefacts.read_json(ctx.path(artefacts.SPLIT_DIR, artefacts.SPLIT_NAME))
    entry = next(e for e in split["sections"] if e["label"] == ctx.section)
    return Section(
        segment=segment,
        pdf=ctx.path(artefacts.SPLIT_DIR, entry["file"]),
        original_pdf=ctx.source,
        page_map={int(page): origin for page, origin in entry["page_map"].items()},
    )


def route_name(route: Route) -> str:
    """The registry route for ``ingester``'s routing decision (question and
    ``annotated_booklet`` sections share the question extractor, so one chain)."""
    if route.pipeline == QUESTION_EXTRACTOR:
        return QUESTION
    if route.pipeline == TABLE_EXTRACTOR:
        return TABLE
    return UNROUTED


def section_route(section: Section) -> str:
    return route_name(choose_route(section))
