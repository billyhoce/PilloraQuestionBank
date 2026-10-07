"""``render`` (table route): draw a table section's pages; write the review images (and debug renders).

Reads ``labelled.json`` (what ``questions`` saved) and the section's split PDF, rasterises
each page once and writes ``pNN.png`` (the question rectangles in red, drawn on the
straightened image for a scanned page, the frame its rectangles are in), ``review/pNN.webp``
(clean and **unstraightened**, the PDF's own frame, for the admin review page) and, when the
job asks for debug, ``_debug/pNN.png`` (column pairs, row bands and reading order drawn in).
Nothing is read or detected again; every mark comes from the saved file, as in
``ingester ingest --debug``.
"""

from __future__ import annotations

import logging

from question_extractor.tablepipeline import LABELLED_NAME, read_labelled, render_table

from ..outcome import Outcome, StageContext, done, failed
from ..registry import CPU, SECTION, TABLE, Stage
from ..sections import load_section

log = logging.getLogger(__name__)


def run(ctx: StageContext) -> Outcome:
    section = load_section(ctx)
    out_dir = ctx.path(section.segment.label)
    labelled = out_dir / LABELLED_NAME
    if not labelled.is_file():
        return failed(f"{labelled} is missing; questions has not written it")
    tables, page_results = read_labelled(labelled)

    written = render_table(
        section.pdf, out_dir, page_results, tables, ctx.config.extract, ctx.debug, review=True
    )
    for page in page_results:
        if page.page not in written:
            log.warning("%s: page %d was not rendered", section.segment.label, page.page)
    return done(
        needs_review=any(page.needs_review for page in tables) or section.segment.needs_review
    )


STAGE = Stage(
    name="render", scope=SECTION, kind=CPU, run=run, needs=("questions",), route=TABLE
)
