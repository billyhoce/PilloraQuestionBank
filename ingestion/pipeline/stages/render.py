"""``render``: draw a located section's pages; write the review images (and debug renders).

Reads ``<label>/detections.json`` (what ``locate`` saved) and the section's split
PDF, rasterises each page once and writes ``pNN.png`` (the question rectangles in
red), ``review/pNN.webp`` (clean, for the admin review page) and, when the job
asks for debug, ``_debug/pNN.png`` (calibration and anchors drawn in). No detection
runs: the rectangles and every overlay come from the saved file, which is also how
``ingester ingest --debug`` draws its debug renders.

The manifest ``locate`` wrote already names these images, so a page whose image is
not written here is a warning on this task.
"""

from __future__ import annotations

import json
import logging

from question_extractor.pipeline import DETECTIONS_NAME, render_saved
from question_extractor.render import page_filename

from ..outcome import Outcome, StageContext, done, failed
from ..registry import CPU, QUESTION, SECTION, Stage
from ..sections import load_section

log = logging.getLogger(__name__)


def run(ctx: StageContext) -> Outcome:
    section = load_section(ctx)
    out_dir = ctx.path(section.segment.label)
    detections = out_dir / DETECTIONS_NAME
    if not detections.is_file():
        return failed(f"{detections} is missing; locate has not written it")
    pages = json.loads(detections.read_text(encoding="utf-8"))["pages"]

    written = render_saved(
        section.pdf, out_dir, ctx.config.extract, debug=ctx.debug, review=True
    )
    for page in pages:
        if page["page"] not in written:
            log.warning("%s: page %d was not rendered", section.segment.label, page["page"])
    return done(
        needs_review=any(page["needs_review"] for page in pages) or section.segment.needs_review
    )


STAGE = Stage(name="render", scope=SECTION, kind=CPU, run=run, needs=("locate",), route=QUESTION)
