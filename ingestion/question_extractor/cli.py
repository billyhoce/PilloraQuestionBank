"""Command-line entry point.

    python -m question_extractor <input.pdf|folder> --output-dir output/ [--start-page N]
    python -m question_extractor <answers.pdf|folder> --table --output-dir output/ \
        [--question-columns 0,2] [--reading-order down|across]

A folder input processes every PDF it contains; one paper failing does not stop
the rest. ``--table`` reads table-format answer PDFs instead of question papers
(:mod:`.tablepipeline`).
"""

from __future__ import annotations

import argparse
import logging
import shlex
import sys
from dataclasses import replace
from pathlib import Path

from .config import ExtractConfig
from .pipeline import ExtractionError, PaperResult, extract_paper
from .tablepipeline import TablePaperResult, extract_table_paper
from .tables import ACROSS, DOWN, TableLayout

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="question_extractor",
        description=(
            "Locate individual exam questions in digital-text PDF papers and render "
            "each page with the question boundaries drawn on it in red."
        ),
    )
    parser.add_argument("input", type=Path, help="a PDF file, or a folder of PDFs")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="root folder for per-paper output folders (default: output)",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=None,
        help=(
            "1-based page the questions start on; by default the first page with a "
            "question number in the gutter, which skips cover and formula sheets"
        ),
    )
    parser.add_argument(
        "--zoom",
        type=float,
        default=ExtractConfig.zoom,
        help=f"render scale, 3.0 is ~216 dpi (default: {ExtractConfig.zoom})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="also write _debug/ renders showing x_cut, anchors, figures and dividers",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help=(
            "also write review/pNN.webp: each page clean, with nothing drawn on it, as "
            "filed (a scan is not straightened), at review_zoom"
        ),
    )
    parser.add_argument(
        "--table",
        action="store_true",
        help=(
            "read table-format answer PDFs: find each page's column pairs and row "
            "bands, written to tables.json and drawn on the page renders"
        ),
    )
    parser.add_argument(
        "--question-columns",
        type=_column_list,
        default=(),
        help=(
            "with --table: 0-based indices of the columns holding question numbers, "
            "comma-separated (e.g. 0 or 0,2); measured when left out"
        ),
    )
    parser.add_argument(
        "--reading-order",
        choices=(DOWN, ACROSS),
        default=None,
        help="with --table: how the answers read; measured when left out",
    )
    parser.add_argument(
        "--ocr-command",
        type=shlex.split,
        default=None,
        metavar="CMD",
        help=(
            "with --table: the command that runs Tesseract on a scanned table, e.g. "
            "'tesseract' where the binary is installed; defaults to `docker run` of "
            "the pillora-tesseract image"
        ),
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="when the input is a folder, search it recursively",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log debug-level detail",
    )
    return parser


def _column_list(text: str) -> tuple[int, ...]:
    try:
        columns = tuple(int(part) for part in text.split(",") if part.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a comma-separated list of indices")
    if any(c < 0 for c in columns) or list(columns) != sorted(set(columns)):
        raise argparse.ArgumentTypeError(f"{text!r} is not ascending 0-based indices")
    return columns


def find_pdfs(root: Path, recursive: bool) -> list[Path]:
    """PDFs directly in a folder, or anywhere beneath it with ``--recursive``."""
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(message)s",
    )

    config = replace(ExtractConfig(), zoom=args.zoom)
    if args.ocr_command:
        config = replace(config, ocr_command=tuple(args.ocr_command))

    if args.input.is_dir():
        pdfs = find_pdfs(args.input, args.recursive)
        if not pdfs:
            log.error("no PDFs found in %s", args.input)
            return 1
    elif args.input.is_file():
        pdfs = [args.input]
    else:
        log.error("%s does not exist", args.input)
        return 1

    if args.table and args.start_page is not None:
        log.warning("--start-page is ignored with --table: every page is read")
    if not args.table and (args.question_columns or args.reading_order):
        log.warning("--question-columns and --reading-order apply only with --table")
    layout = (
        TableLayout(args.question_columns, args.reading_order)
        if args.question_columns or args.reading_order
        else None
    )

    succeeded: list[PaperResult | TablePaperResult] = []
    failed: list[tuple[Path, str]] = []

    for pdf in pdfs:
        try:
            if args.table:
                succeeded.append(
                    extract_table_paper(
                        pdf,
                        args.output_dir,
                        config,
                        debug=args.debug,
                        layout=layout,
                        review=args.review,
                    )
                )
                continue
            succeeded.append(
                extract_paper(
                    pdf,
                    args.output_dir,
                    config,
                    start_page=args.start_page,
                    debug=args.debug,
                    review=args.review,
                )
            )
        except ExtractionError as exc:
            # One unusable paper must not abandon the rest of a folder.
            log.error("%s", exc)
            failed.append((pdf, str(exc)))
        except Exception as exc:  # pragma: no cover - unexpected, keep the batch alive
            log.exception("%s: unexpected failure (%s)", pdf.name, exc)
            failed.append((pdf, str(exc)))

    _report(succeeded, failed)
    return 1 if failed and not succeeded else 0


def _report(
    succeeded: list[PaperResult | TablePaperResult], failed: list[tuple[Path, str]]
) -> None:
    for result in succeeded:
        review = [page.page for page in result.pages if page.needs_review]
        suffix = f", pages needing review: {review}" if review else ""
        if isinstance(result, TablePaperResult):
            log.info(
                "done %s: %d question(s) from %d row(s), %d warning(s)%s",
                result.paper,
                len(result.questions),
                result.row_count,
                len(result.warnings),
                suffix,
            )
            continue
        log.info(
            "done %s: %d question(s), %d warning(s)%s",
            result.paper,
            len(result.questions),
            len(result.warnings),
            suffix,
        )
    if failed:
        log.warning("%d paper(s) could not be processed", len(failed))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
