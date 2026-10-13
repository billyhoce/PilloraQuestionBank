"""Shared pieces for the worker tests: a file-backed SQLite database (the worker uses several
sessions and threads, which the savepoint-based ``db_session`` fixture cannot serve) and
helpers that make jobs and tasks."""

import os
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.orm import IngestJob, IngestTask, User


def make_session_factory(path):
    """A SQLite file per test; set WORKER_TEST_DATABASE_URL to a *scratch* Postgres database to run
    the same tests there (it is truncated first), which exercises the real FOR UPDATE SKIP LOCKED."""
    url = os.environ.get("WORKER_TEST_DATABASE_URL")
    if url:
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "TRUNCATE ingest_task, worker_heartbeat, ingest_job, app_user RESTART IDENTITY CASCADE"
            )
        return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30}
    )

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _record):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def make_user(factory) -> int:
    with factory() as db:
        user = User(email="admin@test.com", first_name="A", last_name="B", role="admin", password_hash="x")
        db.add(user)
        db.commit()
        return user.id


def make_job(factory, user_id, *, status="queued", filename="RI_2024_Math_P1.pdf", stages=("register",), created_at=None):
    job_id = uuid.uuid4()
    with factory() as db:
        job = IngestJob(
            id=job_id,
            created_by=user_id,
            filename=filename,
            source_key=f"tmp/ingest/{job_id}/source.pdf",
            sha256="0" * 64,
            page_count=1,
            status=status,
        )
        if created_at is not None:
            job.created_at = created_at
        for stage in stages:
            job.tasks.append(IngestTask(section=None, stage=stage, status="ready"))
        db.add(job)
        db.commit()
    return job_id
