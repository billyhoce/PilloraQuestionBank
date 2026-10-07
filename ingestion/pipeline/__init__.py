"""Run a booklet as a job of small, file-based stages. See pipeline/README.md."""

from __future__ import annotations

from .config import PipelineConfig
from .outcome import Outcome, StageContext, done, failed, skipped
from .registry import Registry, Stage, default_registry
from .runner import Runner, settle
from .sqlite_store import SQLiteStore
from .store import Job, Store, Task, TaskSpec

__all__ = [
    "Job",
    "Outcome",
    "PipelineConfig",
    "Registry",
    "Runner",
    "SQLiteStore",
    "Stage",
    "StageContext",
    "Store",
    "Task",
    "TaskSpec",
    "default_registry",
    "done",
    "failed",
    "settle",
    "skipped",
]
