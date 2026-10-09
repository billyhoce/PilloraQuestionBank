# Plan: ingest hardening, traceability, retention and question/answer pairing

Status: **proposed** — nothing here is implemented yet. Written 2026-10-09 from a code trace of the
auto-import flow (`app/routes/ingest.py`, `app/services/ingest*.py`, `app/worker/`, `ingestion/`).
When a phase ships, move the facts it establishes into the owning feature doc
([features/ingestion.md](../features/ingestion.md), [features/ai-labelling.md](../features/ai-labelling.md),
[DEPLOYMENT.md](../DEPLOYMENT.md), [DATA_MODEL.md](../DATA_MODEL.md)) and tick it off here.

## Contents

- [Where things stand](#where-things-stand)
- [Decisions already made](#decisions-already-made)
- [Phase 0 — Bug fixes](#phase-0--bug-fixes)
- [Phase 1 — Trace one PDF by its job id](#phase-1--trace-one-pdf-by-its-job-id)
- [Phase 2 — Retention and cleanup](#phase-2--retention-and-cleanup)
- [Phase 3 — Direct-to-S3 upload](#phase-3--direct-to-s3-upload)
- [Phase 4 — Question/answer booklet pairing](#phase-4--questionanswer-booklet-pairing)
- [Verification rules](#verification-rules)
- [Open questions](#open-questions)

## Where things stand

- **Trigger.** The admin uploads on `/admin/import` (Auto-detect tab). Each file becomes one
  `POST /api/import/jobs`, which creates one `ingest_job` row plus a `register` task, and stores the
  PDF at `tmp/ingest/{job_id}/source.pdf`.
  - The `worker` container (`python -m app.worker`) claims tasks from Postgres with
    `FOR UPDATE SKIP LOCKED` and leases.
  - It runs the `ingestion/pipeline` stages on a local scratch folder.
  - It uploads the review images to S3 and writes the proposal to the job row.
  - The admin then reviews, confirms or skips each paper on `ReviewPage.jsx`.
- **Storage.**
  - **S3:** `tmp/ingest/{id}/source.pdf` and `tmp/ingest/{id}/pages/*.webp`.
  - **Scratch:** every pipeline artefact, under `/tmp/ingest/{id}/` in the worker container. It has
    no volume.
  - **Confirm:** writes crops to `tmp/{uuid}/page_n.webp`, which are then copied to
    `papers/{paper_id}/q{n}/{type}_{order}.webp`.
- **Retention today.**
  - The daily sweep expires `review_ready` / `failed` jobs 7 days after `updated_at` and deletes their
    S3 prefix and scratch folder.
  - A bucket lifecycle rule deletes everything under `tmp/` 7 days after creation. That can fire
    before the sweep, and it never covers `queued` / `running` jobs.
  - `ingest_job` and `ingest_task` rows are never deleted.
- **Pairing.**
  - A question-only booklet works. Its papers have question pages only and raise no warning.
  - Two separate uploads (questions + answers) become two unrelated jobs. The answer-only job's
    rectangles end up as numberless `orphan_answers`, and confirming it returns 422, so the answers are
    lost.
  - The metadata extractor reads only the filename. It returns no `stream`, and it runs once per job,
    before segmentation.
  - The `paper` table has **no unique constraint** beyond its primary key, in the ORM
    (`app/models/orm.py:197-224`) or in any migration.
- **Logging.**
  - The job UUID already reaches `paper.source_job_id`, but almost no log line carries it.
  - The API logs to an in-container file with no volume, so those logs are lost on redeploy.
  - Stage tracebacks are logged only at DEBUG.
  - Task rows hold current state only, with no history.

## Decisions already made

| Topic | Decision |
|---|---|
| Job queue | **Keep Postgres as the queue** (`SELECT … FOR UPDATE SKIP LOCKED`, leases, heartbeats). This is the same pattern as Solid Queue, Oban, River, pg-boss and Procrastinate. It enqueues in the same transaction that creates the job and needs no extra infrastructure. Kafka is an event log, not a job queue. Redis/Celery or SQS would add infrastructure plus an outbox to keep the DB and queue consistent. Revisit only at thousands of jobs/s or when there are many independent consumers. |
| Upload path | Move to **presigned direct-to-S3 uploads** ([Phase 3](#phase-3--direct-to-s3-upload)). The blocking-route bug is fixed first ([B2](#b2-the-upload-route-blocks-the-event-loop)). |
| Retention of unconfirmed jobs | **Keep until settled.** No auto-expiry for `review_ready` / `failed`; the job list shows an age badge instead. |
| Protecting pending files from S3 lifecycle | **Separate prefix.** Job data lives under `ingest/{job_id}/`, which has no lifecycle rule. `tmp/` keeps a short expiry and holds only throwaway files. |
| What survives a settled job | **A small debug bundle**: `segments.json`, `ingest.json` and the proposal, a few KB. It is kept on the `ingest_job` row. Everything under `ingest/{job_id}/` is deleted. |
| Scratch folder | Treated as a **cache**. It is deleted at `review_ready`, and kept for `failed` jobs so Retry re-runs only the failed tasks. |
| Reconciler | Runs **report-only first**. Deleting is turned on with `INGEST_RECONCILE_DELETE=true` once its reports look right. |
| Cover pages | Come from the **existing segment call** (an extra field). No second VLM call. |
| Matching key | All seven paper fields: `school_id, year, level_id, subject_id, exam_type_id, stream_id, paper_number`. School + year + paper number alone is ambiguous. |

---

## Phase 0 — Bug fixes

One small PR. Each fix comes with a regression test.

### B1. `del img` in `confirm_import` cleanup

- **Where:** `app/services/ingest.py:166-170`.
- **Bug:** after the commit, a failed temp-key delete runs `except Exception: del img`. `img` is
  undefined, so it raises `UnboundLocalError` / `NameError`.
- **Effect:**
  - The admin gets a 500 even though the paper was committed.
  - The remaining temp keys leak.
  - In the auto flow, `_record` is never reached, so the job still shows the paper as open. Clicking
    **Confirm** again creates a **duplicate paper**.
- **Fix:** log the failed key, e.g. `log.warning(..., temp_key)`, and continue. The `tmp/` lifecycle
  rule (and, after Phase 2, the reconciler) removes the leftover.
- **Test:** add a test in `tests/test_ingest.py` where `delete_object` raises for the temp key. It
  asserts that the paper is returned, no exception escapes and the other temp keys are still deleted.

### B1b. Make auto-confirm atomic

This is the same failure family as B1.

- **Where:** `app/services/ingest_confirm.py:166-171`.
- **Bug:** `confirm_import` commits the paper first. Only afterwards are `paper.source_job_id` and
  `_record(...)` set and committed, in a second transaction. A crash between the two leaves an
  unlinked paper and an "open" proposal paper, so confirming again duplicates it.
- **Fix:** give `confirm_import` a way to defer the commit, or have it accept `source_job_id` plus a
  pre-commit callback. The paper insert, `source_job_id` and `_record` then commit in one transaction,
  with S3 copies before the commit and temp deletes after it, as today.
- **Test:** make the `_record` step fail and assert that no paper row exists afterwards.

### B2. The upload route blocks the event loop

- **Where:** `app/routes/ingest.py:386-400`.
- **Bug:** `create_ingest_job` is `async def`, but `create_job` does blocking work: PyMuPDF
  validation, a boto3 `put` of the whole PDF and a synchronous DB commit. Uvicorn runs a single worker
  (`Dockerfile:46`), so one large upload stalls **every** API request until S3 returns.
- **Fix:** change the route to a plain `def` (FastAPI runs it in its thread pool) and read the file
  with `file.file.read()`. Check the other `async def` routes in `app/routes/ingest.py` (for example
  `upload-pdf`) for the same pattern.
- **Test:** existing route tests keep passing. Optionally add a test that a slow fake store doesn't
  block a concurrent `GET /api/health`.
- Phase 3 makes this route obsolete, but the fix is one line and removes the stall now.

---

## Phase 1 — Trace one PDF by its job id

**Goal:** given a job UUID, which the admin can see in the UI, show every log line, task attempt,
Claude call and resulting paper for it.

### 1.1 Stamp context on every log record

- Add `app/log_context.py` (a contextvar holding `job_id`, `section`, `stage`, `task_attempt`) and a
  `logging.Filter` that copies it onto each record.
- In the worker, set it around each claimed task. The task is known in `Runner.run_one` (`claim_ready`
  returns it). Either:
  - give the runner an `on_task_start` / `on_task_end` hook that `app/worker` fills in, or
  - set the contextvar in `ingestion/pipeline/runner.py` itself, next to the existing
    `collect_warnings()` scope (`runner.py:272`, `question_extractor/warnscope.py`).

  The second option is simpler and keeps `ingestion/` free of `app` imports.
- Add `task.job_id` to the runner's own lines (`runner.py:167,182,282,283,399`) so the CLI output is
  traceable too.
- In the API, set `job_id` in the job routes (`/jobs/{id}/…`) and add a request-id middleware: an
  `X-Request-ID` header is generated if absent, echoed in the response and put on every record.

### 1.2 One log format, to stdout, in both containers

- Replace the file handler in `app/logger.py` with a stdout handler and a **JSON formatter**
  (`python-json-logger`, or a ~20-line formatter). Fields: `ts, level, logger, msg, job_id, section,
  stage, request_id, user_id`.
- Configure the **root** logger once (`app/logging_setup.py`), called from `app/main.py` and
  `app/worker/main.py`, so `app.*`, `pipeline.*`, `ingester.*` and `question_extractor.*` all reach the
  handler. Today module-named loggers in the API get no handler below WARNING.
- Keep the existing `Timer` / `log_tokens` helpers but emit structured fields instead of hand-padded
  pipe tables.
- In `deploy/docker-compose.prod.yml`, set the `json-file` driver with `max-size` / `max-file` for
  `api` and `worker`, so `docker logs` holds a bounded, greppable history across restarts. A hosted log
  sink is optional and out of scope.

### 1.3 Log the lifecycle events that are silent today

At INFO, with `job_id`: job created (filename, size, sha256, page count, user), task claimed, task
finished (status, duration), proposal saved, paper confirmed (paper id), paper skipped, retry, cancel,
expired, reconciler finding.

### 1.4 Keep tracebacks

- In `runner.py:262,276`, log the exception at ERROR with `exc_info` instead of
  `log.debug(traceback.format_exc())`.
- Store a truncated traceback (e.g. the last 4 KB) in a new `ingest_task.traceback` column so the UI
  can show it.

### 1.5 Task attempt history

- New table `ingest_event(id, job_id FK, task_id NULL, at, kind, actor_user_id NULL, data JSONB)`.
- Append a row on job created, task claimed, task finished/failed (status, error, warnings, duration),
  retry, cancel, proposal edited, paper confirmed/skipped, expired, reconciler action.
- This replaces "current state only": `claim_ready` / `reopen` can keep overwriting the task row
  because the history lives here.
- Add an Alembic migration, and update [DATA_MODEL.md](../DATA_MODEL.md).

### 1.6 Claude-call traceability and cost

- In `ingestion/ingester/request.py`, pass the response's request id (`response._request_id` /
  `response.id`) to `usage_listener` along with model and usage.
- In the worker listener, log it with the job context and add the token counts and cost to a per-job
  total in `job.report["cost"]`.
- Do the same for the filename/cover metadata call.

### 1.7 Provenance from question back to source

- Store `section` and `proposal_question_index` on each `question`, plus the source page and rectangle
  on each `question_page`, all nullable. This is where a confirmed question came from inside the PDF.
- Show the job id in `JobDetail.jsx` with a copy button. Add an admin-only `GET /api/import/jobs`
  filter by job id / paper id and an "all admins" view. Today `_get_own_job` scopes jobs to their
  creator.

### Tests

- pytest for the log filter (context fields appear on records emitted inside a task scope).
- pytest for `ingest_event` rows written per transition.
- pytest for `job.report["cost"]` accumulation.
- Vitest for the job id shown in `JobDetail`.

---

## Phase 2 — Retention and cleanup

**Principle:** S3 and the DB are the durable state of a pending job, and scratch is a cache. The job's
inputs are kept until the job is **settled** (`confirmed`, `cancelled`). They are deleted when the job
settles. A daily **reconciler** compares the DB with S3 and disk and cleans whatever the happy path
missed. The S3 lifecycle rule stays only as a backstop for genuinely throwaway files.

### 2.1 New S3 layout

| Prefix | Holds | Lifecycle rule |
|---|---|---|
| `ingest/{job_id}/source.pdf` | uploaded source | **none** |
| `ingest/{job_id}/pages/pNN.webp` | review images | **none** |
| `tmp/{uuid}/…` | manual-import pages, confirm crops, page-edit replacements | expire after **2 days** (was 7) |
| `papers/{paper_id}/…` | stored question images | none (versioning keeps deletes 30 days) |

- `source_key_for` / `job_prefix` (`app/services/ingest_jobs.py:38-43`) return `ingest/{id}/…`.
- **Jobs already in flight** under `tmp/ingest/` must keep working. Make every reader use the stored
  `job.source_key`, and derive the job prefix from it with `source_key.rsplit("/", 1)[0] + "/"` rather
  than rebuilding it from the id. Touch `_drop_job_objects`, `cancel_job`, the sweep, `after_report`'s
  page upload and `build_review`'s presign.
- Update `docs/DEPLOYMENT.md`'s lifecycle step: the `tmp/` rule shortens to 2 days, and there is
  explicitly **no** rule on `ingest/`. Applying it is a one-time manual step.

### 2.2 No auto-expiry for pending jobs

- In `app/worker/sweep.py`, drop `review_ready` / `failed` from `expire_stale_jobs`. Keep the
  `expired` status value for historical rows; don't delete it from the enum.
- In `AutoImport.jsx`, show an age badge ("waiting 12 days") from `created_at`, highlighted past
  14 days, and a filter "Awaiting review".

### 2.3 Scratch as a cache

- After the report stage succeeds, `after_report` (`app/worker/edges.py:109-129`) deletes the job's
  scratch folder, once pages are uploaded and the proposal is written. Review, confirm and manual-pages
  read only S3 and the DB.
- A `failed` job keeps its scratch so Retry re-runs only the failed tasks. If scratch has gone (a
  redeploy), `Runner.revalidate` already re-runs from the S3 source, as today.
- `clean_cancelled_scratch` still covers `cancelled` / `confirmed` jobs whose scratch outlived them.

### 2.4 Debug bundle on settle

- Copy `segments.json` and `ingest.json` into the job row at `after_report` time. Add a new
  `ingest_job.debug` JSONB column, or nest them under `report["debug"]`.
- The proposal and edited proposal are already on the row.
- With that in place, settling (`_drop_job_objects`, cancel) deletes **everything** under
  `ingest/{job_id}/`. The invariant for the reconciler becomes: "settled job ⇒ prefix empty".

### 2.5 Reconciler

- New `app/worker/reconcile.py`, called from `run_sweep` (already claimed once a day across workers).
- Each check produces findings `{kind, key_or_path, job_id?, age, action}`. They are logged with the
  job context and written to `ingest_event`. Deletion runs only when `INGEST_RECONCILE_DELETE=true`.

| Check | Rule | Grace |
|---|---|---|
| Orphan job prefix | `ingest/{id}/` (and legacy `tmp/ingest/{id}/`) whose job row is missing or settled | 1 day after settle |
| Stale temp objects | anything under `tmp/` | 24 h |
| Orphan scratch | folder under the scratch root whose job is not `queued` / `running` / `failed` | 1 day |
| Orphan paper images | key under `papers/` not referenced by any `question_page.image_key` | 7 days |
| Stuck jobs | `queued` / `running` job with no live lease and no task progress | 6 h → mark `failed` with reason `stuck`, which is visible and retryable |
| Missing source | pending job whose `source_key` object no longer exists | report only, never delete the row |

- Listing `papers/` is one paginated `ListObjectsV2` pass, which is cheap at ~10k objects/year. Compare
  it against a single `SELECT image_key FROM question_page`.
- Add a `GET /api/import/reconcile/last` admin route (or a section in the job list) that shows the last
  run's findings. Optional.

### 2.6 Database rows

- `ingest_job` / `ingest_task` / `ingest_event` rows are kept indefinitely. They are small and form the
  audit trail.
- `confirmed_paper_ids` can name a later-deleted paper. The paper-delete routes
  (`routes/papers.py:366`, `routes/ingest.py:321`) should log an `ingest_event` against the source job
  when one exists.

### Tests

- pytest for the sweep no longer expiring `review_ready` / `failed`.
- pytest for prefix derivation from a legacy `tmp/ingest/` source key.
- pytest for scratch removal after `after_report`.
- pytest for each reconciler check, in dry-run and delete modes, against `FakeObjectStore`.
- Vitest for the age badge.

---

## Phase 3 — Direct-to-S3 upload

**Goal:** the browser uploads straight to S3 with a presigned POST, so the API never holds the file.

1. **`POST /api/import/uploads`**, body `{filename, size}`, admin only.
   - Creates the `ingest_job` row with a new status `awaiting_upload` and
     `source_key = ingest/{job_id}/source.pdf`. No task is created yet.
   - Returns `generate_presigned_post` with conditions `content-length-range 1..100 MB`,
     `Content-Type = application/pdf` and a 15-minute expiry, plus `job_id`.
2. **The browser** POSTs the form directly to S3, with `XMLHttpRequest` upload progress for a real
   progress bar per file.
3. **`POST /api/import/jobs/{id}/uploaded`.**
   - `HEAD` the object and check its size and content type.
   - Set status `queued` and insert the `register` task. Inserting the task row is still what enqueues
     the job.
   - Log a "job created" event.
4. **PDF validation** (page count, password, sha256) moves from `create_job` into the `register` stage
   (`app/worker/edges.py` `after_register`, or a pre-register check). A bad PDF becomes a failed job
   with a clear reason instead of an immediate 422. `ingest_job.page_count` / `sha256` are filled in by
   the worker.
5. **Bucket CORS rule** for the app origin (POST only). Document it in `DEPLOYMENT.md` and add the
   equivalent to the MinIO `createbuckets` service in `docker-compose.yml`.
6. **Abandoned uploads.** An `awaiting_upload` job older than 1 hour is marked `cancelled` by the
   reconciler, which also removes any partial object.
7. Remove the old multipart `POST /api/import/jobs`, or keep it for tests and the CLI for one release.
   Keep nginx's `client_max_body_size` for the Manual tab.

The job id now exists **before** the bytes move, so the traceability from Phase 1 covers the upload
itself.

### Tests

- pytest for the presign response conditions.
- pytest for the `uploaded` endpoint: missing object, wrong size, happy path.
- pytest for the abandoned-upload reconciler rule.
- Vitest for the upload flow with a mocked S3 POST.

---

## Phase 4 — Question/answer booklet pairing

Write [docs/adr/0002-qa-booklet-pairing.md](../adr/0002-qa-booklet-pairing.md) first, summarising this
phase. Changes in `ingestion/` follow its own verification rule: run over `ingestion/samples/` before
and after, then diff.

### 4.1 Answer-only papers keep their question numbers (prerequisite)

- **Where:** `ingestion/pipeline/proposal.py:123-127, 195-201, 251-254`.
- When an answer section has no question section, build `questions` from the answer section's numbered
  rectangles: `{number, question_rects: [], answer_rects: [...]}`. Today they collapse into numberless
  `orphan_answers`.
- Add a paper-level `role: "question" | "answer_only"`.
- Relax the review validators in `app/services/ingest_review.py`:
  - `_check_paper` (line 138) must allow empty `question_rects` when `role == "answer_only"`;
  - `_check_rect` stays strict.
- `ReviewPage.jsx`: an answer-only paper shows its answers grouped by question number, and replaces
  "Confirm" with "Attach to paper…" (4.6).
- Add a warning to the proposal when a question section has no answer section, so question-only
  booklets are flagged as such rather than silent.

### 4.2 Cover pages from the segment call

- Add an optional `cover_pages: [int]` per segment to `RESPONSE_SCHEMA` and `SEGMENT_SYSTEM` in
  `ingestion/ingester/request.py`. The prompt change: "for each range, also list the cover /
  instruction pages that precede it and belong to it".
- Carry the field through `Segment.entry` / `from_entry` (`ingestion/ingester/segments.py:68-95`),
  `parse_answer` and `validation._check_each`: pages must be in range and must not overlap any
  segment.
- **Fallback when the model returns none:** the unclaimed pages immediately before `first_page`.
- Bump the segment `Stage` `version` in `ingestion/pipeline/registry.py`. The fingerprint does not
  cover prompt text.
- Committed fixtures (`ingestion/samples/*.segments.json`) lack the field. That is fine because
  `from_entry` uses `.get`, but regenerate them for the diff.
- Answer booklets often have no cover. An empty list is valid.

### 4.3 Metadata from cover pages, per paper

- Generalise `app/ai/filename_extractor.py` into `extract_paper_metadata(filename, db, cover=None)`.
  It sends the cover pages as a `document` block, a sub-PDF cut with `extract_page_range`. If there are
  no cover pages, it sends the first page of the section. The filename stays as a hint.
- **Add `stream`** to the tool schema, `_EMPTY` and `resolve_metadata`, and raise `max_tokens` from
  256.
- Move the call from `after_register` to a new **`after_segment`** hook in `app/worker/edges.py`
  (hooks already work for any job-scope stage). Call it once **per segment pair**, not once per job.
  Store the results in `job.report["paper_metadata"][paper_key]`, or in the table from 4.4.
- `build_review` (`ingest_review.py:70`) and `ReviewPage.jsx` pre-fill each paper from its own
  metadata instead of the single job-level `filename_metadata`. Keep `filename_metadata` as a fallback
  for old jobs.
- The extractor stays in `app/`, because `ingestion/` must not import `app`
  (`tests/test_ingestion_independence.py`).
- Update `tests/test_ai_filename_extractor.py`, `tests/test_ingest_jobs.py` and `tests/test_ingest.py`.

### 4.4 A queryable per-paper record and duplicate protection

- New table `ingest_paper`:
  - `id`, `job_id` FK, `paper_key` (the proposal key), `role`;
  - the seven metadata fields (nullable until known), `metadata_source` (`cover` / `filename` /
    `admin`);
  - `status` (`pending`, `confirmed`, `skipped`, `attached`);
  - `paper_id` FK NULL, `matched_ingest_paper_id` FK NULL.

  This replaces the per-paper bits buried in `job.report` JSON.
- Normalise `paper_number` on write: "P1", "Paper 1", "I" → "1"; keep letters such as "a" / "b".
- **Duplicate protection on `paper`:**
  - First, run a one-off query to find existing duplicates on the seven-field key, and resolve them by
    hand.
  - Then add a unique index on `(school_id, year, level_id, subject_id, exam_type_id, stream_id,
    paper_number)`.
  - `confirm_import` turns a unique violation into a 409 "this paper already exists — attach to it
    instead?".
- Check the live DB first (see [Open questions](#open-questions)).

### 4.5 Automatic matching

Runs at the end of `after_report`, and again whenever an admin edits a paper's metadata on the review
page.

- **Answer-only `ingest_paper` → confirmed `paper` with the same key:** propose an attach (4.6). It
  stays a proposal: the admin clicks once to accept.
- **Answer-only ↔ pending question `ingest_paper` with the same key** (both unconfirmed): link them
  with `matched_ingest_paper_id`. The question paper's review page shows "answers available from
  <filename>". Confirming it pulls the answer rectangles from the other job, cropped from **that**
  job's `source.pdf`, and settles both.
- **Question-only paper confirmed while a matching answer-only job is pending:** surface it on the
  answer job as a ready-to-attach target.
- If several candidates match, or only some fields match, do not auto-link. Mark the paper for manual
  matching.

### 4.6 Attach answers to an existing paper

- New `attach_answers(job, paper_key, paper_id, mode)` in `app/services/ingest_confirm.py`:
  1. Crop the answer rectangles with the existing `render_crop` / `build_confirm_payload` logic.
  2. Map them to `Question` rows by `question_number`.
  3. Add `QuestionPage(page_type="answer")` rows with collision-safe ordering, reusing
     `paper_admin.apply_page_changes` / `commit_with_page_moves`.
  4. Record the outcome with `_record(job, key, "attached", paper_id)` in the **same** transaction (see
     B1b).
- `mode` is `append` or `replace`; the default is `replace` when the question has no answer pages.
- Answer numbers with no matching question are **reported back** to the admin, not dropped.
- `POST /api/import/jobs/{id}/attach`, body `{key, paper_id, mode}`.

### 4.7 Manual matching UI

- On `ReviewPage.jsx`, an answer-only paper (or any unmatched one) gets a **"Match to paper…"** panel:
  - pre-filled filters from its metadata;
  - candidate list from `GET /api/papers` (already filters on every metadata field) plus pending
    question papers from other jobs (new `GET /api/import/papers/pending`);
  - a side-by-side preview of the first question and its answer;
  - an Attach button.
- On the job list, add an "Unmatched answers" filter.

### Tests

- pytest for the proposal shape of answer-only papers (via the pipeline's report stage on a fixture).
- pytest for the review validators.
- pytest for `paper_number` normalisation.
- pytest for the unique-index → 409 path.
- pytest for the auto-match rules (single match, ambiguous, partial).
- pytest for `attach_answers` (append / replace / unmatched numbers).
- Vitest for the matching panel.
- For `ingestion/`, diff `ingestion/samples/` output before and after 4.1 and 4.2.

---

## Suggested order and PR slicing

| PR | Contents | Depends on |
|---|---|---|
| 1 | Phase 0 (B1, B1b, B2) | — |
| 2 | Phase 1.1–1.4 (context, JSON stdout, lifecycle logs, tracebacks) | — |
| 3 | Phase 1.5–1.7 (`ingest_event`, Claude request ids + cost, provenance, job-id UI) | 2 |
| 4 | Phase 2.1–2.4 (prefix, no expiry, scratch cache, debug bundle) + DEPLOYMENT.md lifecycle change | 1 |
| 5 | Phase 2.5 reconciler (dry-run) | 3, 4 |
| 6 | Phase 3 direct upload | 4, 5 |
| 7 | ADR 0002 + Phase 4.1 + 4.2 (ingestion changes, sample diffs) | — |
| 8 | Phase 4.3 + 4.4 (per-paper metadata, `ingest_paper`, unique index) | 7 |
| 9 | Phase 4.5–4.7 (matching, attach, UI) | 1 (B1b), 8 |

After PR 5 has run in production for a week or two with sensible reports, flip
`INGEST_RECONCILE_DELETE=true`.

## Verification rules

- **Webapp:** `pytest` and Vitest for every behaviour change (CLAUDE.md, "Write tests where the
  change is testable"). Both run in CI's `frontend-build` job.
- **`ingestion/`:** no unit tests. Run its commands over `ingestion/samples/` before and after, then
  diff (see [ingestion/CLAUDE.md](../../ingestion/CLAUDE.md)).
- **Docs:** each PR updates the owning feature doc in the same change, as listed per phase above.

## Open questions

1. **Live DB indexes on `paper`.** The ORM and migrations define none, but a manual index in Supabase
   would not show up there. Check with
   `SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'paper';` before 4.4.
2. **`paper_number` normalisation table.** Confirm the spellings seen in real filenames and covers
   (e.g. "P1", "Paper I", "1A") before fixing the rules.
3. **Attach mode default** when a question already has answer pages: replace or append? The plan
   proposes asking each time and defaulting to append.
4. **Age-badge threshold** for highlighting stale reviews (plan: 14 days).
