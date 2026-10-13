"""Segments, the plan that holds them, and ``segments.json``."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SEGMENTS_NAME = "segments.json"

KIND_PREFIXES = {"question": "q", "answer": "a"}
PREFIX_KINDS = {prefix: kind for kind, prefix in KIND_PREFIXES.items()}

# An answer section's shape; question sections carry none.
TEMPLATES = ("table", "annotated_booklet")

# How a `table` section's answers run when it has more than one column pair:
# down each pair before the next, or across the pairs row by row.
READING_ORDERS = ("down", "across")

# No leading zeros, so each label has exactly one spelling.
LABEL_RE = re.compile(r"^([qa])([1-9][0-9]*)$")

SOURCE_MODEL = "model"
SOURCE_HAND = "hand"


def format_label(kind: str, index: int) -> str:
    return f"{KIND_PREFIXES[kind]}{index}"


def parse_label(label: str) -> tuple[str, int] | None:
    match = LABEL_RE.match(label.strip()) if isinstance(label, str) else None
    if match is None:
        return None
    return PREFIX_KINDS[match.group(1)], int(match.group(2))


@dataclass(frozen=True)
class Segment:
    """A labelled page range; pages are 1-based PDF positions, inclusive."""

    label: str
    kind: str
    index: int
    first_page: int
    last_page: int
    note: str = ""
    template: str | None = None
    needs_review: bool = False
    # `table` sections only: 0-based indices of the printed columns holding
    # question numbers, and the reading order. A hint the table reader checks
    # against the page, not a measurement; empty/None when not given.
    question_columns: tuple[int, ...] = ()
    reading_order: str | None = None

    @property
    def pages(self) -> list[int]:
        return list(range(self.first_page, self.last_page + 1))

    @property
    def page_count(self) -> int:
        return self.last_page - self.first_page + 1

    def entry(self) -> dict:
        return {
            "label": self.label,
            "kind": self.kind,
            "index": self.index,
            "first_page": self.first_page,
            "last_page": self.last_page,
            "note": self.note,
            "template": self.template,
            "needs_review": self.needs_review,
            "question_columns": list(self.question_columns),
            "reading_order": self.reading_order,
        }

    @classmethod
    def from_entry(cls, entry: dict) -> "Segment":
        return cls(
            label=entry["label"],
            kind=entry["kind"],
            index=entry["index"],
            first_page=entry["first_page"],
            last_page=entry["last_page"],
            note=entry.get("note", ""),
            template=entry.get("template"),
            needs_review=entry.get("needs_review", False),
            question_columns=tuple(entry.get("question_columns") or ()),
            reading_order=entry.get("reading_order"),
        )


@dataclass(frozen=True)
class Attempt:
    """One request to one model, and whether its answer was accepted."""

    model: str
    accepted: bool
    problems: tuple[str, ...] = ()

    def entry(self) -> dict:
        return {
            "model": self.model,
            "accepted": self.accepted,
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class SegmentPlan:
    pdf: Path
    paper: str
    page_count: int
    segments: tuple[Segment, ...] = ()
    model: str | None = None  # the model whose answer was accepted
    source: str = SOURCE_MODEL
    attempts: tuple[Attempt, ...] = ()
    warnings: tuple[str, ...] = ()
    config: dict | None = None
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def segmented(self) -> bool:
        return bool(self.segments)

    @property
    def retried(self) -> bool:
        return len(self.attempts) > 1

    def of_kind(self, kind: str) -> list[Segment]:
        return [segment for segment in self.segments if segment.kind == kind]

    def entry(self) -> dict:
        return {
            # POSIX separators so fixtures don't differ by platform.
            "pdf": Path(self.pdf).as_posix(),
            "paper": self.paper,
            "page_count": self.page_count,
            "generated_at": self.generated_at,
            "source": self.source,
            "model": self.model,
            "retried": self.retried,
            "segmented": self.segmented,
            "segments": [segment.entry() for segment in self.segments],
            "attempts": [attempt.entry() for attempt in self.attempts],
            "warnings": list(self.warnings),
            "config": self.config,
        }

    @classmethod
    def from_entry(cls, entry: dict, pdf: Path | None = None) -> "SegmentPlan":
        """``pdf`` overrides the recorded path with where the PDF is now."""
        return cls(
            pdf=pdf if pdf is not None else Path(entry["pdf"]),
            paper=entry["paper"],
            page_count=entry["page_count"],
            segments=tuple(Segment.from_entry(item) for item in entry["segments"]),
            model=entry.get("model"),
            source=entry.get("source", SOURCE_MODEL),
            attempts=tuple(
                Attempt(
                    model=item["model"],
                    accepted=item["accepted"],
                    problems=tuple(item.get("problems", ())),
                )
                for item in entry.get("attempts", ())
            ),
            warnings=tuple(entry.get("warnings", ())),
            config=entry.get("config"),
            generated_at=entry.get("generated_at", ""),
        )


def write_plan_to(plan: SegmentPlan, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write beside, then rename: a reader (or a crash) never sees half a plan.
    partial = path.with_name(path.name + ".tmp")
    partial.write_text(json.dumps(plan.entry(), indent=2) + "\n", encoding="utf-8")
    os.replace(partial, path)
    return path


def write_plan(plan: SegmentPlan, out_dir: Path) -> Path:
    return write_plan_to(plan, out_dir / SEGMENTS_NAME)


def read_plan(path: Path, pdf: Path | None = None) -> SegmentPlan:
    return SegmentPlan.from_entry(json.loads(path.read_text(encoding="utf-8")), pdf=pdf)
