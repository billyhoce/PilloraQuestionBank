"""``grid``: read a table section's column pairs and row bands; write ``grid.json`` (and ``cells.tiff``).

Runs ``question_extractor.grid_pages`` over the section's split PDF, with the segmenter's
column layout as the hint, and saves what it found in ``<label>/``:

- ``grid.json``: each page's ruled column pairs and row bands (labels still unread), and the
  metadata of every OCR cell (:meth:`GridPages.entry`);
- ``cells.tiff``, for a section with scanned pages only: the question cells cropped from the
  straightened pages, one TIFF page per cell, which is what ``ocr`` reads. The pixels live
  in this file, not in ``grid.json``.

Nothing is read, grouped or drawn here. The section's folder is rebuilt from nothing each
time, so no later stage's output from a previous run lingers.
"""

from __future__ import annotations

import logging
import shutil

from ingester.router import table_layout
from question_extractor import ExtractionError, grid_pages
from question_extractor.ocr import encode_cells
from question_extractor.tablepipeline import write_grid

from .. import artefacts
from ..outcome import Outcome, StageContext, done, failed
from ..registry import CPU, SECTION, TABLE, Stage
from ..sections import load_section

log = logging.getLogger(__name__)


def run(ctx: StageContext) -> Outcome:
    section = load_section(ctx)
    segment = section.segment
    extract = ctx.config.extract

    try:
        grid = grid_pages(
            section.pdf, extract, table_layout(segment), provenance=section.provenance
        )
    except ExtractionError as exc:
        return failed(str(exc))

    final = ctx.path(segment.label)
    partial = ctx.path(segment.label + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    write_grid(grid, partial)
    if grid.cells:
        tiff = encode_cells(grid.cells, extract)
        if isinstance(tiff, str):  # `ocr` then fails for want of the file, and `questions` flags the pages
            log.warning("%s: %s", segment.label, tiff)
        else:
            artefacts.write_bytes(partial / artefacts.CELLS_TIFF_NAME, tiff)
    artefacts.replace_dir(partial, final)
    return done(
        needs_review=any(page.needs_review for page in grid.pages) or segment.needs_review,
    )


STAGE = Stage(name="grid", scope=SECTION, kind=CPU, run=run, needs=("split",), route=TABLE)
