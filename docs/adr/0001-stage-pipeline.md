# 0001. Ingest a booklet as a job of file-based stages in a task store

Status: accepted

## Context

`ingester ingest` runs a booklet start to finish in one process: segment (a vision-model call),
split, then each section through an extractor (some of which shell out to a Tesseract container).
That is fine from a terminal and wrong for the webapp, which needs to show progress, survive a
restart, retry only what failed, let the admin edit an intermediate result, and run several
booklets on a 1 OCPU / 6 GB VM without a request holding a worker for minutes.

## Decision

Run a booklet as a **job** of small **stages**, each recorded as a **task** in a **store**.

- A stage is `run(ctx) -> outcome` (`done`, `skipped(reason)` or `failed(error)`, plus
  `needs_review` and `warnings`). Its input and output are **artefacts**: files under the job's
  folder, written atomically. Nothing is handed over in memory.
- Stage boundaries go where an external dependency lives (the Messages API, Tesseract), where a
  human may edit the artefact before the next stage reads it, or where work is costly and
  separately useful. Everything finer stays a function call.
- A **registry** declares each stage's name, scope (job or section), kind (cpu, api,
  subprocess), dependencies and fan-out. A fan-out stage (`split`) reports its sections and the
  runner creates a task per section for every section stage.
- The **store** is a Protocol (`claim_ready`, `heartbeat`, `complete`, `fail`, `add_tasks`,
  `reset_stale`, plus job and task reads). Task identity is `(job_id, section, stage)` and
  `add_tasks` is idempotent on it. The package ships a SQLite implementation for the local CLI
  (`pipeline submit|run|status`); the webapp implements the same Protocol with SQLAlchemy over
  Postgres (`SELECT ... FOR UPDATE SKIP LOCKED` for the claim) and runs the stages through the same
  runner in a scratch directory.
- **One runner loop**: claim, run, record, expand fan-out. A stage that raises is recorded as
  `failed`. Dependencies live in the registry: when a task finishes the runner promotes
  dependents to `ready`, marks those downstream of a failure `blocked`, and those downstream of a
  skip `skipped`. Other jobs are untouched.
- Leases and heartbeats cover a runner that dies mid-task: a task whose lease lapses is made
  ready again until it has used its retry limit. Thresholds live in `PipelineConfig`.

## Consequences

- The local CLI and the webapp run the same stage code; only the store and the job folder
  resolver differ.
- Every intermediate result is an inspectable, editable file, and a rerun can start at any stage.
- The queue is the source of truth for progress, so a status page is a query, not instrumentation.
- Costs: more moving parts than one function call; a Postgres `ingest_task` table whose unique
  key on a nullable `section` needs `NULLS NOT DISTINCT`; promoting dependents is a read-then-write
  per finished task, exact for one runner and caught up on the next pass when several finish
  siblings at once.

## Alternatives considered

- **A job queue library (Celery, RQ, Dramatiq).** Needs a broker the free-tier VM would also
  have to run, and gives no per-stage record for the status page without building one anyway.
- **Keep `ingester ingest` and run it in a background thread.** No progress, no partial retry,
  no editing step, and a restart loses the job.
- **In-memory hand-off between stages.** Cheaper, but ties stages to one process and hides the
  intermediates from the admin.
