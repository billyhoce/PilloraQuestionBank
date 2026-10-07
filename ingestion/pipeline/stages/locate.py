"""``locate``: find a question section's questions; write ``manifest.json`` and ``detections.json``.

Runs ``question_extractor.locate_questions`` over the section's split PDF, with the
split's page map as provenance, and writes what it found into ``<label>/``: the
detections the renders are drawn from and the manifest. Nothing is drawn here.

The manifest names each page's image (``pNN.png``) before ``render`` has written it:
the name is a function of the page number alone and ``render`` writes one for every
page the detections list, so the manifest is the one ``ingester ingest`` writes for
the section, key for key. Splitting the writes this way is what lets the review page
read rectangles as soon as ``locate`` is done and lets ``render`` be rerun (say, with
debug on) without detecting again.

A section with no text on any page ends as ``skipped``: it is a scan, and the
question extractor cannot crop one (``ingester.router``'s rule). The section's folder is
rebuilt from nothing each time, so a previous run's rectangles never linger.
"""

from __future__ import annotations

import logging
import shutil

from ingester.router import has_text
from question_extractor import ExtractionError, locate_questions
from question_extractor.pipeline import write_detections, write_question_manifest
from question_extractor.render import page_filename
from question_extractor.warnscope import collect_warnings, current_warnings

from .. import artefacts
from ..outcome import Outcome, StageContext, done, failed, skipped
from ..registry import CPU, QUESTION, SECTION, Stage
from ..sections import load_section

log = logging.getLogger(__name__)


def run(ctx: StageContext) -> Outcome:
    section = load_section(ctx)
    segment = section.segment
    extract = ctx.config.extract

    try:
        carries_text = has_text(section.pdf)
    except Exception as exc:
        return failed(f"{segment.label} could not be read ({exc})")
    if not carries_text:
        reason = "no page carries extractable text (a scanned paper needs OCR)"
        log.warning("%s: not routed: %s", segment.label, reason)
        return skipped(reason, needs_review=True)

    final = ctx.path(segment.label)
    partial = ctx.path(segment.label + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    with collect_warnings():
        try:
            located = locate_questions(section.pdf, extract, provenance=section.provenance)
        except ExtractionError as exc:
            return failed(str(exc), warnings=tuple(current_warnings()))
        images = {page.page: page_filename(page.page) for page in located.pages}
        write_detections(located, partial)
        write_question_manifest(
            located, partial, images, extract, current_warnings(), section.provenance
        )
        warnings = tuple(current_warnings())
    artefacts.replace_dir(partial, final)
    return done(
        needs_review=any(page.needs_review for page in located.pages) or segment.needs_review,
        warnings=warnings,
    )


STAGE = Stage(
    name="locate", scope=SECTION, kind=CPU, run=run, route=QUESTION
)
