# Ingestion

**Scope:** Getting exam papers into the bank and maintaining them — the admin import wizard, the
server-side PDF→image pipeline, and the Manage Papers editor. The AI part-split/topic step that
follows import is in [ai-labelling.md](./ai-labelling.md); filename metadata extraction is there
too.

## Import API — admin only

```
POST   /api/import/upload-pdf       -- (Manual) upload a single PDF; returns page images + AI-suggested metadata
POST   /api/import/confirm          -- submit labeled paper + questions
POST   /api/import/ai-topics        -- AI part split + topic/marks suggestions for one question
POST   /api/import/save-topics      -- persist user-reviewed parts for a paper's questions
DELETE /api/import/papers/{paper_id} -- delete a paper, its questions/pages, and their S3 objects

POST   /api/import/jobs             -- (Auto-detect) submit a PDF as an ingest job; returns {job_id}
GET    /api/import/jobs?status=     -- the requesting admin's jobs, newest first, with progress + worker_alive
GET    /api/import/jobs/{id}        -- one job, its report and its tasks (+ progress, worker_alive)
POST   /api/import/jobs/{id}/retry  -- return failed/blocked tasks and everything downstream to ready
DELETE /api/import/jobs/{id}        -- cancel a job
```

The two AI-topics routes are documented in [ai-labelling.md](./ai-labelling.md).

## Auto-detect import

On `/admin/import` the admin picks **Auto-detect** or **Manual** (the wizard below, unchanged).
Auto-detect is the start of automatic import: the admin drops PDF(s), each becomes an **ingest job**
and shows up in the job list. The [worker](#the-worker) takes it from `queued` to `review_ready` with
a proposal on the job row. Tables: [DATA_MODEL.md](../DATA_MODEL.md#auto-import-jobs).

### Job routes (admin only; non-admins get `403`)

- `POST /api/import/jobs` (multipart `file`) — a non-`application/pdf` content type, or bytes
  PyMuPDF cannot open (corrupt, encrypted, zero pages), is a `422`. Otherwise it reads the page
  count and SHA-256 from the bytes (no rendering), puts the PDF at
  `tmp/ingest/{job_id}/source.pdf`, inserts the `ingest_job` (`queued`) with its first task
  (`section` NULL, stage `register`, status `ready`), and returns `{"job_id": ...}` with `201`.
  It makes no Claude call, so it returns in well under a second. If the DB insert fails the
  uploaded object is deleted.
- **Filename metadata** is not extracted in the request. The worker runs the existing filename
  extraction ([ai-labelling.md](./ai-labelling.md#filename-metadata-extraction)) as part of the
  `register` task, via `record_filename_metadata` in `app/services/ingest_jobs.py`, and stores the
  result in `report.filename_metadata` (merged into any existing report; empty metadata on error)
  so the review/confirm step can pre-fill the metadata sidebar. It stays in `app/` because it
  needs the DB reference data (`ingestion/` never imports `app`).
- `GET /api/import/jobs?status=` — **only jobs the requesting admin created**, newest first, as
  `{"data": [...], "worker_alive": bool, "heartbeat_age_s": int|null}`; an unknown `status` is `422`.
  Each job carries its progress (below).
- `GET /api/import/jobs/{id}` — the job plus `report`, its `tasks` (status, attempts, duration,
  warnings, reason/error, ...), its progress and `worker_alive` / `heartbeat_age_s`. Another admin's
  job, or an unknown id, is `404`.
- `POST /api/import/jobs/{id}/retry` — runs the pipeline's own `Runner.retry` over the `ingest_task`
  rows (`_RequestStore` in `app/services/ingest_jobs.py`: `SqlStore` on the request's session), so
  the dependency rules (needs, soft needs, `report` after the sections, per-route chains) are not
  re-implemented. Failed and blocked tasks, and every finished task downstream of them, go back to
  `ready` (or `pending` while their needs are unfinished) with `attempts` reset; the job status is
  re-derived (`queued`/`running`) so the worker picks it up. Returns the job plus `reopened` (a
  count; `0` when nothing was broken). A `cancelled`, `confirmed` or `expired` job is a `409`.
- **Progress** on every job (`job_progress`): `stage` — the stage of the running task, else of the
  most recently finished task, `null` before anything has started; `tasks_done` / `tasks_total` —
  tasks `done` or `skipped` over all tasks (the total grows as sections fan out);
  `warnings_count` — warnings summed over the tasks; `needs_review` — any task flagged.
- **Worker liveness**: `worker_alive` is true when the `worker_heartbeat` row (touched every 30 s)
  is at most `WORKER_STALE_SECONDS` (90, `app/services/ingest_jobs.py`) old; `heartbeat_age_s` is
  its age in whole seconds. No row (worker never started) gives `false` / `null`. The server computes
  both so the UI never compares clocks. With the worker stopped a new job stays `queued`; starting
  the worker drains it.
- `DELETE /api/import/jobs/{id}` — cancel: sets `cancelled`, commits, **then** deletes the
  `tmp/ingest/{id}/` prefix (a failed S3 delete only orphans temp objects). `204`. A `confirmed`,
  `cancelled` or `expired` job is a `409`.

S3 goes through the `get_object_store` dependency (`put` / `get` / `presign` / `delete_prefix`), so
tests use the `fake_object_store` fixture.

### Job statuses

| Status | Meaning |
| --- | --- |
| `queued` | Created; no task has started |
| `running` | A task is running, or some have finished and others are still to run |
| `review_ready` | `report` is done and `ingest_job.proposal` is stored: a proposal is ready for the admin to review |
| `failed` | Nothing is left to run and there is nothing to review (`error` names the failing stage) |
| `confirmed` | The admin confirmed; papers created (`confirmed_paper_ids`, `paper.source_job_id`) |
| `cancelled` | The admin cancelled it; its S3 prefix is removed |
| `expired` | Abandoned and cleaned up |

Task statuses: `pending`, `ready`, `running`, `done`, `skipped`, `failed`, `blocked`.

The worker derives `queued` / `running` / `review_ready` / `failed` from the job's tasks after every
task completion (`app.worker.store.derive_job_status`); the API never recomputes it. A job that has
`report` done and a proposal is `review_ready` **even when some sections failed** (the proposal lists
them as failed, flagged for the admin). It is `failed` when a job-level stage (`register`, `segment`,
`split`) failed or was blocked — `report` still runs then, but describes a booklet nothing was
extracted from — or when the pipeline ends with no proposal. A job in an API-owned state
(`cancelled`, `confirmed`, `expired`) is never touched.

### UI

`ImportPage` shows an Auto-detect / Manual tab pair (it opens on Manual if a manual import is in
progress in `sessionStorage`). `ManualImport` is the old wizard, unchanged. `AutoImport` is a
compact drop zone (one job per dropped PDF) above the job list. Each row shows the filename (click
to open the job detail), status, the current stage with a `done/total` progress bar, the warnings
count, a "Needs review" marker, created time, and Retry and Cancel buttons. The list polls
`GET /api/import/jobs` every 3 s (`POLL_MS`) while any job is `queued` or `running` and stops when
none is and on unmount; Refresh is still there. While a job is active and `worker_alive` is false
the list shows a "Worker offline" banner and marks the waiting rows. The job detail (`JobDetail`)
lists every task with its section, status, duration, warnings and reason or error, and refreshes
with each poll.

### The worker

`python -m app.worker` (`app/worker/`) is a separate process that runs queued jobs through the
`ingestion/pipeline` stages (see [pipeline/README.md](../../ingestion/pipeline/README.md) and
[ADR 0001](../adr/0001-stage-pipeline.md)). One process, one task at a time.

- **Loop.** Each pass writes the `worker_heartbeat` row, then the pipeline `Runner` claims one ready
  task through `SqlStore` (`app/worker/store.py`), runs it in the job's scratch folder, and records
  status, duration, warnings, `needs_review` and reason/error. The claim is
  `SELECT ... FOR UPDATE SKIP LOCKED` ordered by job (oldest first) then task (stage) order, followed by
  an update guarded by `WHERE status = 'ready'` whose row count says whether this claimer won (that
  guard is what the SQLite unit tests exercise; SKIP LOCKED itself is Postgres-only). Tasks of a job
  that is not `queued`/`running` — a cancelled job — are never claimed. `SqlStore.complete` records
  the outcome and the fan-out tasks (`split` creates each section's tasks) in one transaction and is
  refused for a task whose lease was lost; `add_tasks` is idempotent on `(job, section, stage)`.
  The API creates only the `register` task; `register`'s hook creates the rest of the job-level chain
  (`segment`, `split`, `report`).
- **Job status** is derived from the tasks on every completion (above), with `report` supplying the
  proposal.
- **Leases.** A claim sets `lease_until = now() + 10 min`. A liveness thread refreshes the running
  task's lease and the heartbeat every 30 s (and the runner's own heartbeat thread does too), so a
  long stage keeps its task. On start, tasks past their lease go back to `ready` (`failed` after 3
  attempts; the runner also does this on every pass).
- **Shutdown.** SIGTERM/SIGINT finish the current task and exit cleanly.
- **Scratch and S3 edges** (`app/worker/edges.py`, composed around the stages — `ingestion/` knows
  nothing of S3). The job's scratch folder is `$INGEST_SCRATCH_DIR/{job_id}/`
  (default `/tmp/ingest/`). Resolving it fetches `tmp/ingest/{job_id}/source.pdf` from S3 into it when
  missing, so `register` finds its input and a restart that lost the folder gets the booklet back
  before any stage reads it. Artefacts lost with the folder are **not** re-downloaded: their tasks'
  outputs are missing, so on start `Runner.revalidate` reopens them and they run again (slower, not
  wrong); with the folder intact, fingerprints keep finished tasks as they are. After `register`
  succeeds the filename metadata is extracted (`report["filename_metadata"]`). After `report`
  succeeds the review images `pages/pNN.webp` (booklet page numbering) are uploaded to
  `tmp/ingest/{job_id}/pages/` and the proposal is stored in `ingest_job.proposal`; the run summary
  (per-stage timing, deduplicated warnings, `needs_review`, one entry per task) is merged into
  `report` next to `filename_metadata`. The images go up from `report`, not `render`, because the
  job-level `pages/` folder the proposal's image paths name is assembled by `report` (`render` writes
  only each section's own `review/` folder). A job cancelled while `report` runs gets no upload.
- **Memory.** PyMuPDF pages are rasterised one at a time and freed in the extractor (no list of
  pixmaps), and the worker reads each review image from disk only as it uploads it.
- **Config (env).** `INGEST_SCRATCH_DIR`, `INGEST_OCR_COMMAND` (the Tesseract command, split like a
  shell line; `tesseract` in the container), `INGEST_SEGMENT_MODEL`, `INGEST_RETRY_MODEL` — each
  defaulting to the ingestion config. `INGEST_FIXTURES_DIR` is for development only: a folder of
  `<paper>.segments.json` plans (named after the uploaded filename) copied beside the scratch
  `source.pdf` so the `segment` stage uses them instead of the Messages API.
- **Token logging.** The segment stage's Messages API usage reaches `app.logger.log_tokens` through
  `ingester.request.usage_listener` (set by the worker). Prices for `claude-haiku-4-5` and
  `claude-opus-5` (the retry model) are in `_PRICES`.
- **Testing seam.** `app.deps.get_pipeline_runner()` returns the factory the worker builds its runner
  with; tests pass a factory whose stages write a canned proposal (`tests/test_worker.py`). Setting
  `WORKER_TEST_DATABASE_URL` to a scratch Postgres database runs the worker tests there too.

## Server-side pipeline

*(The Manual flow.)*

### 1. `POST /api/import/upload-pdf`

- Accepts a single PDF (multipart). Non-PDF content types → `422`.
- **PyMuPDF** renders each page to an RGB image at 300 dpi. Pages are processed **one at a time**
  (`app/services/ingest.py::iter_pdf_pages` is a generator): a page is rendered, standardised,
  encoded and uploaded, then released before the next is rendered. A 300 dpi page is ~26 MB, so
  holding a whole booklet (~2 GB for 80 pages) would not fit the 6 GB VM; the peak is now one page's
  pixmap/image plus the stored WebP bytes.
- `app/pdf/image_processing.py::standardize` stores each page **content-only** (no margin),
  downscaling to a **1760 px** width (aspect preserved) only when wider, otherwise unchanged. Page
  margins and question numbers are added later by the generation engine. See
  [DATA_MODEL.md](../DATA_MODEL.md#image-dimension-standards).
- Encodes WebP at quality 85 (`to_webp_bytes`).
- Stores images under `tmp/{upload_id}/page_{i}.webp` and returns presigned URLs (2-hour expiry) for
  the grid preview, plus each page's width/height.
- **Always** calls AI filename-metadata extraction and returns `suggested_metadata` alongside the
  pages — unconditional, not optional.

### 2. `POST /api/import/confirm`

- Accepts paper metadata + an ordered list of questions, each with its pages (`temp_key`,
  `page_type`, `page_order`, `width_px`, `height_px`).
- Accepts an optional `is_premium` flag, **defaulting to `true`** — imported papers are premium
  unless the admin unticks the box.
- **Rejects a stream and level from different school levels with a `422`**
  (`school_level_conflict`, shared with the paper `PUT`). Premium is sold per school level and the
  paywall reads the *level*'s, so a mismatched paper would read as Secondary in the UI while being
  sold to Primary customers. See [users-and-premium.md](./users-and-premium.md).
- Creates `Paper`, `Question` and `QuestionPage` rows transactionally. Each question also gets a
  single blank `QuestionPart`: topics and marks arrive later, at the review step, but the
  every-question-has-a-part invariant holds from creation.
- Moves images from the temp key to the canonical pattern
  `papers/{paper_id}/q{question_number}/{page_type}_{page_order}.webp` (S3 server-side copy, then
  delete of the temp object).
- Persists `width_px` / `height_px` per page.
- Returns the created paper id plus serialized questions/pages, each page carrying a fresh presigned
  URL.

### 3. `DELETE /api/import/papers/{paper_id}`

Deletes the `Paper` row — cascading to `Question` / `QuestionPage` / `QuestionPart` and, through the
part, `QuestionTopic` / `QuestionSubtopic` — then deletes the S3 objects **after** the DB
transaction succeeds.

## Import wizard UI (admin)

`/admin/import`. Each step is a UI state in the same page.

### Step 1 — Upload PDF(s)
Drag-drop zone accepting multiple PDFs; files are appended in upload order, preserved through the
flow.

### Step 2 — Server processes PDF → page images
Loading state while the server renders pages, which come back as image URLs.

### Step 3 — Grid preview
All returned pages as a thumbnail grid — **max 5 per row** (fewer on narrow screens), thumbnails at
an A4 aspect ratio so they scale with the cell width. Click a thumbnail for a **lightbox / zoom
modal**.

### Step 4 — Auto-label questions
Every page is auto-assigned `Q1, Q2, Q3, …` sequentially, rendered on each thumbnail.

### Step 5 — Manual adjust (merge pages into one question)
Each page has a "Merge with prev" toggle — available both on the thumbnail and inside the lightbox,
so pages can be merged while paging through zoomed images without leaving fullscreen. Marking a page
a continuation **auto-renumbers all subsequent pages** (Q4 → Q3, Q5 → Q4, …). A visual cue (e.g. a
left bracket) groups pages belonging to one question.

### Step 6 — Set Q/A divider
Click between two adjacent pages, or drag a divider line, to mark where Questions end and Answers
begin. Pages after the divider relabel as `A1, A2, A3, …`. Answer pages support the same multi-page
merging as step 5.

### Step 7 — Set paper metadata (sidebar)
Dropdowns populated from the reference tables — Subject, Stream, Level, School, Exam Type — plus
Year (number), Paper Number (string: "1", "2", "a", "b") and a **Premium paper** checkbox, ticked by
default. **AI pre-fill:** when the upload completes, filename extraction pre-populates the form (see
[ai-labelling.md](./ai-labelling.md#filename-metadata-extraction)); the admin confirms or edits.

### Step 8 — Confirm upload
Shows a summary — # questions, # answers, metadata — then calls `POST /api/import/confirm`.

### Step 9 — AI part split, topics & marks
See [ai-labelling.md](./ai-labelling.md#the-review-step-topicreviewjsx). There is no separate "set
marks" step: marks come from the parts.

### Components

`<UploadDropZone />`, `<PageGrid />` + `<PageThumbnail />` + `<Lightbox />`,
`<QuestionGroupingControls />` (merge / un-merge with auto-renumbering), `<QADivider />`,
`<MetadataSidebar />`, and `<PartsEditor />` (step 9, shared with the admin question editor).

## Editing an imported paper

`/admin/papers` lists imported papers; `PaperEditor.jsx` opens one. Each question is a
`QuestionEditor.jsx` card: question number, page-image editors, tags, and a `<PartsEditor />` for its
parts. There is **no question-level marks field** — marks are per part and the total is derived.

The admin question-CRUD endpoints share the parts write path with import:

```
POST   /api/papers/{id}/questions   -- { question_number, parts, tag_ids, pages }
PUT    /api/questions/{id}          -- same shape
PUT    /api/papers/{paper_id}       -- full metadata update (requires every FK id)
```

Both question endpoints take `parts: [{label, marks, topic_assignments}]` — no question-level
`marks`, since it is derived — and return the question with `marks` (the sum) plus
`parts: [{part_order, label, marks, selections: [{topic_id, subtopic_id}]}]`, where `selections` is
the flat cross-product shape the editor UI consumes. See
[ai-labelling.md](./ai-labelling.md#the-shared-parts-write-path).

**Re-run AI** re-labels one question through `POST /api/import/ai-topics` and replaces its parts with
the suggestion. The paper-level re-label does the same for every question, and is triggered when an
admin changes the paper's subject or stream — which invalidates the existing topic labels, since
topics are scoped to (subject, stream). Clearing those labels reaches them through `question_part`;
the **parts themselves and their marks survive**, only the now-out-of-scope topic assignments go.

For the Premium checkbox on the papers list, see
[users-and-premium.md](./users-and-premium.md#flagging-a-paper-premium).
