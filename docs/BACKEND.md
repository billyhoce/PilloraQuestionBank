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
├── routes/         # FastAPI route handlers — auth.py, reference.py, ingest.py, questions.py
├── schemas/        # Pydantic request/response models — auth.py, reference.py, questions.py
├── models/         # SQLAlchemy ORM models — orm.py
├── services/       # business logic — auth.py, ingest.py, generate.py (stub)
├── pdf/            # image_processing.py (PDF→image, standardization), layout_engine.py (stub)
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

### Generation — Public (Not Implemented)

```
POST   /api/generate/paper       -- planned; no route exists yet
```

`app/services/generate.py::knapsack_select` and `app/pdf/layout_engine.py::LayoutEngine` are stubs that raise `NotImplementedError`. No route is registered in `main.py` for paper generation.

## Import Pipeline (Server Side)

The frontend drives the UX flow (see [FRONTEND.md](./FRONTEND.md)). Server-side responsibilities:

1. **`POST /api/import/upload-pdf`** (Implemented)
   - Accepts a single PDF (multipart upload). Rejects non-PDF content types with `422`.
   - Uses **PyMuPDF** to render every page to an RGB image at 300 dpi.
   - Standardizes each page per `app/pdf/image_processing.py::standardize`: keeps original height, pads width to a fixed **2480 px** canvas with a **90 px** left margin (cropping source content if it would overflow the canvas).
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

## Paper Generation Engine (Not Implemented)

`POST /api/generate/paper` and its supporting engine are **not built yet**. The design below is the intended target; treat it as a spec for future work, not current behavior.

### Inputs (two modes)

1. **Manual selection:** `{ question_ids: [...], header_text, include_answers }`
2. **Auto-fill by criteria:** `{ filters, target_marks, header_text, include_answers }` — server selects questions whose marks sum to the target.

### Auto-fill Algorithm

Greedy / knapsack selection over questions matching `filters`. Prefer **exact match** to `target_marks`; otherwise return the closest combination. (At v1 scale, a simple iterative approach is fine.) `app/services/generate.py::knapsack_select` is currently a stub.

### PDF Layout Algorithm

- **Page size:** A4 (210 × 297 mm).
- **Margins:** reserve a left margin for question numbers; reserve top/bottom for header/footer.
- **First page:** insert custom header/instructions text from `header_text`.
- **For each question (in selection order):**
  1. Compute *source label* and place it above the question in small text:
     ```
     {School} {Year} {Level} {ExamType} Q{question_number}
     ```
     Example: `Raffles Institution 2024 Sec 3 EOY Q5`
     Note: `Q{question_number}` here is the **original** number from the source paper, not the renumbered position.
  2. Place a *paper-local* question number in the left margin: `Q1`, `Q2`, ... — renumbered for this generated paper.
  3. Place the question's image(s) in `page_order`.
  4. Track a vertical cursor. If `cursor + image_height > page_height - bottom_margin`, start a new page before placing the image.
  5. After placing all pages of a question, if the next question fits in the remaining space, place it on the same page; otherwise, start a new page.
- **Answer pages (optional):** if `include_answers`, append all `page_type='answer'` images after all questions, grouped per question, with the same renumbered labels.

`app/pdf/layout_engine.py::LayoutEngine.compute_layout` / `.render` are currently stubs (`NotImplementedError`). `app/pdf/layout_engine.py` already defines the `QuestionLayout` / `LayoutPlan` dataclasses the implementation is expected to fill in.

### Library

ReportLab is already in `requirements.txt`, in preference over FPDF2, for the per-page cursor + image flow described above.

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
  - `copy_object(src_key, dst_key)` — server-side copy + delete, used to move temp upload images to their canonical key on confirm.
  - `delete_object(key)` — used when a paper is deleted.
  - `get_image_bytes(key)` — fetches raw bytes for server-side use (AI topic labeling).
- All keys follow the pattern documented in [DATA_MODEL.md](./DATA_MODEL.md#image-storage-conventions).
- **Local dev:** `boto3` is pointed at an S3-compatible endpoint via the `S3_ENDPOINT_URL` env var (empty/unset in production) — same code path, no special-casing.
