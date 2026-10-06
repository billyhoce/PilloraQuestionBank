"""Reading a scanned table's question cells with Tesseract.

The only module that runs Tesseract. It runs in the repo's own container
(``ingestion/docker/tesseract/``, built by ``docker compose build tesseract``), so the host
needs Docker and nothing else, and every machine reads with the same Tesseract
release.

**Only the question cells are read**, cut from the straightened page
(:mod:`.scanpage`) one row at a time. A scan's own text layer, where it has one,
is in the unstraightened page's coordinates and was read without knowing where
the cells are. The question column is the one thing the table reader needs text
for, and a cell cut clear of its rules (``table_cell_inset``) holds nothing but
the label. Each cell is read against a character whitelist of digits, lower-case
letters, brackets and the full stop (``ocr_whitelist``), which is every character
a label like ``12(a)(ii)`` can hold.

**One container run per section.** Every cell of every scanned page goes into one
multi-page TIFF, piped to ``tesseract stdin stdout ... tsv``. Each TIFF page is
one cell, and the TSV's ``page_num`` says which. Nothing is written to disk and
nothing is mounted. Starting a container costs about half a second, which is
paid once.

**Failure is reported, never raised.** Docker missing, the daemon down, the image
not built, a timeout, or a reply that does not cover every cell: :func:`read_cells`
returns the reason as a string, and the pipeline flags the scanned pages with
it. ``--pull never`` keeps a missing image from being fetched from Docker Hub
under the same name.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

import cv2
import numpy as np
import pymupdf

from .config import ExtractConfig
from .geometry import Span, TextLine
from .scanpage import ScanPage
from .tables import RowBand, TablePage

log = logging.getLogger(__name__)

BUILD_HINT = "build the image with `docker compose build tesseract`"


@dataclass(frozen=True)
class OcrCell:
    """One question cell to read: its crop, and where the crop sits on the page."""

    page: int
    row: RowBand
    """The row whose question cell this is."""
    rect: pymupdf.Rect
    """The cropped area, in the straightened page's points."""
    image: np.ndarray
    """The crop, padded on every side with ``ocr_pad`` white pixels."""
    origin_px: tuple[int, int]
    """Page pixel of the crop's top-left corner, before padding."""
    pad_px: int
    scale: float
    """Pixels per point."""


@dataclass(frozen=True)
class OcrRead:
    """What Tesseract read in one cell."""

    lines: tuple[TextLine, ...] = ()
    """One line per text line it found, in straightened page points."""
    confidence: float | None = None
    """The lowest word confidence (0-100); ``None`` when it read nothing."""


def question_cells(scan: ScanPage, result: TablePage, config: ExtractConfig) -> list[OcrCell]:
    """Every row's question cell on a scanned page, cut clear of its rules."""
    inset = config.table_cell_inset
    cells: list[OcrCell] = []
    for pair in result.pairs:
        for row in pair.rows:
            rect = pymupdf.Rect(
                pair.x0 + inset, row.top + inset, pair.question_x1 - inset, row.bottom - inset
            )
            if rect.is_empty:
                continue
            crop = scan.crop(rect, config.ocr_pad)
            if crop is None:
                continue
            image, origin = crop
            cells.append(OcrCell(scan.page, row, rect, image, origin, config.ocr_pad, scan.scale))
    return cells


def read_cells(cells: list[OcrCell], config: ExtractConfig) -> list[OcrRead] | str:
    """What each cell says, in order, or why nothing could be read."""
    if not cells:
        return []
    params = [cv2.IMWRITE_TIFF_XDPI, config.scan_dpi, cv2.IMWRITE_TIFF_YDPI, config.scan_dpi]
    ok, tiff = cv2.imencodemulti(".tiff", [cell.image for cell in cells], params)
    if not ok:
        return "the question cells could not be encoded as a TIFF"
    command = [
        "docker", "run", "--rm", "-i", "--pull", "never", "--network", "none",
        config.ocr_image,
        "stdin", "stdout",
        "--psm", str(config.ocr_psm),
        "--dpi", str(config.scan_dpi),
        "-c", f"tessedit_char_whitelist={config.ocr_whitelist}",
        "tsv",
    ]
    try:
        proc = subprocess.run(
            command, input=tiff.tobytes(), capture_output=True, timeout=config.ocr_timeout_s
        )
    except FileNotFoundError:
        return "docker is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return f"the Tesseract container did not finish within {config.ocr_timeout_s}s"
    except OSError as exc:
        return f"docker could not be run ({exc})"
    if proc.returncode != 0:
        return f"the Tesseract container failed: {_last_error(proc.stderr)}"

    pages, words = _parse_tsv(proc.stdout.decode("utf-8", errors="replace"))
    if pages != len(cells):
        return f"Tesseract returned {pages} page(s) for {len(cells)} cell(s)"
    log.info("OCR read %d question cell(s) in one container run", len(cells))
    return [_read(cell, words.get(n, [])) for n, cell in enumerate(cells, start=1)]


@dataclass(frozen=True)
class _Word:
    line: tuple[int, int, int]
    """``(block, paragraph, line)``: which text line Tesseract put it on."""
    left: int
    top: int
    width: int
    height: int
    confidence: float
    text: str


def _parse_tsv(tsv: str) -> tuple[int, dict[int, list[_Word]]]:
    """The number of pages in a Tesseract TSV, and its words by page."""
    pages = 0
    words: dict[int, list[_Word]] = {}
    for row in tsv.splitlines()[1:]:
        fields = row.split("\t")
        if len(fields) < 12:
            continue
        level = fields[0]
        if level == "1":
            pages += 1
        elif level == "5" and fields[11].strip():
            words.setdefault(int(fields[1]), []).append(
                _Word(
                    line=(int(fields[2]), int(fields[3]), int(fields[4])),
                    left=int(fields[6]),
                    top=int(fields[7]),
                    width=int(fields[8]),
                    height=int(fields[9]),
                    confidence=float(fields[10]),
                    text=fields[11].strip(),
                )
            )
    return pages, words


def _read(cell: OcrCell, words: list[_Word]) -> OcrRead:
    if not words:
        return OcrRead()
    by_line: dict[tuple[int, int, int], list[_Word]] = {}
    for word in words:
        by_line.setdefault(word.line, []).append(word)
    lines = [_text_line(cell, sorted(group, key=lambda w: w.left)) for group in by_line.values()]
    lines.sort(key=lambda line: (line.y0, line.x0))
    return OcrRead(lines=tuple(lines), confidence=min(word.confidence for word in words))


def _text_line(cell: OcrCell, words: list[_Word]) -> TextLine:
    spans = tuple(Span(rect=_page_rect(cell, word), text=word.text) for word in words)
    rect = pymupdf.Rect(
        min(span.rect.x0 for span in spans),
        min(span.rect.y0 for span in spans),
        max(span.rect.x1 for span in spans),
        max(span.rect.y1 for span in spans),
    )
    return TextLine(
        page=cell.page,
        rect=rect,
        text=" ".join(span.text for span in spans),
        leading_token=spans[0].text.split()[0],
        leading_x=spans[0].rect.x0,
        spans=spans,
    )


def _page_rect(cell: OcrCell, word: _Word) -> pymupdf.Rect:
    """A word's box in the padded crop, as straightened page points."""
    x0_px, y0_px = cell.origin_px

    def to_pt(px: int, origin: int) -> float:
        return (px - cell.pad_px + origin) / cell.scale

    return pymupdf.Rect(
        to_pt(word.left, x0_px),
        to_pt(word.top, y0_px),
        to_pt(word.left + word.width, x0_px),
        to_pt(word.top + word.height, y0_px),
    )


def _last_error(stderr: bytes) -> str:
    """The line of the container's stderr that says what went wrong.

    Docker's own error (``docker: Error response from daemon: No such image``,
    ``docker: error during connect``) when there is one, since Docker follows it
    with a generic ``Run 'docker run --help'``; otherwise Tesseract's last line
    that is not its ``Page N`` progress.
    """
    lines = [
        line.strip()
        for line in stderr.decode("utf-8", errors="replace").splitlines()
        if line.strip()
        and not line.strip().startswith("Page ")
        and not line.strip().startswith("Run 'docker")
    ]
    docker = [line for line in lines if line.startswith("docker:")]
    chosen = docker[0] if docker else (lines[-1] if lines else "no error message")
    return chosen[:200]
