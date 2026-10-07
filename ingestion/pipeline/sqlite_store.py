"""The local :class:`~pipeline.store.Store`, over one SQLite file.

The columns mirror the webapp's ``ingest_task`` table so the Postgres store can
follow it one for one. SQLite differences kept inside this module: NULL sections
are unique-checked through ``COALESCE`` in an expression index, timestamps are
ISO-8601 UTC text, ``warnings`` is JSON text, and the claim is one
``BEGIN IMMEDIATE`` transaction (Postgres would use ``FOR UPDATE SKIP LOCKED``).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .outcome import Outcome
from .store import (
    DONE,
    FAILED,
    PENDING,
    READY,
    RUNNING,
    SKIPPED,
    STATUSES,
    Job,
    Task,
    TaskSpec,
)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS job (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingest_task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES job(id),
    section TEXT,
    stage TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ({", ".join(repr(s) for s in STATUSES)})),
    attempts INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    warnings TEXT NOT NULL DEFAULT '[]',
    needs_review INTEGER NOT NULL DEFAULT 0,
    fingerprint TEXT,
    lease_until TEXT,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ingest_task_identity
    ON ingest_task (job_id, COALESCE(section, ''), stage);
CREATE INDEX IF NOT EXISTS ingest_task_status ON ingest_task (status);
"""

_COLUMNS = (
    "id, job_id, section, stage, status, attempts, reason, error, warnings, "
    "needs_review, fingerprint, lease_until, started_at, finished_at, duration_ms"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def _moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        job_id=row["job_id"],
        section=row["section"],
        stage=row["stage"],
        status=row["status"],
        attempts=row["attempts"],
        reason=row["reason"],
        error=row["error"],
        warnings=tuple(json.loads(row["warnings"])),
        needs_review=bool(row["needs_review"]),
        fingerprint=row["fingerprint"],
        lease_until=_moment(row["lease_until"]),
        started_at=_moment(row["started_at"]),
        finished_at=_moment(row["finished_at"]),
        duration_ms=row["duration_ms"],
    )


class SQLiteStore:
    def __init__(
        self, path: Path | str, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._clock = clock
        # Autocommit; transactions are explicit. One connection shared with the
        # runner's heartbeat thread, serialised by the lock. WAL lets another
        # process (`pipeline status`) read while a runner writes.
        self._db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- the runner's loop ------------------------------------------------
    def claim_ready(self, lease_seconds: float) -> Task | None:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT t.id FROM ingest_task t JOIN job j ON j.id = t.job_id "
                    "WHERE t.status = ? ORDER BY j.rowid, t.id LIMIT 1",
                    (READY,),
                ).fetchone()
                if row is None:
                    self._db.execute("COMMIT")
                    return None
                now = self._clock()
                self._db.execute(
                    "UPDATE ingest_task SET status = ?, attempts = attempts + 1, "
                    "reason = '', error = '', warnings = '[]', needs_review = 0, "
                    "started_at = ?, finished_at = NULL, duration_ms = NULL, "
                    "lease_until = ? WHERE id = ?",
                    (
                        RUNNING,
                        _text(now),
                        _text(now + timedelta(seconds=lease_seconds)),
                        row["id"],
                    ),
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            return self._get(row["id"])

    def heartbeat(self, task_id: int, lease_seconds: float) -> bool:
        with self._lock:
            cursor = self._db.execute(
                "UPDATE ingest_task SET lease_until = ? WHERE id = ? AND status = ?",
                (_text(self._clock() + timedelta(seconds=lease_seconds)), task_id, RUNNING),
            )
            return cursor.rowcount == 1

    def complete(self, task_id: int, outcome: Outcome) -> bool:
        if outcome.status not in (DONE, SKIPPED):
            raise ValueError(f"complete() takes done or skipped, not {outcome.status}")
        return self._finish(task_id, outcome)

    def fail(self, task_id: int, outcome: Outcome) -> bool:
        if outcome.status != FAILED:
            raise ValueError(f"fail() takes failed, not {outcome.status}")
        return self._finish(task_id, outcome)

    def _finish(self, task_id: int, outcome: Outcome) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT started_at FROM ingest_task WHERE id = ? AND status = ?",
                (task_id, RUNNING),
            ).fetchone()
            if row is None:
                return False
            now = self._clock()
            started = _moment(row["started_at"])
            duration = int((now - started).total_seconds() * 1000) if started else None
            self._db.execute(
                "UPDATE ingest_task SET status = ?, reason = ?, error = ?, warnings = ?, "
                "needs_review = ?, lease_until = NULL, finished_at = ?, duration_ms = ? "
                "WHERE id = ?",
                (
                    outcome.status,
                    outcome.reason,
                    outcome.error,
                    json.dumps(list(outcome.warnings)),
                    int(outcome.needs_review),
                    _text(now),
                    duration,
                    task_id,
                ),
            )
            return True

    def add_tasks(self, specs: Sequence[TaskSpec]) -> list[Task]:
        created: list[Task] = []
        with self._lock:
            for spec in specs:
                cursor = self._db.execute(
                    "INSERT OR IGNORE INTO ingest_task (job_id, section, stage, status) "
                    "VALUES (?, ?, ?, ?)",
                    (spec.job_id, spec.section, spec.stage, PENDING),
                )
                if cursor.rowcount == 1:
                    created.append(self._get(cursor.lastrowid))
        return created

    def reset_stale(self, retry_limit: int) -> list[Task]:
        with self._lock:
            now = self._clock()
            rows = self._db.execute(
                "SELECT id, attempts FROM ingest_task WHERE status = ? AND lease_until < ?",
                (RUNNING, _text(now)),
            ).fetchall()
            for row in rows:
                if row["attempts"] >= retry_limit:
                    self._db.execute(
                        "UPDATE ingest_task SET status = ?, lease_until = NULL, "
                        "finished_at = ?, needs_review = 1, error = ? WHERE id = ?",
                        (
                            FAILED,
                            _text(now),
                            f"the lease expired on each of {row['attempts']} attempt(s); "
                            "the runner stopped responding",
                            row["id"],
                        ),
                    )
                else:
                    self._db.execute(
                        "UPDATE ingest_task SET status = ?, lease_until = NULL WHERE id = ?",
                        (READY, row["id"]),
                    )
            return [self._get(row["id"]) for row in rows]

    # --- bookkeeping ------------------------------------------------------
    def add_job(self, job_id: str, source: str) -> Job:
        with self._lock:
            self._db.execute(
                "INSERT INTO job (id, source, status, created_at) VALUES (?, ?, 'queued', ?)",
                (job_id, source, _text(self._clock())),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def jobs(self) -> list[Job]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM job ORDER BY rowid").fetchall()
        return [self._job(row) for row in rows]

    def tasks(self, job_id: str | None = None) -> list[Task]:
        query = f"SELECT {_COLUMNS} FROM ingest_task"
        args: tuple = ()
        if job_id is not None:
            query += " WHERE job_id = ?"
            args = (job_id,)
        with self._lock:
            rows = self._db.execute(query + " ORDER BY id", args).fetchall()
        return [_task(row) for row in rows]

    def set_status(self, task_ids: Sequence[int], status: str, reason: str = "") -> None:
        with self._lock:
            for task_id in task_ids:
                self._db.execute(
                    "UPDATE ingest_task SET status = ?, reason = ? WHERE id = ? AND status = ?",
                    (status, reason, task_id, PENDING),
                )

    def set_job_status(self, job_id: str, status: str) -> None:
        with self._lock:
            self._db.execute("UPDATE job SET status = ? WHERE id = ?", (status, job_id))

    def _get(self, task_id: int) -> Task:
        row = self._db.execute(
            f"SELECT {_COLUMNS} FROM ingest_task WHERE id = ?", (task_id,)
        ).fetchone()
        return _task(row)

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            source=row["source"],
            status=row["status"],
            created_at=_moment(row["created_at"]),
        )
