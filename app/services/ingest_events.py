"""Append rows to ``ingest_event``, the audit trail of an ingest job.

Every call adds to the caller's session and never commits: the event lands in the same
transaction as the state change it describes. Kinds: ``created``, ``task_claimed``,
``task_finished`` (``status`` done/skipped/failed), ``retry``, ``cancelled``,
``proposal_edited``, ``paper_confirmed``, ``paper_skipped``, ``paper_deleted``, ``reconcile`` (a
reconciler finding; ``job_id`` is NULL when the finding has no job). (``expired`` appears only on historical rows.)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.orm import IngestEvent


def add_event(
    db: Session,
    job_id: uuid.UUID | None,
    kind: str,
    *,
    task_id: int | None = None,
    actor_user_id: int | None = None,
    at: datetime | None = None,
    **data: Any,
) -> IngestEvent:
    event = IngestEvent(job_id=job_id, task_id=task_id, kind=kind, actor_user_id=actor_user_id, data=data)
    if at is not None:
        event.at = at
    db.add(event)
    return event
