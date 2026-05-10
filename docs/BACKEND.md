# Backend

**Scope:** FastAPI server — API endpoints, import pipeline (server side), PDF generation engine, auth/security, object-store integration. For database schema, see [DATA_MODEL.md](./DATA_MODEL.md). For AI calls (topic labeling, filename extraction), see [AI_INTEGRATION.md](./AI_INTEGRATION.md). For frontend UX flows, see [FRONTEND.md](./FRONTEND.md).

## Stack

- **Python:** 3.11+
- **Framework:** FastAPI (REST API; first-class Pydantic validation; first-class Anthropic SDK)
- **PDF → Image:** `pdf2image` (Python) backed by **Poppler** (system dependency)
- **Image processing:** Pillow / WebP encoder
- **PDF generation:** ReportLab or FPDF2
- **Auth:** bcrypt for password hashing, JWT (httpOnly cookie) or server-side sessions

## Suggested Project Layout

```
app/
├── routes/         # FastAPI route handlers (one file per resource)
├── models/         # Pydantic request/response models + ORM models
├── services/       # business logic (import, generation, auth)
├── pdf/            # PDF parsing (in) and PDF rendering (out)
├── storage/        # AWS S3 client + signed URL helpers
├── ai/             # Claude API clients (see AI_INTEGRATION.md)
└── main.py
```

## API Endpoints

### Auth (Implemented)

```
POST   /api/auth/register       -- public registration
POST   /api/auth/login          -- returns JWT/session
POST   /api/auth/logout
```

### Reference Data — Admin write, Public read (Implemented)

```
GET|POST|PUT|DELETE  /api/school-levels
GET|POST|PUT|DELETE  /api/subjects
GET|POST|PUT|DELETE  /api/streams
GET|POST|PUT|DELETE  /api/levels
GET|POST|PUT|DELETE  /api/schools
GET|POST|PUT|DELETE  /api/exam-types
GET|POST|PUT|DELETE  /api/topics          -- filtered by ?subject_id=&stream_id=
GET|POST|PUT|DELETE  /api/subtopics       -- filtered by ?topic_id=
```

### Import — Admin only

```
POST   /api/import/upload-pdf    -- upload PDF(s); returns page images
POST   /api/import/confirm       -- submit labeled paper + questions
POST   /api/import/ai-topics     -- trigger AI topic labeling for a paper
```

### Questions — Public read

```
GET    /api/questions             -- filter params: subject_id, stream_id,
                                     level_id, year, school_id, exam_type_id,
                                     topic_id, subtopic_id
                                  -- returns paginated question list with metadata
GET    /api/questions/:id         -- full question detail + image URLs
GET    /api/questions/:id/image/:page  -- serve image (or signed object store URL)
```

### Generation — Public

```
POST   /api/generate/paper       -- body: { question_ids[], header_text,
                                     include_answers: bool }
                                  -- OR: { filters, target_marks, header_text }
                                  -- returns: PDF file download
```

## Import Pipeline (Server Side)

The frontend drives the UX flow (see [FRONTEND.md](./FRONTEND.md)). Server-side responsibilities:

1. **`POST /api/import/upload-pdf`**
   - Accept one or more PDFs (multipart upload).
   - For each PDF, use `pdf2image` (Poppler) to render every page to an image.
   - Apply image standardization per [DATA_MODEL.md → Image Dimension Standards](./DATA_MODEL.md#image-dimension-standards): keep original height, pad/normalize width to 2480 px @ 300 dpi, add 180 px left margin.
   - Encode WebP at quality 85 (fall back to JPEG if needed).
   - Store images in a temporary location keyed to a session/upload-id, return image URLs (or signed URLs) for the frontend grid preview.
   - Optionally call AI filename extraction (see [AI_INTEGRATION.md](./AI_INTEGRATION.md)) and return suggested metadata.

2. **`POST /api/import/confirm`**
   - Accept the labeled structure: paper metadata + ordered list of questions, each with its pages, page order, and `page_type` (`question` or `answer`).
   - Create `Paper`, `Question`, and `QuestionPage` rows transactionally.
   - Move images from the temp location into the canonical object-store key pattern: `papers/{paper_id}/q{question_number}/{page_type}_{page_order}.webp`.
   - Persist `width_px` and `height_px` per page.

3. **`POST /api/import/ai-topics`**
   - Triggered by frontend after confirm.
   - For each `Question` in the paper, call Claude with question images + valid topic list for the subject. See [AI_INTEGRATION.md → Topic Auto-labeling](./AI_INTEGRATION.md).
   - Persist suggestions to `QuestionTopic` (or stage them for user review — frontend decides).

## Paper Generation Engine

Implements `POST /api/generate/paper`.

### Inputs (two modes)

1. **Manual selection:** `{ question_ids: [...], header_text, include_answers }`
2. **Auto-fill by criteria:** `{ filters, target_marks, header_text, include_answers }` — server selects questions whose marks sum to the target.

### Auto-fill Algorithm

Greedy / knapsack selection over questions matching `filters`. Prefer **exact match** to `target_marks`; otherwise return the closest combination. (At v1 scale, a simple iterative approach is fine.)

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

### Library

Use **ReportLab** (more mature, better image control) or **FPDF2** (lighter). ReportLab is recommended for the per-page cursor + image flow.

## Auth & Security

- **Passwords:** bcrypt with salt rounds ≥ 12.
- **Auth tokens:** JWT in `httpOnly` cookie, OR server-side sessions. Either works at this scale.
- **Admin routes:** middleware that checks `user.role === 'admin'`. Apply to all `POST/PUT/DELETE` on reference data and all `/api/import/*`.
- **Image access:** prefer **S3 presigned URLs** (time-limited) over proxying through the backend, to keep VM bandwidth free for HTML/JSON.
- **Input validation:** all API inputs as Pydantic models with strict types.
- **CORS:** lock to your production domain only.
- **Rate limiting:** basic limiter on `/api/auth/*` to slow credential stuffing.

## Object Store Integration

- AWS SDK for Python — `boto3`.
- Helpers in `app/storage/`:
  - `put_image(key, bytes)` — used during import (`s3.put_object(Bucket=..., Key=key, Body=bytes, ContentType="image/webp")`).
  - `get_presigned_url(key, expires_in_seconds)` — used when serving images to the frontend (`s3.generate_presigned_url("get_object", ...)`).
- All keys follow the pattern documented in [DATA_MODEL.md](./DATA_MODEL.md#image-storage-conventions).
- **Local dev:** point `boto3` at MinIO (S3-compatible) by setting `endpoint_url` from an env var that's empty in production. Same code path, no special-casing.
