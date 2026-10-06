"""End-to-end reading of one table-format answer PDF (``--table``).

The answer-table counterpart of :mod:`.pipeline`, sharing its first stages and
none of its question-paper ones:

1. **geometry** — the same extraction, which also carries every axis-aligned
   path piece (:attr:`PageGeometry.rule_segments`).
2. **furniture** — the same running header/footer detection, so a ruled footer
   or a boxed school crest can neither join a table nor become a row.
3. **grid** — per page, the column pairs and their row bands
   (:func:`.tables.find_tables`). A scanned page is straightened first and its
   rules are read off the pixels (:mod:`.scanpage`), with the looser
   ``scan_rule_pos_tol``. There is no calibration stage: a table rules its own
   question column, so the rule between the question and answer columns is what
   ``x_cut`` is to a question paper.
4. **OCR** — every scanned page's question cells, in one container run for the
   whole section (:mod:`.ocr`). A digital page's text layer needs none.
5. **labels** — each row's question label, the checks, and the reading order
   (:func:`.tables.label_table_page`), with the section's layout as the hint.
6. **questions** — the rows grouped into questions, one rectangle per run of
   rows (:mod:`.tablequestions`).
7. **render + manifest** — each page whole with its question rectangles drawn
   in red (:mod:`.render`), and ``manifest.json``, in the question pipeline's
   shape. A scanned page is drawn on its straightened image, the frame its
   rectangles are in. ``tables.json`` records the row-level reading behind them,
   and ``--debug`` draws it (:mod:`.tablerender`).

Provenance works as in :mod:`.pipeline`: it takes part in no detection and only
adds ``original_page`` beside each page number in the output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from .boundaries import Question
from .config import ExtractConfig
from .furniture import Furniture, detect_furniture
from .geometry import PageGeometry, TextLine, extract_document
from .manifest import build_manifest, config_snapshot, write_manifest
from .ocr import BUILD_HINT, OcrCell, question_cells, read_cells
from .pipeline import ExtractionError, _WarningCollector, paper_name
from .provenance import SourceProvenance, check_page_map
from .render import render_pages
from .scanpage import read_scan_page
from .tablequestions import build_table_questions
from .tablerender import render_table_pages
from .tables import TableLayout, TablePage, find_tables, label_table_page
from .trim import _pixel_box

log = logging.getLogger(__name__)

TABLES_NAME = "tables.json"


@dataclass
class TablePaperResult:
    """What one table-format answer PDF's run produced."""

    paper: str
    out_dir: Path
    pages: list[TablePage]
    questions: list[Question]
    images: dict[int, str]
    manifest_path: Path
    tables_path: Path
    warnings: list[str]
    provenance: SourceProvenance | None = None

    @property
    def needs_review(self) -> bool:
        return any(page.needs_review for page in self.pages)

    @property
    def row_count(self) -> int:
        return sum(len(pair.rows) for page in self.pages for pair in page.pairs)


def extract_table_paper(
    pdf_path: Path,
    output_root: Path,
    config: ExtractConfig,
    debug: bool = False,
    provenance: SourceProvenance | None = None,
    layout: TableLayout | None = None,
) -> TablePaperResult:
    """Read every page of a table-format answer PDF into column pairs and rows.

    ``layout`` is the segmenter's word on which columns hold the question numbers
    and which way the answers read; without it both are measured.
    """
    collector = _WarningCollector()
    package_logger = logging.getLogger(__package__)
    package_logger.addHandler(collector)
    try:
        return _extract(pdf_path, output_root, config, debug, collector, provenance, layout)
    finally:
        package_logger.removeHandler(collector)


def _extract(
    pdf_path: Path,
    output_root: Path,
    config: ExtractConfig,
    debug: bool,
    collector: _WarningCollector,
    provenance: SourceProvenance | None,
    layout: TableLayout | None,
) -> TablePaperResult:
    name = paper_name(pdf_path)
    log.info("processing %s as an answer table", pdf_path.name)
    scan_config = replace(config, table_rule_pos_tol=config.scan_rule_pos_tol)

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        raise ExtractionError(f"could not open {pdf_path.name}: {exc}") from exc
    with doc:
        page_count = doc.page_count
        try:
            pages = extract_document(doc)
        except Exception as exc:
            raise ExtractionError(f"could not read {pdf_path.name}: {exc}") from exc
        if not pages:
            raise ExtractionError(f"{pdf_path.name} has no pages")
        check_page_map(provenance, page_count, pdf_path.name)
        furniture = detect_furniture(pages, config)

        cells: list[OcrCell] = []
        results = [
            _find_page(doc[geom.number - 1], geom, furniture, config, scan_config, layout, cells)
            for geom in pages
        ]

    ocr_lines = _read_scanned_labels(name, cells, results, config)
    for geom, result in zip(pages, results):
        if result.scanned:
            label_table_page(
                result,
                ocr_lines.get(result.page, []) if ocr_lines is not None else [],
                scan_config,
                layout,
                labels_read=ocr_lines is not None,
            )
        else:
            label_table_page(result, furniture.body_lines(geom), config, layout)
    for result in results:
        if result.needs_review:
            log.warning("%s p%d: %s", name, result.page, result.review_reason)
    questions, page_results = build_table_questions(results, config)

    out_dir = output_root / name
    straightened = {r.page: r.straightened_deg for r in results if r.straightened_deg}
    images = render_pages(
        pdf_path,
        out_dir,
        page_results,
        {question.number: len(question.bands) for question in questions},
        None,
        config,
        straightened=straightened,
    )
    if debug:
        render_table_pages(pdf_path, out_dir, results, config, debug=True)

    warnings = list(collector.messages)
    manifest = build_manifest(
        paper=name,
        source_pdf=pdf_path,
        page_count=page_count,
        start_page=1,
        end_page=None,
        questions=questions,
        results=page_results,
        images=images,
        calibration=None,
        config=config,
        warnings=warnings,
        provenance=provenance,
    )
    _table_manifest(manifest, results, layout)
    manifest_path = write_manifest(manifest, out_dir)

    record = build_tables_record(
        paper=name,
        source_pdf=pdf_path,
        page_count=page_count,
        results=results,
        images=images,
        config=config,
        warnings=warnings,
        provenance=provenance,
        layout=layout,
    )
    tables_path = out_dir / TABLES_NAME
    tables_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    result = TablePaperResult(
        paper=name,
        out_dir=out_dir,
        pages=results,
        questions=questions,
        images=images,
        manifest_path=manifest_path,
        tables_path=tables_path,
        warnings=warnings,
        provenance=provenance,
    )
    log.info(
        "%s: %d question(s) from %d row(s) across %d page(s)%s",
        name,
        len(questions),
        result.row_count,
        len(results),
        " - some pages need review" if result.needs_review else "",
    )
    return result


TABLE_OUTPUT_NOTE = (
    "Read from a table-format answer key. Pages are rendered whole with each "
    "question's rectangles drawn in red; no cropping is applied. A question has "
    "one rectangle per run of its rows that sit one under the other in one "
    "column pair on one page, from the grid corner above and left of its first "
    "question cell to the bottom right of its last row, every answer column "
    "included; a question split by a column or page break has one per piece. "
    "Rectangles follow the table's rules and are not trimmed. On a page with "
    "'straightened' set (a scan) they are in the page's points after it was "
    "rotated counter-clockwise by angle_deg about its centre, and are drawn on "
    "that straightened image. tables.json holds the row-level reading."
)


def _table_manifest(
    manifest: dict, results: list[TablePage], layout: TableLayout | None
) -> None:
    """Fit the question-paper manifest to a table: its note, layout and rotations."""
    manifest["output_mode"] = "table_questions"
    manifest["output_note"] = TABLE_OUTPUT_NOTE
    manifest["layout"] = _layout_entry(layout)
    by_page = {result.page: result for result in results}
    for entry in manifest["pages"]:
        entry["straightened"] = _straightened(by_page[entry["page"]])


def _find_page(
    page: pymupdf.Page,
    geom: PageGeometry,
    furniture: Furniture,
    config: ExtractConfig,
    scan_config: ExtractConfig,
    layout: TableLayout | None,
    cells: list[OcrCell],
) -> TablePage:
    """One page's grid, with whether each row's answer area holds ink; a scanned
    page's question cells are added to ``cells``."""
    band = furniture.band(geom.number)
    inset, floor = config.table_cell_inset, config.trim_min_ink_span
    if not geom.has_page_sized_image(config.figure_max_area_frac):
        result = find_tables(geom, band, config, layout)
        for pair in result.pairs:
            for row in pair.rows:
                area = pair.answer_area(row, inset)
                row.answer_ink = _pixel_box(page, area, config, min_ink=floor) is not None
        return result
    scan = read_scan_page(page, config)
    result = find_tables(geom, band, scan_config, layout, segments=scan.segments())
    result.straightened_deg = scan.angle_deg
    result.problems[:0] = scan.problems
    for pair in result.pairs:
        for row in pair.rows:
            row.answer_ink = scan.has_ink(pair.answer_area(row, inset), floor)
    cells.extend(question_cells(scan, result, config))
    return result


def _read_scanned_labels(
    name: str, cells: list[OcrCell], results: list[TablePage], config: ExtractConfig
) -> dict[int, list[TextLine]] | None:
    """OCR every scanned question cell at once, as text lines by page.

    ``None`` when nothing could be read. Every scanned page is then flagged with
    the reason, and the section is still written: its grid is as good as ever.
    """
    if not cells:
        return {}
    reads = read_cells(cells, config)
    if isinstance(reads, str):
        log.warning("%s: OCR unavailable: %s (%s)", name, reads, BUILD_HINT)
        for result in results:
            if result.scanned and result.tables:
                result.problems.append(f"OCR unavailable, so no question label was read: {reads}")
        return None

    lines: dict[int, list[TextLine]] = {}
    for cell, read in zip(cells, reads):
        lines.setdefault(cell.page, []).extend(read.lines)
        cell.row.confidence = read.confidence
    return lines


def _r(value: float) -> float:
    return round(value, 2)


def _origin(page: int, provenance: SourceProvenance | None) -> dict:
    """``original_page`` for one page, or nothing without provenance."""
    return {} if provenance is None else {"original_page": provenance.original_page(page)}


def _page_entry(
    result: TablePage, images: dict[int, str], provenance: SourceProvenance | None
) -> dict:
    return {
        "page": result.page,
        **_origin(result.page, provenance),
        "image": images.get(result.page),
        "has_text": result.has_text,
        "straightened": _straightened(result),
        "body_band": {"top": _r(result.body_band.top), "bottom": _r(result.body_band.bottom)},
        "tables": [
            {"x0": _r(t.x0), "y0": _r(t.y0), "x1": _r(t.x1), "y1": _r(t.y1)}
            for t in result.tables
        ],
        "reading_order": result.reading_order,
        "inversions": result.inversions,
        "column_pairs": [
            {
                "pair": pair.index,
                "x0": _r(pair.x0),
                "question_x1": _r(pair.question_x1),
                "x1": _r(pair.x1),
                "y0": _r(pair.top),
                "y1": _r(pair.bottom),
                "rows": [
                    {
                        "row": i,
                        "order": row.order,
                        "y0": _r(row.top),
                        "y1": _r(row.bottom),
                        "label": row.label,
                        "question_number": row.number,
                        **(
                            {"ocr_confidence": _conf(row.confidence)}
                            if result.scanned
                            else {}
                        ),
                    }
                    for i, row in enumerate(pair.rows, start=1)
                ],
            }
            for pair in result.pairs
        ],
        # Each run is an unbroken stretch of reading inside one pair; every
        # boundary between runs is a column break.
        "runs": [
            {"pair": pair, "first_row": first, "last_row": last}
            for pair, first, last in result.runs
        ],
        "needs_review": result.needs_review,
        "review_reason": result.review_reason,
    }


def _conf(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _straightened(result: TablePage) -> dict | None:
    """How a scanned page was turned before anything on it was measured.

    Every rectangle on such a page is in the straightened page's points: the page
    image rotated counter-clockwise (as seen) by ``angle_deg`` about its centre.
    ``None`` on a born-digital page, whose rectangles are the PDF's own.
    """
    if result.straightened_deg is None:
        return None
    return {"angle_deg": round(result.straightened_deg, 3)}


def _layout_entry(layout: TableLayout | None) -> dict | None:
    if layout is None:
        return None
    return {
        "question_columns": list(layout.question_columns),
        "reading_order": layout.reading_order,
    }


def build_tables_record(
    paper: str,
    source_pdf: Path,
    page_count: int,
    results: list[TablePage],
    images: dict[int, str],
    config: ExtractConfig,
    warnings: list[str],
    provenance: SourceProvenance | None = None,
    layout: TableLayout | None = None,
) -> dict:
    """Assemble ``tables.json``: the table geometry of every page, in PDF points."""
    return {
        "paper": paper,
        "source_pdf": str(source_pdf),
        **({} if provenance is None else {"provenance": provenance.manifest_entry()}),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "layout": _layout_entry(layout),
        "output_mode": "table_geometry",
        "output_note": (
            "Diagnostic of an intermediate stage: each page's ruled column pairs and "
            "their row bands, not crops. Rows are how a question's rectangle is "
            "found; grouping them into whole questions is a later stage. Rows are "
            "numbered by 'order' in reading order, and each boundary between 'runs' "
            "is a column break."
        ),
        "page_count": page_count,
        "render_zoom": config.zoom,
        "pages": [_page_entry(result, images, provenance) for result in results],
        "needs_review_pages": [
            {
                "page": result.page,
                **_origin(result.page, provenance),
                "reason": result.review_reason,
                "image": images.get(result.page),
            }
            for result in results
            if result.needs_review
        ],
        "warnings": warnings,
        "config": config_snapshot(config),
    }
