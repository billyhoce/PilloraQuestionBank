"""``scan``: straighten and OCR a scanned question section; write ``_scan/<label>.pdf`` and ``.json``.

A question or ``annotated_booklet`` section none of whose pages carries a text layer is
a scan, and the question locator has nothing to read on it; one made mostly of picture
pages (questions pasted in as images, :func:`ingester.router.needs_ocr`) has little more.
This stage gives it one
(:func:`question_extractor.scanpaper.read_scanned_paper`): every page straightened
into ``_scan/<label>.pdf`` (each page its original size) and read by Tesseract, the
lines saved with each page's rotation in ``_scan/<label>.json``. ``locate`` then reads
the section off those two as it reads a born-digital one.

``skipped`` otherwise (the text layer is enough, and ``locate`` reads the PDF as it is). ``failed`` when Tesseract is missing, errors or times
out; ``locate`` still runs (it lists this stage as a soft need) and reports the section
not extracted, with this task's error as the reason. The outputs live beside the split
PDFs, not in ``<label>/``, which ``locate`` rebuilds from nothing.
"""

from __future__ import annotations

from ingester.router import needs_ocr
from question_extractor.scanpaper import read_scanned_paper

from .. import artefacts
from ..fingerprint import extract_settings, plan_inputs
from ..outcome import Outcome, StageContext, done, failed, skipped
from ..registry import QUESTION, SECTION, SUBPROCESS, Stage
from ..sections import load_section


def run(ctx: StageContext) -> Outcome:
    section = load_section(ctx)
    label = section.segment.label
    pdf_path, json_path = artefacts.scan_paths(ctx.job_dir, label)
    pdf_path.unlink(missing_ok=True)  # a previous run's copy must not outlive a changed section
    json_path.unlink(missing_ok=True)

    try:
        ocr = needs_ocr(section.pdf, ctx.config.extract)
    except Exception as exc:
        return failed(f"{label} could not be read ({exc})")
    if not ocr:
        return skipped("the section's text layer is enough, so there is nothing to OCR")

    paper = read_scanned_paper(section.pdf, ctx.config.extract)
    if isinstance(paper, str):
        return failed(paper)
    artefacts.write_bytes(pdf_path, paper.pdf)
    artefacts.write_json(json_path, paper.entry())
    problems = tuple(f"page {page.page}: {problem}" for page in paper.pages for problem in page.problems)
    return done(needs_review=bool(problems), warnings=problems)


STAGE = Stage(
    name="scan",
    scope=SECTION,
    kind=SUBPROCESS,
    run=run,
    needs=("split",),
    route=QUESTION,
    inputs=plan_inputs,
    settings=extract_settings,  # without ocr_command: where Tesseract runs, not how it reads
    outputs=lambda ctx: list(artefacts.scan_paths(ctx.job_dir, ctx.section)),
    version=2,  # v2: a section of mostly picture pages is OCR'd too
)
