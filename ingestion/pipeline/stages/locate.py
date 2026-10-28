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

A section ``scan`` OCR'd (a scan, or mostly picture pages) is read off what it left: the
straightened copy of the PDF and the OCR'd text (``_scan/<label>.pdf`` and ``.json``).
Its rectangles are in the straightened pages' points, which the manifest records per
page (``straightened``), and a page ``scan`` could not straighten is flagged. When
``scan`` did not finish (Tesseract missing, say), a section with no text ends as
``skipped`` with why: the question extractor cannot crop a page it cannot read. A
picture-page section is then located off its own thin text layer. The section's folder
is rebuilt from nothing each time, so a previous run's rectangles never linger.
"""

from __future__ import annotations

import logging
import shutil

from ingester.router import has_text
from question_extractor import ExtractionError, locate_questions
from question_extractor.pipeline import DETECTIONS_NAME, write_detections, write_question_manifest
from question_extractor.render import page_filename
from question_extractor.scanpaper import read_scan_record
from question_extractor.warnscope import collect_warnings, current_warnings

from .. import artefacts
from ..fingerprint import extract_settings, plan_inputs
from ..outcome import Outcome, StageContext, done, failed, skipped
from ..registry import CPU, QUESTION, SECTION, Stage
from ..sections import load_section

log = logging.getLogger(__name__)

NO_TEXT = "no page carries extractable text (a scanned paper needs OCR)"


def run(ctx: StageContext) -> Outcome:
    section = load_section(ctx)
    segment = section.segment
    extract = ctx.config.extract

    scan_pdf, scan_json = artefacts.scan_paths(ctx.job_dir, segment.label)
    scanned = "scan" not in ctx.unmet and scan_pdf.is_file() and scan_json.is_file()
    pdf, text, straightened, problems = section.pdf, None, None, {}
    if scanned:
        pages, text = read_scan_record(artefacts.read_json(scan_json))
        pdf = scan_pdf
        straightened = {page.page: page.angle_deg for page in pages}
        problems = {page.page: "; ".join(page.problems) for page in pages if page.problems}
    else:
        try:
            carries_text = has_text(section.pdf)
        except Exception as exc:
            return failed(f"{segment.label} could not be read ({exc})")
        if not carries_text:
            unmet = ctx.unmet.get("scan")
            reason = NO_TEXT if unmet is None else f"{NO_TEXT}, and OCR {unmet.status}: {unmet.detail}"
            log.warning("%s: not routed: %s", segment.label, reason)
            return skipped(reason, needs_review=True)

    final = ctx.path(segment.label)
    partial = ctx.path(segment.label + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    with collect_warnings():
        if scanned:
            log.warning(
                "%s is a scan: its pages were straightened and read by OCR, so check each "
                "question's number", segment.label,
            )
        try:
            located = locate_questions(pdf, extract, provenance=section.provenance, text=text)
        except ExtractionError as exc:
            return failed(str(exc), warnings=tuple(current_warnings()))
        for page in located.pages:
            if page.page in problems:  # a tilt not trusted: the page was left as scanned
                page.needs_review = True
                page.review_reason = "; ".join(r for r in (page.review_reason, problems[page.page]) if r)
        images = {page.page: page_filename(page.page) for page in located.pages}
        write_detections(located, partial)
        write_question_manifest(
            located, partial, images, extract, current_warnings(), section.provenance, straightened
        )
        warnings = tuple(current_warnings())
    artefacts.replace_dir(partial, final)
    return done(
        needs_review=any(page.needs_review for page in located.pages) or segment.needs_review,
        warnings=warnings,
    )


def _inputs(ctx: StageContext) -> list:
    return [*plan_inputs(ctx), *artefacts.scan_paths(ctx.job_dir, ctx.section)]


STAGE = Stage(
    name="locate",
    scope=SECTION,
    kind=CPU,
    run=run,
    needs=("split",),
    soft_needs=("scan",),
    route=QUESTION,
    inputs=_inputs,
    settings=extract_settings,
    outputs=lambda ctx: [
        ctx.path(ctx.section, "manifest.json"),
        ctx.path(ctx.section, DETECTIONS_NAME),
    ],
    version=3,  # v3: content above the first question with none open is a preamble, not flagged
)
