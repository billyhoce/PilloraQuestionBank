"""A scanned question paper, straightened and given the text layer it never had.

The question locator reads a page's text layer: the gutter numbers it anchors on,
the lines it calibrates the columns from, the words it trims a crop onto. A scan
carries none, so on its own the locator can only hand every page back for review.
:func:`read_scanned_paper` makes it something the locator can read, in two parts:

- **a straightened copy of the PDF**: each page rendered, its scanner borders
  whitened and its tilt rotated out (:func:`.scanpage.read_scan_page`), then set
  back on a page of the original's size. Everything measured on it is in the
  straightened page's points, as on a scanned answer table; the renders and the
  pixel pass of the trim (:mod:`.trim`) read this copy, so they see what was
  measured;
- **the text of every page**, read by Tesseract off those straightened images
  (:func:`.ocr.read_pages`), as :class:`.geometry.TextLine` objects in the same
  points.

:func:`.pipeline.locate_questions` takes both (``text=``) and runs exactly as on a
born-digital paper. Nothing is guessed here: a page whose tilt cannot be trusted
is left unrotated with the reason in its ``problems``, and the caller flags it.

The pages are read in batches of ``ocr_page_batch``, one Tesseract run each, so a
long section never holds more than one batch of page images.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .config import ExtractConfig
from .geometry import TextLine
from .ocr import read_pages
from .scanpage import add_image_page, read_scan_page

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScannedPage:
    """What straightening one page found."""

    page: int
    """1-based PDF page number."""
    angle_deg: float
    """The rotation applied (counter-clockwise as seen, about the page centre); 0.0 when none."""
    measured_deg: float | None
    """The tilt measured; ``None`` when nothing on the page could measure it."""
    problems: tuple[str, ...] = ()

    def entry(self) -> dict:
        return {
            "page": self.page,
            "angle_deg": self.angle_deg,
            "measured_deg": self.measured_deg,
            "problems": list(self.problems),
        }

    @classmethod
    def from_entry(cls, entry: dict) -> ScannedPage:
        return cls(entry["page"], entry["angle_deg"], entry["measured_deg"], tuple(entry["problems"]))


@dataclass
class ScannedPaper:
    pdf: bytes
    """The straightened copy: one page per page of the scan, each its original size."""
    pages: list[ScannedPage]
    text: dict[int, list[TextLine]] = field(default_factory=dict)
    """Each page's OCR'd lines, in straightened points, by page number."""

    def entry(self) -> dict:
        """JSON-ready, without the PDF: ``{"pages": [...], "text": {"<page>": [line, ...]}}``."""
        return {
            "pages": [page.entry() for page in self.pages],
            "text": {str(n): [line.entry() for line in lines] for n, lines in self.text.items()},
        }


def read_scanned_paper(pdf_path: Path, config: ExtractConfig) -> ScannedPaper | str:
    """Straighten every page of ``pdf_path`` and OCR it; a string says why it could not be read."""
    try:
        source = pymupdf.open(pdf_path)
    except Exception as exc:
        return f"{pdf_path.name} could not be opened ({exc})"
    out = pymupdf.open()
    pages: list[ScannedPage] = []
    text: dict[int, list[TextLine]] = {}
    try:
        for start in range(0, source.page_count, config.ocr_page_batch):
            batch = []
            for number in range(start, min(start + config.ocr_page_batch, source.page_count)):
                page = source[number]
                scan = read_scan_page(page, config)
                add_image_page(out, page.rect, scan.image)
                pages.append(
                    ScannedPage(scan.page, scan.angle_deg, scan.measured_deg, tuple(scan.problems))
                )
                batch.append(scan)
            lines = read_pages(batch, config)
            if isinstance(lines, str):
                return lines
            for scan, page_lines in zip(batch, lines):
                text[scan.page] = page_lines
        pdf = out.tobytes(garbage=3, deflate=True)
    finally:
        out.close()
        source.close()
    straightened = sum(1 for page in pages if page.angle_deg)
    log.info(
        "%s: straightened %d of %d scanned page(s) and read %d line(s) of text",
        pdf_path.name, straightened, len(pages), sum(len(lines) for lines in text.values()),
    )
    return ScannedPaper(pdf=pdf, pages=pages, text=text)


def read_scan_record(entry: dict) -> tuple[list[ScannedPage], dict[int, list[TextLine]]]:
    """The pages and text :meth:`ScannedPaper.entry` wrote."""
    pages = [ScannedPage.from_entry(page) for page in entry["pages"]]
    text = {
        int(n): [TextLine.from_entry(line) for line in lines] for n, lines in entry["text"].items()
    }
    return pages, text
