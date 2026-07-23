# Backend

**Scope:** FastAPI server — API endpoints, import pipeline (server side), PDF generation engine, auth/security, object-store integration. For database schema, see [DATA_MODEL.md](./DATA_MODEL.md). For AI calls (topic labeling, filename extraction), see [AI_INTEGRATION.md](./AI_INTEGRATION.md). For frontend UX flows, see [FRONTEND.md](./FRONTEND.md).

## Stack

- **Python:** 3.11+
- **Framework:** FastAPI (REST API; first-class Pydantic validation; first-class Anthropic SDK)
- **PDF → Image:** **PyMuPDF** (`fitz`), rendered at 300 dpi. *(Not `pdf2image`/Poppler as originally planned — no system dependency required.)*
- **Image processing:** Pillow (WebP encoder)
- **PDF generation:** ReportLab (see [Paper Generation Engine](#paper-generation-engine-implemented))
- **Auth:** bcrypt for password hashing, JWT (httpOnly cookie) via `python-jose`

## Project Layout (Actual)

```
app/
├── routes/         # FastAPI route handlers — auth.py, reference.py, ingest.py, questions.py, generate.py
├── schemas/        # Pydantic request/response models — auth.py, reference.py, questions.py, generate.py
├── models/         # SQLAlchemy ORM models — orm.py
├── services/       # business logic — auth.py, ingest.py, generate.py (question selection)
├── pdf/            # image_processing.py (PDF→image, standardization), layout_engine.py (PDF packing + render), sample_data.py (synthetic fixtures)
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
POST   /api/auth/register       -- public registration (always role "public")
POST   /api/auth/login          -- sets JWT in httpOnly cookie
POST   /api/auth/logout         -- clears cookie
GET    /api/auth/me             -- returns current authenticated user
```

### User Management — Admin only (Implemented)

```
GET    /api/users               -- list all users (id, email, role, created_at)
PATCH  /api/users/{id}/role     -- change a user's tier. Body: { role: "admin"|"public"|"premium" }.
                                   An admin cannot change their own role (400). Unknown user -> 404.
                                   Invalid role value -> 422.
```

The three tiers are `admin`, `public` (shown as "Normal" in the UI), and `premium`.
Registration always yields `public`; `premium`/`admin` are granted here by an admin
(the Subscribe page is a payment stub, not a self-serve upgrade path).

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
                                     paper_number (case-insensitive exact match; strings may
                                     contain letters, e.g. "1", "a"),
                                     search (free-text keyword, OR-matched case-insensitively
                                     against topic, subtopic, tag, school, subject, level,
                                     school-level tier (e.g. "Secondary"), stream and exam-type
                                     names; a "T{n}" token (e.g. "T10") matches the topic
                                     number; an all-digit keyword also matches the paper year
                                     exactly),
                                     page, page_size
                                  -- returns paginated question list with paper info, topic chips
                                     ({ topic_name, topic_number, subtopic_names[] }),
                                     and a presigned first-page image URL
GET    /api/questions/:id         -- full question detail: question pages + answer pages
                                     (each with a presigned S3 URL), topics
```

There is no `/api/questions/:id/image/:page` proxy endpoint — images are served exclusively via presigned S3 URLs embedded directly in the `/api/questions` and `/api/questions/:id` responses (see [Auth & Security](#auth--security)).

**Premium paywall.** Both read endpoints take *optional* auth (`get_current_user_optional`)
so they stay public but can tailor the response to the viewer. For a question whose
paper has `is_premium = true`, when the viewer is not entitled (`can_view_premium` is
false — i.e. anonymous or `public`), the backend **withholds the presigned image URL**
(`first_page_url` / page `url` become `null`) and sets `locked: true` on the item /
detail. The tile and all metadata are still returned, so the frontend can show a
locked placeholder that prompts a subscription. `premium` and `admin` viewers see the
URLs normally.

### Generation — Authenticated (Implemented)

```
POST   /api/generate/select      -- auto-select a set of questions for a target.
                                    Body: { filters, target_type, target_value,
                                    exclude_question_ids[], algorithm }. `filters` mirrors
                                    the Browse filter params (subject_id, stream_id,
                                    level_id, year, school_id, exam_type_id, topic_ids[],
                                    exclusive, paper_number, search). `target_type` is
                                    "marks" (target_value = marks total) or "count"
                                    (target_value = number of questions). `algorithm` is
                                    "random" (default) or "in-order". Returns { items,
                                    total_marks, count, exact, warning }.
POST   /api/generate/paper       -- render a PDF from a manual selection.
                                    Body: { question_ids[] (min 1), variant:
                                    "question"|"answer"|"combined", header_text,
                                    footer_text, include_cover, cover_title,
                                    cover_subtitle1, cover_subtitle2, cover_body }.
                                    "combined" returns one PDF with the answer
                                    paper appended after the question paper.
                                    Each page carries branded header/footer chrome;
                                    the question paper credits each question's source;
                                    a cover page (per section, with a marks box) is
                                    included unless include_cover=false (admins only —
                                    see role enforcement below).
                                    Returns application/pdf. Empty question_ids -> 422.
```

**Role enforcement on `/generate/paper`.** Admins control every field verbatim. For
non-admin users (`public` and `premium`) the admin-set [generation config](#generation-config--cover-titles)
wins (`_resolve_generation_options` in `app/routes/generate.py`):

- `include_cover` is forced to `true` — users always get a cover page.
- `cover_body`, `header_text`, and `footer_text` are replaced with the config presets.
- `cover_title` must be one of the configured cover titles: an unknown title -> `400`
  (a hand-crafted POST can't bypass the dropdown); an empty/omitted title falls back to
  the **first** configured title; with no titles configured the cover is untitled.
- `cover_subtitle1` / `cover_subtitle2` stay free text for everyone.

`POST /api/generate/select` (`app/routes/generate.py`) reuses the Browse filter suite
(`_apply_filters` + the eager-load options from `app/routes/questions.py`) to build the candidate
pool and excludes any `exclude_question_ids`, then dispatches on `target_type` + `algorithm`: for
`"marks"` it runs `knapsack_select` (`"random"`) or `in_order_select` (`"in-order"`); for `"count"`
it runs `count_select` (random sample or first-N). It never returns a 404 — an empty result with a
`warning` string keeps the live builder UI responsive.

**Premium paywall on generation.** For non-premium viewers (`public`), `/generate/select`
filters premium papers out of the candidate pool entirely, and `/generate/paper` returns
`403` if any posted `question_id` belongs to a premium paper (the UI already prevents adding
locked questions; this is the server-side guard). `premium`/`admin` users are unrestricted.

**Toggling a paper's premium flag.**

```
PATCH  /api/papers/{paper_id}/premium  -- set a paper's is_premium flag. Admin only.
                                          Body: { is_premium: bool }. Returns { id, is_premium }.
                                          Unknown paper -> 404. Missing/invalid body -> 422.
```

`app/routes/papers.py::set_paper_premium_route` is a lightweight alternative to the full
metadata `PUT /api/papers/{paper_id}` (which requires every FK id): it loads the paper, sets
`is_premium`, and `db.flush()`es (`get_db` commits on success). It powers the inline Premium
checkbox on the admin Papers list, so an admin can flag/unflag a paper without opening the editor.

`POST /api/generate/paper` renders the question paper, the answer paper, or both combined into a
single PDF, depending on `variant`. Both endpoints require authentication (`get_current_user`),
not admin. See [Paper Generation Engine](#paper-generation-engine-implemented) below.

### Generation Config & Cover Titles (Implemented)

Admin-set presets that drive non-admin generations (see role enforcement above) and pre-fill the
Generate form. Router: `app/routes/generation_config.py`; service:
`app/services/generation_config.py` (`get_or_create_config` lazily creates the singleton row with
the seeded defaults, so the app self-heals on an unseeded database).

```
GET    /api/generation-config    -- any authenticated user. Returns { titles: [{id, name}] (id
                                    order — the first is the non-admin dropdown default),
                                    subtitle1_placeholder, subtitle2_placeholder, cover_body,
                                    header_text, footer_text }. Nothing here is secret (every
                                    value is printed in the PDFs users generate); writes are
                                    what's restricted.
PUT    /api/generation-config    -- admin. Replaces the five preset fields; returns the GET shape.
                                    cover_body is stored as-is and sanitized at render time
                                    (app/pdf/cover_body.py), same as the request path.
GET    /api/cover-titles         -- any authenticated user. { data: [{id, name}] } in id order.
POST   /api/cover-titles         -- admin. Body { name }. Duplicate -> 409. Returns 201.
PUT    /api/cover-titles/:id     -- admin. Body { name }. Duplicate -> 409, unknown id -> 404.
DELETE /api/cover-titles/:id     -- admin. Plain delete (nothing references titles). 204.
```

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
   - Accepts an optional `is_premium` flag (**defaults to `true`** — imported papers are premium unless the admin unticks the box at the final import step).
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

`app/services/generate.py` offers selection by a **marks total** (`target_type="marks"`) or a
**question count** (`target_type="count"`), each with a `"random"` or `"in-order"` `algorithm`, all
exposed via `POST /api/generate/select`.

**Marks target.** Both marks selectors ignore questions with `null` or non-positive `marks` and
return `[]` for a non-positive target or when nothing is selectable.

`knapsack_select(questions, target_marks)` (`algorithm="random"`):

- **Randomized-restart greedy**, not an exact optimizer. Each restart shuffles the pool and greedily
  adds questions until the running total reaches the target, considering every intermediate subset.
  The restart budget scales with pool size (`_RESTARTS_PER_QUESTION = 20`, clamped to `[200, 2000]`).
- Prefers an **exact match**; otherwise returns the subset whose total is closest (a slight overshoot
  is allowed if it lands closer). The randomness is intentional: the same filters/target produce a
  *different* paper each time (equally-good subsets are reservoir-sampled). Stops early on an exact
  match.

`in_order_select(questions, target_marks)` (`algorithm="in-order"`):

- **Deterministic single greedy pass** over the pool in its given (`Question.id`) order that **stops
  at the first question which would exceed the target** — the result never overshoots. No shuffling,
  restarts, or tie-break randomness, so the same filtered pool and target always return the same
  questions from the top of the list.

**Count target.** `count_select(questions, count, *, randomize)` selects a fixed *number* of
questions — `random.sample` of `count` when `algorithm="random"`, else the first `count` in id
order. Unlike the marks selectors it does **not** filter out null-mark questions (the caller is
choosing a count, not a marks total). Returns all matches when `count` exceeds the pool size.

`POST /api/generate/select` also supports an **add-to-selection** flow client-side: the frontend
passes the already-chosen questions in `exclude_question_ids` and reduces `target_value` by their
running total (marks) or count, so autofill tops up an existing selection instead of replacing it
(see [FRONTEND.md](./FRONTEND.md#paper-generation-ui)).

## Paper Generation Engine (Implemented)

`POST /api/generate/paper` (`app/routes/generate.py::generate_paper`) turns a manual selection into
a PDF. `variant="question"` and `variant="answer"` each generate one paper per call — the frontend
calls it twice in the separate-PDFs mode to produce the question and answer papers, which follow
identical layout rules. `variant="combined"` (the frontend's default mode) generates **one PDF**
holding the question paper followed by the answer paper, each section starting on a fresh page and
keeping its own layout rules; the answer section is omitted entirely when no selected question has
answer pages. There is no server-side autofill-at-generate: the selection is already resolved
(manually or via `/generate/select`) before this endpoint is hit.

### Route behavior

- Fetches the selected `Question` rows (eager-loading pages + paper), then **re-sorts them into
  `question_ids` order** (a DB `IN` query is unordered).
- Numbers questions `1..N` in **selection order**. The same numbers are used in both variants: an
  answer keeps the number of its question. For `variant="answer"`, a question with no answer pages
  is **skipped**, but its number stays reserved so the remaining answers still match the question
  paper.
- `header_text` is printed only on the question variant (in `combined`, only on the question
  section's first page).
- Returns `Response(pdf, media_type="application/pdf")`. Empty `question_ids` → 422 (schema).

### Layout engine (`app/pdf/layout_engine.py`)

Works in **300-DPI pixel space** (A4 = 2480×3508 px). Stored images are content-only (≤ 1760 px
wide from ingestion); the engine builds the page margins itself. `LayoutEngine(page_capacity_px,
fit_width, show_credit)` — `page_capacity_px` is the usable vertical budget (the **content band
between the header and footer rule lines** — see [Page chrome](#page-chrome) — not the raw page
height); `fit_width` selects the horizontal treatment per variant:

- **`fit_width=True` (question paper):** each image is scaled (aspect preserved) to a fixed **1760 px
  content width** and drawn **centered** on the page — **360 px margin on each side** (1760 + 360 +
  360 = 2480). All questions therefore render at the same width regardless of their stored size.
- **`fit_width=False` (answer paper):** each image keeps its **native size** (≤ 1760 px), **flush to
  the 360 px left margin**, with the remaining width as right padding. It never overflows (360 + 1760
  < 2480). A **100 px vertical gap** separates one question's answer block from the next (`block_gap_px`);
  multiple answer pages of the same question stack with no extra gap.

Both variants draw the question number into the **360 px left margin**, right-aligned just left of
the image.

Rendering is split so sections can share a document: `LayoutEngine.render_onto(canvas, plan,
fetch_bytes)` draws a plan onto an existing ReportLab canvas (ending on a fresh page), and
`render(plan, fetch_bytes)` wraps it for a standalone PDF. The module-level
`render_combined(sections, fetch_bytes)` takes `(engine, plan)` pairs and renders them into one
PDF — how the `combined` variant appends the answer paper after the question paper.

- `compute_layout(blocks, header_text="") -> LayoutPlan`: greedy **packing** — keeps a running
  cursor and places each block (one question's pages for this variant) on the current page. A block
  starts a new page only when its **first page-image** (plus its credit band) won't fit in the space
  left — so a multi-page question packs its first page onto the current page when there is room and
  **flows its remaining pages onto following pages**, rather than jumping the whole question to a
  fresh page. Two short consecutive questions therefore share a page; a block taller than a whole
  page still starts wherever its first page fits. Heights use the variant's scale (`_image_scale`),
  with a page-tall image clamped to `page_capacity_px` (`_page_height_px`); the block-start test uses
  `_first_unit_height_px` (credit band + first page). Header height is reserved on the first page.
  The walk mirrors `render_onto`'s per-image flow, so `page_count` counts multi-page overflow pages
  too (render remains authoritative).
- `render(plan, fetch_bytes) -> bytes`: **ReportLab** canvas at A4, scaling px→points. For each
  block it places the page image(s) (`fetch_bytes(image_key)` → Pillow → `ImageReader`) at the
  variant's scale and left offset, then draws the **number in the left margin**, right-aligned just
  left of the image's edge and nudged slightly below the block's top (drawn *after* the image so it
  is never covered). Page-breaks per image; an image taller than the page is scaled to fit. In
  production `fetch_bytes` is `get_image_bytes`; the `variant="answer"` call only fetches answer
  bytes and vice-versa, so no image is fetched twice across the two requests.

Dataclasses: `Block(label, source_label, pages, page_index)`,
`LayoutPlan(page_count, blocks, header_text, footer_label, cover)`, and
`CoverSpec(title, subtitle1, subtitle2, body, total_marks, is_questions)`.

**Per-question source credit (`show_credit`):** on the question paper, each block is drawn with a
small grey provenance line just above its image — `source_label`, formatted
`[{School}/{Year}/{ExamType}/{paper_number}/Q{original_number}]` (e.g.
`[Bendemeer Secondary School/2024/Prelim/2/Q6]`; `paper_number` is stored bare and rendered as-is).
The credit line is drawn at `_CREDIT_FONT_PX = 40` (~11.5pt at 300 DPI).
`LayoutEngine(show_credit=True)` reserves a fixed band (`_CREDIT_BAND_PX`) in each
block's height so packing and rendering stay in sync, then draws the line and advances the cursor
before the image. The route enables it for the `question` variant (and the `combined` PDF's
question section) and leaves it off for the answer paper. Blocks with an empty `source_label`
reserve no band.

### Page chrome

Every page carries branded furniture, drawn by `LayoutEngine._draw_chrome` once per page:

- **Purple rule lines** (`PURPLE ≈ #776687`) near the top (`_HEADER_LINE_Y_PX = 310`) and bottom
  (`_FOOTER_LINE_Y_PX`), inset `_MARGIN_X_PX` on each side. The **content band sits between them**
  (`_CONTENT_TOP_PX … _CONTENT_BOTTOM_PX`), which is what `_DEFAULT_CAPACITY_PX` measures. The header
  rule sits far enough down the page that the full-size logo clears it above the line.
- **Logo** top-left, sitting **fully above** the header rule — its bottom edge a small
  `_LOGO_RULE_GAP_PX` gap above the line (not centered on it). Loaded from
  `app/pdf/assets/pillora_logo.png` (`LOGO_PATH`) via `_load_logo` (cached, aspect-preserved to
  `_LOGO_W_PX`). The asset is **optional**: if absent/unreadable the page renders without it (no
  error).
- **Website** (`WEBSITE = www.pillora.com.sg`) centered on the header rule, with a clickable
  link annotation (`canvas.linkURL`) pointing at `WEBSITE_URL`.
- **Footer label** (`LayoutPlan.footer_label`) centered under the footer rule, plus **`Page {n}`**
  bottom-right. The route sets the footer label to the resolved `footer_text` **verbatim** —
  admins' request field, or the generation-config preset for non-admins. The same text appears on
  every section (the old subtitle2-derived `"… Questions"` / `"… Answers"` labels are gone —
  identical footers on the question and answer sections are intentional).

Page numbers **restart at 1 for each section** (each `render_onto` call), so in the `combined`
PDF the question and answer papers number independently. The free-text `header_text` instructions
still render on the first content page, below the header rule.

### Cover page

When `LayoutPlan.cover` is set (a `CoverSpec`), `render_onto` draws a branded cover as the
section's **first page** (page 1), then content starts on page 2 (`_draw_cover` →
`_draw_marks_box`). The cover shows: the logo centered near the top; an editable **title**;
**subtitle 1** with `" – Questions"`/`" – Answers"` appended per variant (`is_questions`); an
editable **subtitle 2**; the editable **letter body**; a **marks box top-right**
(`______ / {total}`); a copyright line; and the standard chrome. A cover-only section (no blocks)
stays a single page.

The letter body is **rich text**: HTML limited to paragraphs plus bold / italic / underline /
link. `app/pdf/cover_body.py` (`to_paragraphs`) whitelists exactly that subset — unknown tags are
stripped (text kept), all text is escaped, `href`s are restricted to `http(s)`/`mailto` (bare
`www.` gets `https://` prefixed), and the emitted markup is always balanced. The result feeds
Platypus `Paragraph` objects, which handle the word-wrap and emit **clickable link annotations**
in the PDF (links render blue + underlined). Plain text with no tags is accepted as the legacy
newline-separated format, so older API clients keep working.

The route (`generate_paper`) computes `total_marks = sum(q.marks or 0 …)`, resolves the
effective cover values by role (`_resolve_generation_options` — admins use the request's
`cover_*` fields verbatim; non-admins get the generation-config presets and a validated title),
builds a `CoverSpec` per section (question section `is_questions=True`, answer section `False`),
and includes it unless covers are disabled (admins only — non-admins always get one). In
`combined`, a cover is prepended to **each** section. The canonical default cover title/body live
in `app/services/generation_config.py` (`DEFAULT_COVER_TITLE`, `DEFAULT_COVER_BODY`): they seed
the `generation_config` row and `cover_title` list in the Alembic migration, and
`GET /api/generation-config` serves the live config so the frontend pre-fills the editable fields
without keeping its own copy.

### Library

ReportLab (in `requirements.txt`) drives the per-page cursor + image flow; Pillow decodes the stored
WebP page images.

### Local sample generation & visual self-verification

Two scripts (`scripts/generate_sample_pdf.py`, `scripts/pdf_to_images.py`) drive the real layout
engine with no database, S3, or network, then rasterize the output for visual inspection — the
workflow for verifying layout changes without standing up infrastructure. See
[PDF_GENERATION_TESTING.md](./PDF_GENERATION_TESTING.md).

## Auth & Security

- **Passwords:** bcrypt via `bcrypt.gensalt()` (default cost factor 12). Implemented.
- **Auth tokens:** JWT (`python-jose`, HS256) in an `httpOnly`, `secure`, `samesite=lax` cookie named `access_token`, 7-day expiry. `JWT_SECRET_KEY` read from env (falls back to an insecure default — **must** be set in production). Implemented.
- **Admin routes:** `require_admin` dependency (in `app/routes/auth.py`) checks `user.role == "admin"`, returns `403` otherwise. Applied to all `POST/PUT/DELETE` on reference data, all `/api/import/*` routes, and the `/api/users` management routes. Implemented.
- **Roles / premium tier:** three tiers — `admin`, `public` ("Normal"), `premium`. `can_view_premium(user)` (in `app/routes/auth.py`) returns true for `admin`/`premium`. `get_current_user_optional` is the non-raising variant used by the public browse endpoints so they can tailor responses to the viewer's tier. Implemented.
- **Image access:** images are never proxied through the backend — every question/page response embeds an S3 **presigned URL** (`get_presigned_url`), keeping VM bandwidth free for HTML/JSON. The premium paywall works *by withholding this URL*: for a premium paper viewed by a non-entitled user, the backend simply omits `get_presigned_url` and returns `null` + `locked: true`, so the URL never reaches an unauthorized client. Implemented.
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
