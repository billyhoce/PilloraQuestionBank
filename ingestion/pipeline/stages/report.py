"""``report``: the paper-level ``ingest.json``, written once every section has settled.

Reads what the other stages left (``segments.json``, ``_split/split.json`` and each
section's ``manifest.json``) and the status of every task (:attr:`StageContext.tasks`),
and writes the report ``ingester ingest`` used to write: every section with its label,
range, template, route, status, question count, warnings and review flag, plus the
segment and split stages' own warnings. It is what a human opens to see whether a paper
ingested properly.

It runs after the sections whatever became of them (``after_sections``; ``split`` is a
soft need), so a failed or blocked section is a row in the report, not a reason for none:

* ``extracted`` -- every required task of the section is ``done``; counts, warnings and
  review pages come from its manifest;
* ``not_routed`` -- a required task was ``skipped`` (a scan the question extractor cannot
  crop, an answer section with no template), with that task's reason;
* ``failed`` -- a required task ``failed`` or was ``blocked`` behind one, with its error.

A task that is another stage's soft need (``ocr``) is not required: its failure is
already in the manifest's warnings, as the extractor's own is.

It also writes ``proposal.json`` and the ``pages/`` review images (see
:mod:`pipeline.proposal`): the document the admin review page reads. ``report`` below is
the one place that reads the artefacts, ``_section_report`` the one row.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

from ingester.router import (
    EXTRACTED,
    FAILED,
    NOT_ROUTED,
    SectionReport,
    choose_route,
)
from ingester.segments import SegmentPlan, read_plan
from question_extractor.pipeline import paper_name

from .. import artefacts, proposal
from ..outcome import Outcome, StageContext, TaskSummary, done
from ..registry import CPU, JOB, Stage
from ..sections import load_section

# Job stages whose own verdict is already in the report (segment's in
# ``segment_warnings``, split's in ``split_warnings``); any other failed job
# stage (``register``) is named in ``warnings``.
_SELF_REPORTING = ("segment", "split")


def run(ctx: StageContext) -> Outcome:
    paper = paper_name(ctx.source)
    plan = _read_plan(ctx)
    split = _read_split(ctx)
    warnings: list[str] = []

    sections = []
    for entry in split["sections"]:
        report, section_warnings = _section_report(ctx, paper, entry["label"])
        sections.append(report)
        warnings.extend(section_warnings)

    for task in ctx.tasks:
        if task.section is None and task.status in ("failed", "blocked") and (
            task.stage not in _SELF_REPORTING
        ):
            warnings.append(f"{paper}: {task.stage} {task.status}: {task.detail}")

    segmented = plan is not None and plan.segmented
    needs_review = (
        not segmented or bool(split["skipped"]) or any(r.needs_review for r in sections)
    )
    artefacts.write_json(
        ctx.path(artefacts.REPORT_NAME),
        {
            "pdf": ctx.source.as_posix(),
            "paper": paper,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "segmented": segmented,
            "needs_review": needs_review,
            "sections": [report.entry() for report in sections],
            "split_skipped": split["skipped"],
            "segment_warnings": list(plan.warnings) if plan is not None else [],
            "split_warnings": split["warnings"],
            "warnings": warnings,
        },
    )
    artefacts.write_json(
        ctx.path(artefacts.PROPOSAL_NAME),
        proposal.build(
            ctx.job_dir, plan, split, sections, ctx.config.proposal_tolerance_pt
        ),
    )
    return done(needs_review=needs_review)


def _read_plan(ctx: StageContext) -> SegmentPlan | None:
    path = ctx.path(artefacts.SEGMENTS_NAME)
    return read_plan(path, pdf=ctx.source) if path.is_file() else None


def _read_split(ctx: StageContext) -> dict:
    """``split.json``'s sections, skipped labels and warnings; when ``split`` wrote none
    (it failed, or never ran) there are no sections, and a failed ``split`` skipped every
    section of the plan, as the one-process ``ingest`` recorded."""
    path = ctx.path(artefacts.SPLIT_DIR, artefacts.SPLIT_NAME)
    if path.is_file():
        record = artefacts.read_json(path)
        return {
            "sections": record["sections"],
            "skipped": record["skipped"],
            "warnings": record["warnings"],
        }
    task = next((t for t in ctx.tasks if t.section is None and t.stage == "split"), None)
    plan = _read_plan(ctx)
    ran = task is not None and task.status == "failed"
    return {
        "sections": [],
        "skipped": [s.label for s in plan.segments] if ran and plan is not None else [],
        "warnings": list(task.warnings) if ran else [],
    }


def _section_report(
    ctx: StageContext, paper: str, label: str
) -> tuple[SectionReport, list[str]]:
    """One section's row, and the warnings the one-process router logged for it."""
    section = load_section(replace(ctx, section=label))
    segment = section.segment
    route = choose_route(section)
    base = dict(
        label=label,
        kind=segment.kind,
        template=segment.template,
        first_page=segment.first_page,
        last_page=segment.last_page,
    )
    tasks = [t for t in ctx.tasks if t.section == label and not t.optional]

    broken = _first(tasks, "failed") or _first(tasks, "blocked")
    if broken is not None:
        reason = broken.detail
        return (
            SectionReport(**base, route=route.pipeline, status=FAILED, reason=reason, needs_review=True),
            [f"{paper}: '{label}' failed in {route.pipeline} ({reason})"],
        )

    skipped = _first(tasks, "skipped")
    if skipped is not None:
        warn = [f"{paper}: '{label}' not routed: {skipped.detail}"] if skipped.needs_review else []
        return (
            SectionReport(
                **base,
                route=None,
                status=NOT_ROUTED,
                reason=skipped.detail,
                needs_review=skipped.needs_review or segment.needs_review,
            ),
            warn,
        )

    manifest = ctx.path(label, "manifest.json")
    if not manifest.is_file():
        reason = f"{manifest.name} is missing"
        return (
            SectionReport(**base, route=route.pipeline, status=FAILED, reason=reason, needs_review=True),
            [f"{paper}: '{label}' failed in {route.pipeline} ({reason})"],
        )
    record = json.loads(manifest.read_text(encoding="utf-8"))
    review_pages = tuple(page["original_page"] for page in record["needs_review_pages"])
    return (
        SectionReport(
            **base,
            route=route.pipeline,
            status=EXTRACTED,
            output=label,
            questions=len(record["questions"]),
            warnings=tuple(record["warnings"]),
            needs_review=bool(record["needs_review_pages"]) or segment.needs_review,
            review_pages=review_pages,
        ),
        [],
    )


def _first(tasks: list[TaskSummary], status: str) -> TaskSummary | None:
    return next((t for t in tasks if t.status == status), None)


def _inputs(ctx: StageContext) -> list:
    """What the report is built from: the plan, the split map, every section's manifest and
    how each other task ended (the report says what became of every section)."""
    split = ctx.path(artefacts.SPLIT_DIR, artefacts.SPLIT_NAME)
    manifests = sorted(ctx.job_dir.glob("*/manifest.json")) if ctx.job_dir.is_dir() else []
    ended = sorted(
        repr((t.section, t.stage, t.status, t.detail if t.status != "done" else "",
              t.needs_review, t.warnings))
        for t in ctx.tasks
        if t.stage != STAGE.name
    )
    reviews = sorted(ctx.job_dir.glob("*/review")) if ctx.job_dir.is_dir() else []
    return [ctx.path(artefacts.SEGMENTS_NAME), split, *manifests, *reviews, *ended]


STAGE = Stage(
    name="report",
    scope=JOB,
    kind=CPU,
    run=run,
    soft_needs=("register", "segment", "split"),
    after_sections=True,
    inputs=_inputs,
    settings=lambda ctx: {"proposal_tolerance_pt": ctx.config.proposal_tolerance_pt},
    outputs=lambda ctx: [
        ctx.path(artefacts.REPORT_NAME),
        ctx.path(artefacts.PROPOSAL_NAME),
        ctx.path(proposal.PAGES_DIR),
    ],
    version=3,  # v2: proposal and pages/ are new outputs; v3: unrouted items carry their page range
)
