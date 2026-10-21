# Auto-import

**Scope:** the Auto import (`/admin/import/auto`) and Review queue (`/admin/import/review`) pages.
A dropped booklet PDF becomes an **ingest job**. The worker runs the `ingestion/` pipeline over it
and leaves a **proposal**. The admin reviews it and confirms, skips or attaches each proposed paper.

Related docs:
- Question/answer pairing (answer-only papers, attach, matching): [qa-pairing.md](./qa-pairing.md).
- Manual import and Manage Papers: [ingestion.md](./ingestion.md).
- Tables: [DATA_MODEL.md](../DATA_MODEL.md#auto-import-jobs).
- Pipeline internals: [ingestion/README.md](../../ingestion/README.md),
  [ADR 0001](../adr/0001-stage-pipeline.md).
- Vocabulary (job, task, stage, section, proposal, …): [CONTEXT.md](../../CONTEXT.md).

## Lifecycle

1. Browser → `POST /uploads` → job `awaiting_upload` plus a presigned S3 POST.
2. Browser uploads the PDF straight to S3 (the API never holds the file).
3. Browser → `POST /jobs/{id}/uploaded` → job `queued` (`register` task inserted).
4. Worker: `register` → `segment` → `split` → per-section stages → `report` → job `review_ready`,
   with the proposal on the row.
5. Admin reviews and edits on the review page, then decides each paper: confirm, skip or attach.
6. Every paper decided → job `confirmed` (settled), and its S3 prefix is deleted.

## Routes

All admin-only (`403` otherwise). Any admin can see and act on any admin's job.

| Route | Behaviour |
|---|---|
| `POST /api/import/uploads` `{filename, size}` | Size outside 1 B–100 MB → `422`. Creates the job (`awaiting_upload`, `source_key = ingest/{id}/source.pdf`, no task). Returns `201 {job_id, url, fields}`: a presigned POST pinned to that key, `Content-Type: application/pdf`, 1 B–100 MB, 15-minute expiry. |
| `POST /api/import/jobs/{id}/uploaded` | HEADs the object. Missing → `409`. Size out of range or type not PDF → `422` (job stays `awaiting_upload`). Otherwise the job becomes `queued` and the `register` task is inserted. Calling it twice, or on a job not `awaiting_upload`, → `409`. The bytes are not inspected. |
| `GET /api/import/jobs` | All jobs, newest first, each with its progress and `papers` (below). Filters (combinable): `status` (one or comma-separated; unknown → `422`), `job_id`, `paper_id` (the job that created the paper, via `paper.source_job_id` or `confirmed_paper_ids`), `unmatched_answers=true`. Also returns `worker_alive` and `heartbeat_age_s`. |
| `GET /api/import/jobs/{id}` | The job, its `report` (including `cost`), its tasks (status, attempts, duration, warnings, reason, error, traceback) and worker liveness. Unknown id → `404`. |
| `POST /api/import/jobs/{id}/retry` | Failed and blocked tasks, plus everything downstream, go back to the queue with attempts reset. Returns `reopened` (a count). `409` for a job that is `awaiting_upload`, `cancelled`, `confirmed` or `expired`, or that has any paper already decided. |
| `DELETE /api/import/jobs/{id}` | Cancel: status `cancelled` is committed first, then the job's S3 prefix is deleted. `204`. A `confirmed`, `cancelled` or `expired` job → `409`. |
| `GET /api/import/jobs/{id}/review` | The proposal under review (`proposal_edited` if present, else `proposal`), with presigned page URLs and pixel sizes. Also `filename`, `edited`, `page_count`, `paper_metadata` (each paper's ids, plus `extracted`: the raw names read), `filename_metadata` (old jobs), each paper's `key`/`outcome`, `matches`, `proposals`. No proposal yet → `409`. |
| `PUT /api/import/jobs/{id}/proposal` | Saves the admin's edits as `proposal_edited` (see [Editing](#editing)). |
| `PUT /api/import/jobs/{id}/papers/{key}/metadata` | Stores sidebar metadata on the paper's `ingest_paper` row and re-runs matching. See [qa-pairing.md](./qa-pairing.md). |
| `POST /api/import/jobs/{id}/manual-pages` `{first_page, last_page}` | Cuts that range of the job's PDF into Manual-flow pages, using the job's stored metadata (no Claude call). Bad range → `422`. |
| `POST /api/import/jobs/{id}/confirm` | Confirm one paper. See [Confirm and skip](#confirm-and-skip). |
| `POST /api/import/jobs/{id}/skip` `{paper_label}` | Skip one paper. |
| `POST /api/import/jobs/{id}/attach`, `GET /api/import/papers/pending`, `POST`/`DELETE /api/import/jobs/{id}/papers/{key}/match`, `DELETE /api/import/jobs/{id}/papers/{key}/proposed-paper` | Pairing, Unmatch and "Not this one". See [qa-pairing.md](./qa-pairing.md). |

There is no multipart job-creation route; the old `POST /api/import/jobs` was removed.

**Progress** (on every job in the list and detail):
- `stage`: the running task's stage, else the most recently finished one, else `null`.
- `tasks_done` / `tasks_total`: tasks `done` or `skipped` out of all tasks. The total grows as
  sections fan out.
- `warnings_count`.
- `needs_review`: any task flagged.

**Papers** (on every job in the list): one entry per `ingest_paper` row, in key order —
`{key, role, status, school_id, year, level_id, subject_id, exam_type_id, stream_id, paper_number,
linked, match_status}`, where `linked` means it is linked to a paper of another job. Empty until
`report` has run. Loaded in one query for the whole list. This is what the review queue's cards show.

**Worker liveness:** `worker_alive` is true when the heartbeat is at most 90 s old. If the worker
has never started: `false` / `null`. Both values are computed server-side.

## Statuses

| Job status | Meaning |
|---|---|
| `awaiting_upload` | Created; the browser has not finished uploading. Can be cancelled, not retried. |
| `queued` | Uploaded; no task has started. |
| `running` | Some tasks are finished or running, others still to run. |
| `review_ready` | `report` is done and the proposal is stored. Set even if some sections failed (they show in the proposal as failed). |
| `failed` | Nothing left to run and nothing to review: a job-level stage (`register`, `segment`, `split`) failed or was blocked, or there is no proposal. `error` names the stage. |
| `confirmed` | Every paper is confirmed, skipped or attached (settled). |
| `cancelled` | Cancelled by the admin, or by the reconciler for an abandoned upload (settled). |
| `expired` | Historical only; nothing sets it any more. |

- **Task statuses:** `pending`, `ready`, `running`, `done`, `skipped`, `failed`, `blocked`.
- The worker derives `queued` / `running` / `review_ready` / `failed` from the tasks after every
  task completion.
- The API sets `awaiting_upload`, `confirmed` and `cancelled`. The worker never touches a job in
  those states.

## PDF validation

- Done in the worker, before `register` runs. The upload route never opens the file.
- Rejected inputs fail the job (`error = "register failed: <reason>"`, shown in the job list). The
  failure is not retried automatically:
  - "The file is not a readable PDF"
  - "The PDF is password protected"
  - "The PDF has no pages"
- After `register`: `page_count` and `sha256` are set on the job (both `NULL` until then).

## Auto import page

`/admin/import/auto` (`AutoImport.jsx`).

- **Drop zone** (`PdfDropZone.jsx`): drop PDFs or whole folders (walked recursively through
  `webkitGetAsEntry`), or use **Choose files** / **Choose folder** (`webkitdirectory`). Non-PDFs and
  macOS `._*` files are ignored and counted; folder contents queue in path order. The zone never
  locks: more files can be added while earlier ones upload. A status line says what was added,
  skipped as a duplicate (same name, size and modified time already queued) or ignored.
- **Upload queue** (`UploadQueue.jsx`, `UploadQueueProvider` mounted above the routes in `App.jsx`):
  - each PDF is its own entry; at most **3** transfer at once, the rest wait their turn
  - entries: waiting (**Remove**), uploading with a progress bar (XHR; **Stop** aborts the transfer
    and the API client cancels the half-made job), failed with its error (**Retry upload** /
    **Remove**). If the S3 POST or `uploaded` fails, the job is cancelled.
  - uploads keep going while the admin moves to other pages; the navbar's Import link and the
    Auto import tab show how many are in flight, and leaving the site mid-upload asks first
    (`beforeunload`)
  - a finished upload leaves the queue and the job list refreshes
- **Processing board**: the upload queue's entries, then every job still in the pipeline
  (`awaiting_upload`, `queued`, `running`) or stopped in it (`failed`). Each row shows:
  - the filename (opens the job detail), page count, warnings, age badge
  - a **step tracker** — Upload → Read PDF (`register`) → Find papers (`segment`) → Split →
    Extract questions (`locate`/`render`/`grid`/`ocr`/`questions`) → Assemble (`report`) — built
    from the job's `stage` (`pipelinePhases.js`): green behind, blue in hand, red where it failed
  - a caption ("Extract questions · 5/9 tasks", "Waiting for the worker", "Failed at Read PDF") and,
    while running, a `done/total` bar
  - the failure reason, "Worker offline" on an active job when the heartbeat is stale, Retry
    (failed jobs) and Cancel
  - an `awaiting_upload` job not in this browser's queue reads "Upload not finished"
- **Counts** above the board (uploading, queued, running, failed) and a link to the review queue
  with the number of jobs ready.
- **Finished while you were here**: jobs seen in the pipeline that became `review_ready` while the
  page was open, each with a Review link (dismissable).
- **Polling:** every 3 s while anything is uploading, queued or running; otherwise every 15 s (so
  another admin's uploads still appear). Ticks are skipped while the tab is hidden and caught up
  when it is shown (`usePoll.js`).
- **"Worker offline"** banner when a job is active and `worker_alive` is false.
- **All jobs** (`JobHistory.jsx`): every job, settled ones included, with status, failure reason,
  created time, age badge, Review / Retry / Cancel.
  - **Age badge** on unsettled jobs: "waiting N days" (or "waiting today"), from `created_at`.
    Highlighted amber after more than 14 days.
  - **Filters:** **Awaiting review** = `review_ready` + `failed`; **Unmatched answers**: jobs with a
    pending answer-only paper linked to no question paper; **Search box**: a UUID searches by job
    id, digits by paper id. All combine; a filtered list is fetched again on every poll.
- **Job detail (`JobDetail.jsx`):**
  - the job id with a Copy button
  - every task: section, status, duration, warnings, reason or error
  - a collapsed "Traceback" for a failed task
  - refreshes with the poll

## Review queue

`/admin/import/review` (`ReviewQueuePage.jsx`): the jobs waiting for a decision.

- `review_ready` jobs, **oldest first**, polled every 10 s by the import layout
  (`useReviewQueue.js`, shared with the tab badge and the review page) so a job the worker finishes
  appears without a reload. Jobs that arrive after the page loaded are tagged **New**.
- **Each card:** filename (and a Review button), age badge, pages, papers and how many are still to
  decide, warnings, "Pages flagged for a closer look" when a task needs review, and one line per
  paper from the job list's `papers`:
  - Questions / Answers and its key
  - its metadata in words (school · year · level · subject · exam type · paper no.), with the
    missing fields named, or "No details read from the cover"
  - for an answer-only paper: linked / matching paper found / needs matching / not matched; for a
    question paper: "Answers linked from another upload"
  - a decided paper is greyed with its outcome
- **Only jobs with unmatched answers** narrows the list in the browser.

## Review page

`/admin/import/jobs/:jobId/review`, opened from the review queue (and from `review_ready` rows of
All jobs). The header links back to the queue and to the **next job** in it (the oldest other one).

- **One paper at a time:** tabs when there are several, each tab showing its outcome.
- **Page strip:** a flagged page has an amber border, with its reason as a tooltip.
- **Page image overlay:**
  - question rectangles in blue
  - answer rectangles in green
  - `orphan_answers` in grey, dashed
- **Question list:** each question with its flags. Clicking one selects it and jumps to its page.
- **Unrouted sections** are listed with their reason and page range. **Handle manually** cuts that
  range (`manual-pages`) into the Manual wizard and switches to it. This is how a booklet whose
  questions could not be located is finished.
- **Right column:**
  - question paper: the metadata sidebar, pre-filled from the paper's own `paper_metadata[key]`
    (old jobs: `filename_metadata`), plus **Confirm paper** and **Skip this paper**.
  - **School** is a combobox (`SchoolCombobox.jsx`): type to search the existing schools. When the
    cover named a school that matched none (`paper_metadata[key].extracted.school` with no
    `school_id`), it is shown in amber as "*Raffles Instn* — not in the list", and the closest
    existing names (character-bigram likeness) are listed first. It counts as blank: **Confirm** is
    disabled, with "Pick a school: “Raffles Instn” is not in the list." shown, until a school is
    picked. A job without `extracted` (from before it existed) shows nothing extra. The Manual
    import sidebar keeps its plain dropdown.
  - answer-only paper: the Match panel ([qa-pairing.md](./qa-pairing.md)).
- **Metadata edits** are kept per paper and saved (debounced 800 ms) to
  `PUT .../papers/{key}/metadata`. This is best effort, since confirm sends the final values.
- After the last decision the page moves on to the next job in the review queue, or back to the
  queue when it is empty. **Handle manually** opens `/admin/import/manual`.

### Editing

- **Rectangles** (pure edits in `proposalReducer.js`):
  - Click to select; drag the four edge handles to resize, or drag the box itself to move it.
    Clamped to the page, minimum 4 pt.
  - The **Selected box** bar names the box, offers **Delete box**, and for an answer box a
    **Belongs to** menu: move it to another question, or to "No question" (an orphan answer, not
    imported). An orphan answer can be given to a question the same way.
  - Delete/Backspace removes it (unless focus is in an input); Esc deselects.
- **Drawing boxes:** **Draw question box** / **Draw answer box** (an answer-only paper has only the
  latter), then drag on the page. One box per press; Esc cancels. Where it goes is shown before
  drawing:
  - with a question selected: added to that question's question / answer boxes
  - otherwise a question box becomes a new question numbered `max+1`; an answer box becomes an
    orphan answer (in an answer-only paper, a new answer numbered `max+1`)
- **Questions:**
  - Number field: a duplicate or non-positive number is refused, with the reason.
  - **Merge with previous**: keeps the previous question's number and concatenates rectangles and
    flags.
  - **Split before the selected rectangle**, or **split the selected rectangle in half**. The first
    part keeps the number and all answer rectangles; the second part gets `max+1` and no answers.
- **Deleting a question's last question rectangle** deletes the question, and its answer rectangles
  become orphan answers.
- **Saving:** edits save to `PUT .../proposal`, debounced 800 ms and also on leaving the page. The
  header shows Saving… / Saved / Not saved (with the server's message). There is no "reset to
  original".
- **The server accepts only** each paper's `questions` and `orphan_answers`, merged onto the
  original. Pages, labels, `unrouted` and warnings cannot be changed. `409` unless `review_ready`.
- **Validation** (`422`, nothing stored):
  - every rectangle has exactly `page, x0, y0, x1, y1`
  - its page belongs to the paper, with `x0 < x1`, `y0 < y1`, inside the page
  - question numbers are unique positive integers within a paper
  - each question has at least one question rectangle (except in an `answer_only` paper)

## Confirm and skip

**Paper key** (`paper_label`):
- the paper's question label (`q1`)
- else its answer label (`a1`) for an answer-only paper
- else `paper{n}`

**`POST .../confirm`** `{paper_label, subject_id, stream_id, level_id, school_id, exam_type_id,
year, paper_number, is_premium}` → `201`.

- **Refused when:**

  | Condition | Status |
  |---|---|
  | Job not `review_ready`, or paper already decided | `409` |
  | Unknown key | `404` |
  | Stream and level from different school levels | `422` |
  | Paper has no questions (skip it instead) | `422` |
  | `answer_only` paper (attach or skip it instead) | `422` |

- **Images:**
  - Each rectangle of the edited (else original) proposal is cropped from `source.pdf` at 300 dpi,
    standardised (width capped at 1760 px), WebP-encoded and uploaded to `tmp/`, one at a time.
  - `question_rects` become question pages and `answer_rects` answer pages, in order.
  - **Orphan answers are not imported** (the UI says so).
- **One transaction:**
  - the paper, its questions and pages
  - `paper.source_job_id`
  - the job's `review_outcome[key] = confirmed` and `confirmed_paper_ids`
  - the `ingest_paper` row (status, `paper_id`, final metadata)
  - the `paper_confirmed` event
- **S3 order:**
  - Crops are copied to canonical keys before the commit.
  - Temp crops are deleted after it. A failed delete is logged and skipped.
  - If anything fails, nothing is committed and the canonical copies are removed.
- **Never duplicates:** the job row is locked while deciding, so a double click gets a `409`. The
  paper and the outcome commit together.
- **Provenance:** recorded on the new rows (see [ingestion.md](./ingestion.md#provenance)).
- **Linked answer paper:** if the paper is linked to a pending answer-only paper of another job, its
  answers come in too ([qa-pairing.md](./qa-pairing.md#confirming-a-linked-pair)).
- **Response:** `/confirm`'s (`paper_id`, `questions`) plus `job_status`, `answers_from` and
  `unmatched`. The page then opens the topic review (`TopicReview`) on the new paper.

**`POST .../skip`** `{paper_label}`:
- Records `skipped` (outcome, `ingest_paper` row and event in one transaction). Same `404`/`409`
  rules as confirm.
- Skipping a linked question paper releases the link.

**Settling:**
- When every paper has an outcome (`confirmed`, `skipped` or `attached`), the job becomes
  `confirmed`, even if every paper was skipped.
- After the commit, its whole S3 prefix is deleted.
- A job whose proposal has no papers can only be cancelled.

## The worker

A separate container from the same image. One process runs one task at a time.

**Claiming tasks:**
- The oldest job first, then stage order: `SELECT … FOR UPDATE SKIP LOCKED`, then an update
  guarded by `status = 'ready'`.
- Tasks of a job that is not `queued`/`running` are never claimed.
- The API inserts only `register`. `register`'s hook adds `segment`, `split` and `report`, and
  `split` fans out the section tasks.

**Recording a task:** status, duration, warnings, `needs_review`, reason or error, and the
traceback. The outcome and any fan-out tasks are recorded in one transaction. This is refused if the
task's lease was lost.

**Leases and liveness:**
- A claim leases the task for 10 min. Every 30 s the lease and the `worker_heartbeat` row are
  refreshed.
- Expired leases go back to `ready`, or `failed` after 3 attempts.
- An idle worker polls every 2 s.

**Shutdown:** SIGTERM/SIGINT finish the current task, then exit.

**Hooks around stages** (`app/worker/edges.py`; `ingestion/` knows nothing of S3 or the DB):

| When | Hook does |
|---|---|
| Before `register` | Downloads `source.pdf` into scratch if missing; validates the PDF (above). |
| After `register` | Stores `page_count` and `sha256`; adds the job-level tasks. |
| After `segment` | Extracts each paper's metadata from its cover into `report.paper_metadata[key]` ([ai-labelling.md](./ai-labelling.md#paper-metadata-extraction)). A failure never fails the task. |
| After `report` | Uploads review images to `{prefix}pages/`. Stores the proposal, the run summary (timings, warnings, `needs_review`) and the debug bundle (`segments.json` + `ingest.json` → `ingest_job.debug`). Upserts `ingest_paper` rows and runs matching, all in one transaction. A job cancelled meanwhile gets no upload. |
| After `report` is recorded done | Deletes the job's scratch folder, unless the job is `failed`. |

**Scratch** (`$INGEST_SCRATCH_DIR/{job_id}/`, default `/tmp/ingest`) is a cache:
- It is deleted once `report` is recorded done. Review, confirm and `manual-pages` read only S3 and
  the DB.
- A `failed` job keeps it, so Retry re-runs only the failed tasks.
- Lost scratch (a redeploy): the source is re-downloaded and missing artefacts are re-run on start.
  `review_ready` jobs are never revalidated.

**Memory:** pages are rasterised one at a time, and review images are read from disk only as they
upload. The container is capped at 1 CPU / 6 GB.

**Env:**

| Variable | Purpose |
|---|---|
| `INGEST_SCRATCH_DIR` | Scratch root (default `/tmp/ingest`). |
| `INGEST_OCR_COMMAND` | Tesseract command. Unset means OCR is off. |
| `INGEST_SEGMENT_MODEL`, `INGEST_RETRY_MODEL` | Segment-stage models. |
| `INGEST_RECONCILE_DELETE` | Lets the reconciler act (below). |
| `INGEST_FIXTURES_DIR` | Development only: `<filename>.segments.json` plans used instead of the API. |
| `WORKER_VERSION` | Recorded on the heartbeat. |

## Storage and retention

| Where | Holds | Removed |
|---|---|---|
| `ingest/{job_id}/source.pdf`, `ingest/{job_id}/pages/pNN.webp` | Upload, review images | When the job settles. There is **no** bucket lifecycle rule on `ingest/`. |
| `tmp/ingest/{job_id}/…` | Legacy jobs from before the move | When the job settles. |
| `tmp/{uuid}/…` | Confirm crops, Manual-import pages, page-edit uploads | After commit; the bucket rule expires `tmp/` after 2 days. |
| Scratch folder | Pipeline artefacts | After `report`, or by the sweep. |
| `ingest_job.debug` | `segments.json` + `ingest.json` (a few KB) | Never. |
| `ingest_job`, `ingest_task`, `ingest_paper`, `ingest_event` rows | State and audit | Never. |

- **Pending jobs never expire.** They stay until confirmed, skipped, attached or cancelled.
- **Invariant:** a settled job has an empty prefix.
- **Prefix derivation:** always from the stored `source_key`, never rebuilt from the id, so legacy
  `tmp/ingest/` jobs keep working.

**Daily sweep** (claimed atomically via `worker_heartbeat.last_sweep_at`, so it runs at most once a
day across workers and restarts):
1. Removes the scratch folders of jobs `cancelled` or `confirmed` more than a day ago (regardless of
   the delete flag).
2. Runs the reconciler.

### Reconciler

**Report-only unless `INGEST_RECONCILE_DELETE=true`.** That flag gates every action: deleting,
marking jobs failed, and cancelling uploads.

| Check | Rule | Grace | Action when enabled |
|---|---|---|---|
| `orphan_job_prefix` | `ingest/{id}/` or `tmp/ingest/{id}/` whose job is missing or settled | 1 day after settle | delete |
| `stale_temp` | Object under `tmp/` (except `tmp/ingest/`) | 24 h | delete |
| `orphan_scratch` | Scratch folder whose job is missing or not `queued`/`running`/`failed` | 1 day | delete |
| `orphan_paper_image` | Key under `papers/` that no `question_page.image_key` references | 7 days | delete |
| `stuck_job` | `queued`/`running` job with no live lease and no activity | 6 h | mark `failed` (reason `stuck`), its ready/running tasks too, so Retry works |
| `abandoned_upload` | `awaiting_upload` job | 1 h | cancel and delete the partial object |
| `missing_source` | Pending job whose source object is gone | — | report only, always |

- **Each finding** `{kind, key_or_path, job_id?, age, action}` is a WARNING log line plus an
  `ingest_event` (`kind = reconcile`). `job_id` is NULL when there is no job row.
- **`action` values:**
  - dry run: `would_delete`, `would_mark_failed`, `would_cancel`
  - enabled: `deleted` (or `delete_failed`), `marked_failed`, `cancelled`
  - always: `report_only`
- **A failing check** is logged and never stops the others.
- **Flip the flag** after a week or two of sensible reports in production.

## Observability

- **Logs:**
  - JSON on stdout. Every line logged while working on a job carries `job_id` (plus `section`,
    `stage`, `task_attempt` inside a task).
  - API lines carry `request_id` (echoed as `X-Request-ID`).
  - `docker logs <container> | grep <job-uuid>` finds a job across both containers. See
    [ARCHITECTURE.md](../ARCHITECTURE.md#cross-cutting-conventions) and
    [DEPLOYMENT.md](../DEPLOYMENT.md#logs).
- **Lifecycle log lines** (INFO, one each, with `job_id`):
  - `ingest_job/created` (filename, size, user), then `ingest_job/registered` (sha256, page count)
  - `ingest_task/claimed`, `ingest_task/finished` (status, duration)
  - `ingest_job/proposal_stored`, `proposal_saved`
  - `paper_confirmed`, `paper_skipped`, `paper_attached`, `retry`, `cancelled`
- **Stage failures** are logged at ERROR with the exception.
- **Tracebacks:** the last 4 KB of a raised stage's traceback is stored on the task and shown in
  the job detail. It is cleared on re-claim or retry. A failure a stage *reports* (rather than
  raises) has no traceback.
- **Event history (`ingest_event`):** one row per transition, written in the transaction of the
  change. Kinds:
  - `created`, `task_claimed`
  - `task_finished` (status, error, warnings, duration, traceback; also for lease-expiry failures)
  - `retry`, `cancelled`, `proposal_edited`
  - `paper_confirmed`, `paper_skipped`, `paper_attached`, `paper_deleted`
  - `reconcile`, and historical `expired`
  - Task rows are overwritten on re-claim; every attempt stays in the history.
- **Claude cost:**
  - Every Claude call for a job (segmentation, per-paper metadata) logs its Anthropic request id
    (`anthropic_request_id`), model, tokens and `cost_usd`.
  - It also adds to `report.cost` (`calls`, `input_tokens`, `output_tokens`, `cache_write`,
    `cache_hit`, `cost_usd`), under a row lock so concurrent calls are never lost.
  - Prices: `app/logger.py`.

## Testing seams

- `get_object_store` → `fake_object_store` fixture.
- `get_metadata_extractor` → `fake_metadata_extractor` fixture.
- `get_pipeline_runner` → a factory with canned stages (`tests/test_worker.py`).
- `WORKER_TEST_DATABASE_URL` runs the worker tests on a real Postgres (SKIP LOCKED is
  Postgres-only).
