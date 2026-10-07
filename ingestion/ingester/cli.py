"""``python -m ingester segment|split|ingest <pdf|folder>``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from question_extractor import ExtractConfig
from question_extractor.cli import find_pdfs

from .config import IngestConfig
from .router import EXTRACTED, IngestResult, ingest_paper
from .segments import SegmentPlan
from .segmenter import segment_paper
from .splitter import SplitResult, split_paper

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ingester",
        description=(
            "Read an exam-paper PDF with a vision model and record what is in it."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    segment = subparsers.add_parser(
        "segment",
        help="find the question and answer papers in a PDF and write segments.json",
    )
    segment.add_argument("input", type=Path, help="a PDF file, or a folder of PDFs")
    segment.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="root folder for per-paper output folders (default: output)",
    )
    segment.add_argument(
        "--force",
        action="store_true",
        help=(
            "ask the model again even when a segments.json or a committed fixture "
            "already exists"
        ),
    )
    segment.add_argument(
        "--write-fixture",
        action="store_true",
        help=(
            "also write the result beside the PDF as <paper>.segments.json, the "
            "committed fixture later runs reuse"
        ),
    )
    segment.add_argument(
        "--model",
        default=None,
        help=f"model asked first (default: {IngestConfig.model})",
    )
    segment.add_argument(
        "--retry-model",
        default=None,
        help=(
            "model asked again when the first answer fails validation "
            f"(default: {IngestConfig.retry_model})"
        ),
    )
    segment.add_argument(
        "--recursive",
        action="store_true",
        help="when the input is a folder, search it recursively",
    )
    segment.add_argument(
        "-v", "--verbose", action="store_true", help="log debug-level detail"
    )

    split = subparsers.add_parser(
        "split",
        help="write one PDF per section of segments.json, with its page map",
    )
    split.add_argument("input", type=Path, help="a PDF file, or a folder of PDFs")
    split.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="root folder for per-paper output folders (default: output)",
    )
    split.add_argument(
        "--recursive",
        action="store_true",
        help="when the input is a folder, search it recursively",
    )
    split.add_argument(
        "-v", "--verbose", action="store_true", help="log debug-level detail"
    )

    ingest = subparsers.add_parser(
        "ingest",
        help=(
            "segment, split and route each section to its extractor, writing "
            "ingest.json"
        ),
    )
    ingest.add_argument("input", type=Path, help="a PDF file, or a folder of PDFs")
    ingest.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="root folder for per-paper output folders (default: output)",
    )
    ingest.add_argument(
        "--force",
        action="store_true",
        help="ask the model to segment again even when a plan is already on disk",
    )
    ingest.add_argument(
        "--model",
        default=None,
        help=f"model asked first (default: {IngestConfig.model})",
    )
    ingest.add_argument(
        "--retry-model",
        default=None,
        help=(
            "model asked again when the first answer fails validation "
            f"(default: {IngestConfig.retry_model})"
        ),
    )
    ingest.add_argument(
        "--debug",
        action="store_true",
        help="also write each section's _debug/ renders",
    )
    ingest.add_argument(
        "--review",
        action="store_true",
        help="also write each section's clean review/pNN.webp page images",
    )
    ingest.add_argument(
        "--recursive",
        action="store_true",
        help="when the input is a folder, search it recursively",
    )
    ingest.add_argument(
        "-v", "--verbose", action="store_true", help="log debug-level detail"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(message)s",
    )
    pdfs = _find_inputs(args.input, args.recursive)
    if pdfs is None:
        return 1
    if args.command == "split":
        return _split_command(args, pdfs)
    if args.command == "ingest":
        return _ingest_command(args, pdfs)
    return _segment_command(args, pdfs)


def _find_inputs(path: Path, recursive: bool) -> list[Path] | None:
    if path.is_dir():
        pdfs = find_pdfs(path, recursive)
        if not pdfs:
            log.error("no PDFs found in %s", path)
            return None
        return pdfs
    if path.is_file():
        return [path]
    log.error("%s does not exist", path)
    return None


def _ingest_config(args: argparse.Namespace) -> IngestConfig:
    return IngestConfig(
        **{
            key: value
            for key, value in (
                ("model", args.model),
                ("retry_model", args.retry_model),
            )
            if value is not None
        }
    )


def _segment_command(args: argparse.Namespace, pdfs: list[Path]) -> int:
    config = _ingest_config(args)

    plans: list[SegmentPlan] = []
    failed: list[tuple[Path, str]] = []
    for pdf in pdfs:
        try:
            plans.append(
                segment_paper(
                    pdf,
                    args.output_dir,
                    config,
                    force=args.force,
                    write_fixture=args.write_fixture,
                )
            )
        except Exception as exc:  # pragma: no cover - keep a folder run alive
            log.exception("%s: unexpected failure (%s)", pdf.name, exc)
            failed.append((pdf, str(exc)))

    _report(plans, failed)
    return 1 if failed and not plans else 0


def _report(plans: list[SegmentPlan], failed: list[tuple[Path, str]]) -> None:
    for plan in plans:
        labels = ", ".join(
            f"{segment.label} p{segment.first_page}-{segment.last_page}"
            for segment in plan.segments
        )
        log.info(
            "done %s: %s%s",
            plan.paper,
            labels or "no sections",
            f" ({len(plan.warnings)} warning(s))" if plan.warnings else "",
        )
    unsegmented = [plan.paper for plan in plans if not plan.segmented]
    if unsegmented:
        log.warning("%d paper(s) produced no sections: %s", len(unsegmented), unsegmented)
    if failed:
        log.warning("%d paper(s) could not be processed", len(failed))


def _split_command(args: argparse.Namespace, pdfs: list[Path]) -> int:
    results: list[SplitResult] = []
    failed: list[Path] = []
    for pdf in pdfs:
        try:
            results.append(split_paper(pdf, args.output_dir))
        except Exception as exc:  # pragma: no cover - keep a folder run alive
            log.exception("%s: unexpected failure (%s)", pdf.name, exc)
            failed.append(pdf)

    for result in results:
        log.info(
            "done %s: %s%s",
            result.paper,
            ", ".join(section.segment.label for section in result.sections)
            or "no sections",
            f" (skipped {', '.join(result.skipped)})" if result.skipped else "",
        )
    if failed:
        log.warning("%d paper(s) could not be processed", len(failed))
    return 1 if failed and not results else 0



def _ingest_command(args: argparse.Namespace, pdfs: list[Path]) -> int:
    config = _ingest_config(args)
    results: list[IngestResult] = []
    failed: list[Path] = []
    for pdf in pdfs:
        try:
            results.append(
                ingest_paper(
                    pdf,
                    args.output_dir,
                    config,
                    ExtractConfig(),
                    force=args.force,
                    debug=args.debug,
                    review=args.review,
                )
            )
        except Exception as exc:  # pragma: no cover - keep a folder run alive
            log.exception("%s: unexpected failure (%s)", pdf.name, exc)
            failed.append(pdf)

    for result in results:
        sections = ", ".join(
            f"{section.label} {section.status}"
            + (f" ({section.questions} question(s))" if section.status == EXTRACTED else "")
            for section in result.sections
        )
        log.info(
            "done %s: %s%s",
            result.paper,
            sections or "no sections",
            " - needs review" if result.needs_review else "",
        )
    if failed:
        log.warning("%d paper(s) could not be processed", len(failed))
    return 1 if failed and not results else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
