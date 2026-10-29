# 0003. Ingest jobs: Postgres queue, direct-to-S3 upload, keep until settled

Status: accepted

## Context

Auto import originally uploaded through the API, stored job files under `tmp/` (where a 7-day
bucket lifecycle rule could delete a pending job's files), expired unreviewed jobs after 7 days,
and lost worker logs on redeploy. Admins review papers on their own schedule, so a pending job
must not lose its inputs.

## Decision

- **Postgres is the queue.** Tasks are claimed with `FOR UPDATE SKIP LOCKED`, leases and
  heartbeats (the Solid Queue / Oban / pg-boss pattern). A job is enqueued in the same transaction
  that creates it, with no extra infrastructure. Redis/Celery or SQS would add infrastructure plus
  an outbox; Kafka is an event log, not a job queue. Revisit only at thousands of jobs/s or with
  many independent consumers.
- **Browser uploads straight to S3** with a presigned POST (PDF only, ≤ 100 MB, 15-minute expiry);
  the API never holds the file. The job exists before the bytes move, so it is traceable from the
  start. PDF validation (page count, password) runs in the `register` stage and fails the job with a
  reason instead of rejecting the request.
- **Keep a job until it is settled** (every paper confirmed, skipped or attached, or the job
  cancelled). No auto-expiry; the job list shows an age badge instead.
- **Separate S3 prefix.** Job files live under `ingest/{job_id}/` with no lifecycle rule; `tmp/`
  holds only throwaway files and expires after 2 days. Settling deletes the whole job prefix, so
  "settled ⇒ prefix empty" is an invariant.
- **A small debug bundle survives** on the job row (`segments.json`, `ingest.json`, the proposal);
  `ingest_job` / `ingest_task` / `ingest_event` rows are kept indefinitely as the audit trail.
- **Worker scratch is a cache.** Deleted once the report is stored; kept for a failed job so Retry
  re-runs only what failed; rebuilt from the S3 source if lost.
- **A daily reconciler** cleans what the happy path missed (orphan prefixes, stale `tmp/`, orphan
  scratch and paper images, stuck jobs, abandoned uploads). It reports first and deletes only when
  `INGEST_RECONCILE_DELETE=true`.

## Consequences

- Pending jobs cost S3 storage until an admin settles them.
- The S3 lifecycle rule is a backstop only; correctness depends on settle-time deletes and the
  reconciler.
- The bucket needs a CORS rule allowing POST from the app origin (see DEPLOYMENT.md).
