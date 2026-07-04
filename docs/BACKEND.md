# Backend

**Scope:** FastAPI server — API endpoints, import pipeline (server side), PDF generation engine, auth/security, object-store integration. For database schema, see [DATA_MODEL.md](./DATA_MODEL.md). For AI calls (topic labeling, filename extraction), see [AI_INTEGRATION.md](./AI_INTEGRATION.md). For frontend UX flows, see [FRONTEND.md](./FRONTEND.md).

## Stack

- **Python:** 3.11+
- **Framework:** FastAPI (REST API; first-class Pydantic validation; first-class Anthropic SDK)
- **PDF → Image:** **PyMuPDF** (`fitz`), rendered at 300 dpi. *(Not `pdf2image`/Poppler as originally planned — no system dependency required.)*
- **Image processing:** Pillow (WebP encoder)
- **PDF generation:** ReportLab (dependency installed; **engine not yet implemented**, see below)
- **Auth:** bcrypt for password hashing, JWT (httpOnly cookie) via `python-jose`

## Project Layout (Actual)

```
app/
├── routes/         # FastAPI route handlers — auth.py, reference.py, ingest.py, questions.py, generate.py
├── schemas/        # Pydantic request/response models — auth.py, reference.py, questions.py, generate.py
├── models/         # SQLAlchemy ORM models — orm.py
├── services/       # business logic — auth.py, ingest.py, generate.py (question selection)
├── pdf/            # image_processing.py (PDF→image, standardization), layout_engine.py (PDF packing + render)
├── storage/        # s3_client.py — AWS S3 / MinIO client + signed URL helpers
├── ai/             # Claude API clients — filename_extractor.py, topic_labeler.py (see AI_INTEGRATION.md)
├── db.py           # SQLAlchemy engine/session, declarative Base, get_db dependency
├── logger.py       # file logger + Timer + token/cost logging helper
└── main.py
```

Note: Pydantic schemas and ORM models live in separate `schemas/` and `models/` packages (not combined as originally suggested).

## API Endpoints

### Auth (Implemented)

```
POST   /api/auth/register       -- public registration
POST   /api/auth/login          -- sets JWT in httpOnly cookie
POST   /api/auth/logout         -- clears cookie
GET    /api/auth/me             -- returns current authenticated user
```

### Reference Data — Admin write, Public read (Implemented)

```
GET|POST|PUT|DELETE  /api/school-levels
GET|POST|PUT|DELETE  /api/subjects
GET|POST|PUT|DELETE  /api/streams
GET|POST|PUT|DELETE  /api/levels
GET|POST|PUT|DELETE  /api/schools
GET|POST|PUT|DELETE  /api/exam-types
GET|POST|PUT|DELETE  /api/topics          -- filtered by ?subject_id=&stream_id=; list includes nested subtopics
GET|POST|PUT|DELETE  /api/subtopics       -- filtered by ?topic_id=
GET                   /api/papers/years    -- distinct paper years, filtered by ?subject_id=&stream_id=&level_id=
```

Delete endpoints guard against deleting a row that still has dependent data (returns `409` instead of violating a FK constraint).

### Import — Admin only (Implemented)

```
POST   /api/import/upload-pdf       -- upload a single PDF; returns page images + AI-suggested metadata
POST   /api/import/confirm          -- submit labeled paper + questions
POST   /api/import/ai-topics        -- trigger AI subtopic suggestions for one question
POST   /api/import/save-topics      -- persist user-reviewed subtopic selections for a paper's questions
DELETE /api/import/papers/{paper_id} -- delete a paper, its questions/pages, and their S3 objects
```

### Questions — Public read (Implemented)

```
GET    /api/questions             -- filter params: subject_id, stream_id, level_id, year,
                                     school_id, exam_type_id, topic_ids[] (repeatable),
                                     exclusive (bool — restrict to only the given topics),
                                     subtopic_keyword (substring match on subtopic name),
                                     page, page_size
                                  -- returns paginated question list with paper info, topic chips,
                                     and a presigned first-page image URL
GET    /api/questions/:id         -- full question detail: question pages + answer pages
                                     (each with a presigned S3 URL), topics
```

There is no `/api/questions/:id/image/:page` proxy endpoint — images are served exclusively via presigned S3 URLs embedded directly in the `/api/questions` and `/api/questions/:id` responses (see [Auth & Security](#auth--security)).

### Generation — Authenticated (Implemented)

```
POST   /api/generate/select      -- auto-select a randomized set of questions summing near
                                    target_marks. Body: { filters, target_marks,
                                    exclude_question_ids[] }. `filters` mirrors the Browse
                                    filter params (subject_id, stream_id, level_id, year,
                                    school_id, exam_type_id, topic_ids[], exclusive,
                                    subtopic_keyword). Returns { items, total_marks,
                                    target_marks, exact, warning }.
POST   /api/generate/paper       -- render ONE PDF variant from a manual selection.
                                    Body: { question_ids[] (min 1), variant:
                                    "question"|"answer", header_text }. Returns
                                    application/pdf. Empty question_ids -> 422.
```

`POST /api/generate/select` (`app/routes/generate.py`) reuses the Browse filter suite
(`_apply_filters` + the eager-load options from `app/routes/questions.py`) to build the candidate
pool, excludes any `exclude_question_ids`, then runs `knapsack_select`. It never returns a 404 — an
empty result with a `warning` string keeps the live builder UI responsive.

`POST /api/generate/paper` renders the question **or** answer paper (one variant per call — the
frontend calls it twice to get both PDFs). Both require authentication (`get_current_user`), not
admin. See [Paper Generation Engine](#paper-generation-engine-implemented) below.

## Import Pipeline (Server Side)

The frontend drives the UX flow (see [FRONTEND.md](./FRONTEND.md)). Server-side responsibilities:

1. **`POST /api/import/upload-pdf`** (Implemented)
   - Accepts a single PDF (multipart upload). Rejects non-PDF content types with `422`.
   - Uses **PyMuPDF** to render every page to an RGB image at 300 dpi.
   - Standardizes each page per `app/pdf/image_processing.py::standardize`: stores the image **content-only** (no margin), downscaling to a **1760 px** width (aspect preserved) only when wider, otherwise keeping it unchanged. Page margins and question numbers are added later by the generation engine.
   - Encodes WebP at quality 85 (`to_webp_bytes`).
   - Stores images under `tmp/{upload_id}/page_{i}.webp` and returns presigned URLs (2-hour expiry) for the frontend grid preview, along with each page's width/height.
   - Always calls AI filename-metadata extraction (see [AI_INTEGRATION.md](./AI_INTEGRATION.md)) and returns `suggested_metadata` alongside the pages — this is unconditional, not optional.

2. **`POST /api/import/confirm`** (Implemented)
   - Accepts paper metadata + an ordered list of questions, each with its pages (`temp_key`, `page_type`, `page_order`, `width_px`, `height_px`).
   - Creates `Paper`, `Question`, and `QuestionPage` rows transactionally.
   - Moves images from the temp key into the canonical object-store key pattern: `papers/{paper_id}/q{question_number}/{page_type}_{page_order}.webp` (S3 server-side copy + delete of the temp object).
   - Persists `width_px` and `height_px` per page.
   - Returns the created paper id plus serialized questions/pages (each page including a fresh presigned URL).

3. **`POST /api/import/ai-topics`** (Implemented)
   - Takes a single `question_id` (not a whole paper — the frontend calls this once per question).
   - Fetches the question's topic/subtopic list scoped to the paper's `subject_id` + `stream_id`, downscales the question's page images for the AI call (`downscale_for_ai`, capped at 768 px long side), and calls Claude (see [AI_INTEGRATION.md → Topic Auto-labeling](./AI_INTEGRATION.md)).
   - Returns suggested `subtopic_id`s to the frontend for review — it does **not** persist anything itself.

4. **`POST /api/import/save-topics`** (Implemented)
   - Accepts a `paper_id` plus, for each question in that paper, the final list of `subtopic_id`s the admin confirmed.
   - Validates all question ids belong to the paper and all subtopic ids are valid for the paper's subject/stream.
   - Replaces (delete + re-insert) `QuestionTopic` rows for the paper's questions.

5. **`DELETE /api/import/papers/{paper_id}`** (Implemented)
   - Deletes the `Paper` row (cascades to `Question`/`QuestionPage`/`QuestionTopic` in the DB), then deletes the associated S3 objects after the DB transaction succeeds.

## Question Selection (Implemented)

`app/services/generate.py::knapsack_select(questions, target_marks)` picks a subset of questions
whose marks sum as close as possible to `target_marks`, exposed via `POST /api/generate/select`.

- **Randomized-restart greedy**, not an exact optimizer. Each restart shuffles the pool and greedily
  adds questions until the running total reaches the target, considering every intermediate subset.
  The restart budget scales with pool size (`_RESTARTS_PER_QUESTION = 20`, clamped to `[200, 2000]`).
- Prefers an **exact match**; otherwise returns the subset whose total is closest to the target
  (a slight overshoot is allowed if it lands closer). Stops early once an exact match is found.
- The randomness is intentional: the same filters/target produce a *different* paper each time.
  Equally-good subsets are chosen by reservoir sampling so repeated calls vary.
- Questions with `null` or non-positive `marks` are ignored. Returns `[]` for a non-positive target
  or when nothing is selectable.

`POST /api/generate/select` also supports an **add-to-selection** flow client-side: the frontend
passes the already-chosen questions in `exclude_question_ids` and reduces `target_marks` by their
running total, so autofill tops up an existing selection instead of replacing it (see
[FRONTEND.md](./FRONTEND.md#paper-generation-ui)).

## Paper Generation Engine (Implemented)

`POST /api/generate/paper` (`app/routes/generate.py::generate_paper`) turns a manual selection into
a PDF. It generates **one variant per call** — the frontend calls it twice, `variant="question"`
then `variant="answer"`, to produce the separate question and answer papers, which follow identical
layout rules. There is no server-side autofill-at-generate: the selection is already resolved
(manually or via `/generate/select`) before this endpoint is hit.

### Route behavior

- Fetches the selected `Question` rows (eager-loading pages + paper), then **re-sorts them into
  `question_ids` order** (a DB `IN` query is unordered).
- Numbers questions `1..N` in **selection order**. The same numbers are used in both variants: an
  answer keeps the number of its question. For `variant="answer"`, a question with no answer pages
  is **skipped**, but its number stays reserved so the remaining answers still match the question
  paper.
- `header_text` is printed only on the question variant.
- Returns `Response(pdf, media_type="application/pdf")`. Empty `question_ids` → 422 (schema).

### Layout engine (`app/pdf/layout_engine.py`)

Works in **300-DPI pixel space** (A4 = 2480×3508 px). Stored images are content-only (≤ 1760 px
wide from ingestion); the engine builds the page margins itself. `LayoutEngine(page_capacity_px,
fit_width)` — `page_capacity_px` is the usable vertical budget (page height minus top/bottom
margins); `fit_width` selects the horizontal treatment per variant:

- **`fit_width=True` (question paper):** each image is scaled (aspect preserved) to a fixed **1760 px
  content width** and drawn **centered** on the page — **360 px margin on each side** (1760 + 360 +
  360 = 2480). All questions therefore render at the same width regardless of their stored size.
- **`fit_width=False` (answer paper):** each image keeps its **native size** (≤ 1760 px), **flush to
  the 360 px left margin**, with the remaining width as right padding. It never overflows (360 + 1760
  < 2480). A **100 px vertical gap** separates one question's answer block from the next (`block_gap_px`);
  multiple answer pages of the same question stack with no extra gap.

Both variants draw the question number into the **360 px left margin**, right-aligned just left of
the image.

- `compute_layout(blocks, header_text="") -> LayoutPlan`: greedy **packing** — keeps a running
  cursor and places each block (one question's pages for this variant) on the current page while it
  fits `page_capacity_px`; a block that would overflow starts a new page. Two short consecutive
  questions therefore share a page. A block taller than a whole page starts fresh and its pages flow
  across pages at render time. Block heights use the variant's scale (`_image_scale`). Header height
  is reserved on the first page. `page_count` is a lower bound (render is authoritative when a tall
  block overflows).
- `render(plan, fetch_bytes) -> bytes`: **ReportLab** canvas at A4, scaling px→points. For each
  block it places the page image(s) (`fetch_bytes(image_key)` → Pillow → `ImageReader`) at the
  variant's scale and left offset, then draws the **number in the left margin**, right-aligned just
  left of the image's edge and nudged slightly below the block's top (drawn *after* the image so it
  is never covered). Page-breaks per image; an image taller than the page is scaled to fit. In
  production `fetch_bytes` is `get_image_bytes`; the `variant="answer"` call only fetches answer
  bytes and vice-versa, so no image is fetched twice across the two requests.

Dataclasses: `Block(label, source_label, pages, page_index)` and
`LayoutPlan(page_count, blocks, header_text)`. `source_label`
(`{School} {Year} {Level} {ExamType} Q{original_number}`) is assembled per question but not yet
drawn — kept for future use.

### Library

ReportLab (in `requirements.txt`) drives the per-page cursor + image flow; Pillow decodes the stored
WebP page images.

## Auth & Security

- **Passwords:** bcrypt via `bcrypt.gensalt()` (default cost factor 12). Implemented.
- **Auth tokens:** JWT (`python-jose`, HS256) in an `httpOnly`, `secure`, `samesite=lax` cookie named `access_token`, 7-day expiry. `JWT_SECRET_KEY` read from env (falls back to an insecure default — **must** be set in production). Implemented.
- **Admin routes:** `require_admin` dependency (in `app/routes/auth.py`) checks `user.role == "admin"`, returns `403` otherwise. Applied to all `POST/PUT/DELETE` on reference data and all `/api/import/*` routes. Implemented.
- **Image access:** images are never proxied through the backend — every question/page response embeds an S3 **presigned URL** (`get_presigned_url`), keeping VM bandwidth free for HTML/JSON. Implemented.
- **Input validation:** all API inputs are Pydantic models (`app/schemas/`), including password-strength validation on registration. Implemented.
- **CORS:** **not implemented** — no `CORSMiddleware` is registered in `app/main.py`.
- **Rate limiting:** **not implemented** — there is no limiter on `/api/auth/*` or anywhere else.

## Object Store Integration

- AWS SDK for Python — `boto3`. Implemented in `app/storage/s3_client.py`:
  - `put_image(key, bytes)` — used during import (`s3.put_object(..., ContentType="image/webp")`).
  - `get_presigned_url(key, expires_in)` — used whenever images are returned to the frontend.
  - `copy_only(src_key, dst_key)` — server-side copy that leaves the source in place. Import/edit flows copy temp uploads to their canonical key, commit the DB, and only then delete the temp sources, so a failed copy or commit leaves the temp uploads intact (retryable) and never orphans canonical objects.
  - `delete_object(key)` — used when a paper/question/page is deleted; callers commit the DB deletion **before** removing objects, since S3 deletes are irreversible.
  - `get_image_bytes(key)` — fetches raw bytes for server-side use (AI topic labeling).
- All keys follow the pattern documented in [DATA_MODEL.md](./DATA_MODEL.md#image-storage-conventions).
- **Local dev:** `boto3` is pointed at an S3-compatible endpoint via the `S3_ENDPOINT_URL` env var (empty/unset in production) — same code path, no special-casing.
