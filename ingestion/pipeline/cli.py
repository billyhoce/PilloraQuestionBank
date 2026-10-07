"""``python -m pipeline submit|run|status|ingest``."""

from __future__ import annotations

import argparse
import json
import logging
import shlex
import shutil
import sys
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from ingester import IngestConfig
from question_extractor import ExtractConfig
from question_extractor.cli import find_pdfs
from question_extractor.pipeline import paper_name

from . import artefacts
from .config import PipelineConfig
from .registry import default_registry
from .runner import Runner
from .sqlite_store import SQLiteStore
from .store import Store, Task

log = logging.getLogger(__name__)

DB_NAME = "pipeline.db"
_WIDTH = 100  # a reason/error longer than this is cut in `status` (--json has it whole)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="Run booklets through the ingestion stages as tasks in a local queue.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("output/pipeline"),
        help=f"folder holding {DB_NAME} and one folder per job (default: output/pipeline)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log debug-level detail")
    commands = parser.add_subparsers(dest="command", required=True)

    submit = commands.add_parser("submit", help="queue a booklet PDF as a job")
    submit.add_argument("pdf", type=Path, nargs="+", help="the booklet PDF(s)")
    submit.add_argument(
        "--debug",
        action="store_true",
        help="also write each question section's _debug/ renders (review images are always written)",
    )

    run = commands.add_parser("run", help="run queued tasks until none are left")
    run.add_argument("--watch", action="store_true", help="keep polling for new work")
    _add_runner_options(run)

    ingest = commands.add_parser(
        "ingest",
        help="submit every PDF of a file or folder and run them all, writing <paper>/ingest.json",
    )
    ingest.add_argument("input", type=Path, help="a PDF file, or a folder of PDFs")
    ingest.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="root folder for per-paper output folders, <output-dir>/<paper>/ (default: output)",
    )
    ingest.add_argument(
        "--recursive", action="store_true", help="when the input is a folder, search it recursively"
    )
    ingest.add_argument("--debug", action="store_true", help="also write each section's _debug/ renders")
    ingest.add_argument(
        "--review",
        action="store_true",
        help="accepted for `ingester ingest`'s sake; review/pNN.webp images are always written",
    )
    ingest.add_argument(
        "--force",
        action="store_true",
        help="ask the model to segment again even when a plan or fixture is already there",
    )
    _add_runner_options(ingest)

    status = commands.add_parser("status", help="show each job's tasks")
    status.add_argument("job", nargs="?", help="a job id (default: every job)")
    status.add_argument("--json", action="store_true", help="print JSON")
    return parser


def _add_runner_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=None, help=f"default: {IngestConfig.model}")
    parser.add_argument("--retry-model", default=None, help=f"default: {IngestConfig.retry_model}")
    parser.add_argument(
        "--ocr-command",
        type=shlex.split,
        default=None,
        metavar="CMD",
        help=(
            "the command the ocr stage runs Tesseract with on a scanned answer table, e.g. "
            "'tesseract' where the binary is installed; defaults to `docker run` of the "
            "pillora-tesseract image. A run-time setting like --model, not part of the job"
        ),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(message)s",
    )
    if args.command == "ingest":
        return _ingest(args)
    args.root.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(args.root / DB_NAME)
    try:
        if args.command == "submit":
            return _submit(args, store)
        if args.command == "run":
            return _run(args, store)
        return _status(args, store)
    finally:
        store.close()


def _runner(args: argparse.Namespace, store: Store, config: PipelineConfig) -> Runner:
    return Runner(store, default_registry(), lambda job_id: args.root / job_id, config)


def _submit(args: argparse.Namespace, store: Store) -> int:
    runner = _runner(args, store, PipelineConfig())
    missing = [pdf for pdf in args.pdf if not pdf.is_file()]
    for pdf in missing:
        log.error("%s does not exist", pdf)
    for pdf in args.pdf:
        if pdf in missing:
            continue
        job_id = str(uuid.uuid4())
        runner.submit(job_id, pdf.resolve(), debug=args.debug)
        print(f"{job_id}  {pdf.name}")
    return 1 if missing else 0


def _run_config(args: argparse.Namespace) -> PipelineConfig:
    overrides = {
        key: value
        for key, value in (("model", args.model), ("retry_model", args.retry_model))
        if value is not None
    }
    extract = ExtractConfig()
    if args.ocr_command:
        extract = replace(extract, ocr_command=tuple(args.ocr_command))
    return replace(PipelineConfig(), ingest=IngestConfig(**overrides), extract=extract)


def _run(args: argparse.Namespace, store: Store) -> int:
    ran = _runner(args, store, _run_config(args)).run(watch=args.watch)
    log.info("ran %d task(s)", ran)
    return 0


def _ingest(args: argparse.Namespace) -> int:
    """Submit each PDF and run them with one worker; the folder-run replacement for
    ``ingester ingest``.

    Each paper's job folder is ``<output-dir>/<paper>/`` and its job id is the paper name,
    so the tree is the one ``ingester ingest`` wrote (``segments.json``, ``_split/``,
    ``<label>/``, ``ingest.json``) and the router's ``--output-dir`` carries over. The task
    store is a throwaway SQLite file: ``ingest`` is a one-shot batch whose record is the
    folder (``job.json``, ``ingest.json``), and a rerun starts afresh, as it always did. Use
    ``submit`` and ``run`` for a persistent queue. One paper failing does not stop the rest:
    each is its own job, and a failed task blocks only its own dependents.
    """
    if args.input.is_dir():
        pdfs = find_pdfs(args.input, args.recursive)
    elif args.input.is_file():
        pdfs = [args.input]
    else:
        log.error("%s does not exist", args.input)
        return 1
    if not pdfs:
        log.error("no PDFs found in %s", args.input)
        return 1

    papers: dict[str, Path] = {}
    for pdf in pdfs:
        name = paper_name(pdf)
        if name in papers:
            log.warning("%s: same name as %s, which is already queued; skipped", pdf, papers[name])
            continue
        papers[name] = pdf

    output_dir: Path = args.output_dir
    with tempfile.TemporaryDirectory(prefix="pipeline-ingest-") as scratch:
        store = SQLiteStore(Path(scratch) / DB_NAME)
        try:
            runner = Runner(
                store, default_registry(), lambda job_id: output_dir / job_id, _run_config(args)
            )
            for name, pdf in papers.items():
                _clear_previous(output_dir / name)
                runner.submit(name, pdf.resolve(), debug=args.debug, force=args.force)
            runner.run()
        finally:
            store.close()

    processed = 0
    for name in papers:
        report = _read_report(output_dir / name)
        if report is None:
            log.warning("%s: no ingest.json was written", name)
            continue
        if report["segmented"]:
            processed += 1
        sections = ", ".join(
            f"{s['label']} {s['status']}"
            + (f" ({s['questions']} question(s))" if s["status"] == "extracted" else "")
            for s in report["sections"]
        )
        log.info(
            "done %s: %s%s", name, sections or "no sections",
            " - needs review" if report["needs_review"] else "",
        )
    unprocessed = len(papers) - processed
    if unprocessed:
        log.warning("%d paper(s) could not be processed", unprocessed)
    return 1 if processed == 0 else 0


def _clear_previous(paper_dir: Path) -> None:
    """Empty a paper's folder of last run's artefacts, keeping ``segments.json`` (the
    plan a rerun reuses unless ``--force``), so a section that stops being routed leaves
    nothing behind."""
    if not paper_dir.is_dir():
        return
    for entry in paper_dir.iterdir():
        if entry.name == artefacts.SEGMENTS_NAME:
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()


def _read_report(paper_dir: Path) -> dict | None:
    path = paper_dir / artefacts.REPORT_NAME
    return artefacts.read_json(path) if path.is_file() else None


def _seconds(task: Task) -> str:
    return f"{task.duration_ms / 1000:.1f}s" if task.duration_ms is not None else "-"


def _status(args: argparse.Namespace, store: Store) -> int:
    jobs = [store.get_job(args.job)] if args.job else store.jobs()
    if jobs == [None]:
        log.error("no job %s", args.job)
        return 1
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": job.id,
                        "source": job.source,
                        "status": job.status,
                        "tasks": [
                            {
                                "section": t.section,
                                "stage": t.stage,
                                "status": t.status,
                                "attempts": t.attempts,
                                "duration_ms": t.duration_ms,
                                "needs_review": t.needs_review,
                                "reason": t.reason,
                                "error": t.error,
                                "warnings": list(t.warnings),
                            }
                            for t in store.tasks(job.id)
                        ],
                    }
                    for job in jobs
                ],
                indent=2,
            )
        )
        return 0
    for job in jobs:
        print(f"{job.id}  {Path(job.source).name}  [{job.status}]")
        for task in store.tasks(job.id):
            name = f"{task.stage}" + (f" {task.section}" if task.section else "")
            line = f"  {name:<18} {task.status:<8} {_seconds(task):>7}"
            if task.needs_review:
                line += "  needs review"
            if task.warnings:
                line += f"  {len(task.warnings)} warning(s)"
            if task.reason or task.error:
                text = task.reason or task.error
                line += f"  {text if len(text) <= _WIDTH else text[: _WIDTH - 1] + '…'}"
            print(line)
            for warning in task.warnings:
                print(f"      ! {warning}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
