"""``ocr``: read a scanned table section's question cells; write ``ocr.json``.

Runs the configured OCR command (``ExtractConfig.ocr_command``: the Tesseract container by
default, or a binary on PATH) over ``cells.tiff``, once for the whole section, and saves one
read per cell, in the TIFF's order: the text lines found and the lowest word confidence.
``questions`` places them on the grid from the cell metadata in ``grid.json``.

``skipped`` when the section has no scanned page (``grid`` found no cells to read). ``failed``
when the command is missing, errors, times out or answers for the wrong number of cells;
``questions`` still runs (it lists this stage as a soft need) and flags the scanned pages
with this task's error.
"""

from __future__ import annotations

from question_extractor.ocr import read_tiff
from question_extractor.tablepipeline import GRID_NAME, read_grid

from .. import artefacts
from ..outcome import Outcome, StageContext, done, failed, skipped
from ..registry import SECTION, SUBPROCESS, TABLE, Stage
from ..sections import load_section


def run(ctx: StageContext) -> Outcome:
    label = load_section(ctx).segment.label
    cells = read_grid(ctx.path(label, GRID_NAME))["cells"]
    if not cells:
        return skipped("no page of this section is scanned, so there is nothing to read")

    tiff_path = ctx.path(label, artefacts.CELLS_TIFF_NAME)
    if not tiff_path.is_file():
        return failed(f"{tiff_path.name} is missing; grid could not write it")
    reads = read_tiff(tiff_path.read_bytes(), cells, ctx.config.extract)
    if isinstance(reads, str):
        return failed(reads)
    artefacts.write_json(
        ctx.path(label, artefacts.OCR_NAME), {"reads": [read.entry() for read in reads]}
    )
    return done()


STAGE = Stage(
    name="ocr", scope=SECTION, kind=SUBPROCESS, run=run, needs=("grid",), route=TABLE
)
