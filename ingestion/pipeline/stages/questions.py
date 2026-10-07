"""``questions``: label a table section's rows and group them into questions.

Reads ``grid.json``, the section's split PDF (for the text layer of its digital pages) and,
when the section has scanned pages, ``ocr.json``; writes ``manifest.json`` and
``tables.json`` (the files ``ingester ingest`` writes for a table section) and
``labelled.json``, the labelled grid and the question rectangles ``render`` draws from.

``ocr`` is a *soft* need: when it failed (or its read file is missing) the scanned pages come
back flagged, with the OCR task's error as the reason, exactly as ``question_extractor
--table`` flags them when its OCR cannot run. The grid is as good as ever, so the manifest
is still written. A born-digital section never needed ``ocr``, which is then ``skipped``.

The manifest names each page's image before ``render`` has written it, as ``locate`` does.
"""

from __future__ import annotations

import json
import shutil

from ingester.router import table_layout
from question_extractor import ExtractionError
from question_extractor.ocr import OcrRead
from question_extractor.tablepipeline import (
    GRID_NAME,
    load_grid,
    read_labels,
    table_images,
    write_labelled,
    write_table_records,
)
from question_extractor.tablequestions import build_table_questions
from question_extractor.warnscope import collect_warnings, current_warnings

from .. import artefacts
from ..outcome import Outcome, StageContext, done, failed
from ..registry import CPU, SECTION, TABLE, Stage
from ..sections import load_section


def run(ctx: StageContext) -> Outcome:
    section = load_section(ctx)
    segment = section.segment
    extract = ctx.config.extract
    out_dir = ctx.path(segment.label)
    layout = table_layout(segment)

    grid_path = out_dir / GRID_NAME
    if not grid_path.is_file():
        return failed(f"{grid_path} is missing; grid has not written it")
    try:
        grid = load_grid(grid_path, section.pdf, extract)
    except ExtractionError as exc:
        return failed(str(exc))

    with collect_warnings():
        reads = _reads(ctx, out_dir) if grid.cells else None
        read_labels(grid, extract, layout, reads)
        questions, page_results = build_table_questions(grid.pages, extract)
        write_labelled(grid, page_results, out_dir)
        warnings = current_warnings()
        write_table_records(
            grid, questions, page_results, table_images(page_results), out_dir, extract,
            warnings, section.provenance, layout,
        )
    return done(
        needs_review=any(page.needs_review for page in grid.pages) or segment.needs_review,
        warnings=tuple(warnings),
    )


def _reads(ctx: StageContext, out_dir) -> list[OcrRead] | str:
    """The saved OCR reads, or why there are none."""
    path = out_dir / artefacts.OCR_NAME
    if path.is_file():
        record = json.loads(path.read_text(encoding="utf-8"))
        return [OcrRead.from_entry(read) for read in record["reads"]]
    unmet = ctx.unmet.get("ocr")
    if unmet is not None:
        return f"the ocr stage {unmet.status}: {unmet.detail}"
    return f"{path.name} is missing"


STAGE = Stage(
    name="questions",
    scope=SECTION,
    kind=CPU,
    run=run,
    needs=("grid",),
    soft_needs=("ocr",),
    route=TABLE,
)
