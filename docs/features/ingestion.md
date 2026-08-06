# Ingestion

**Scope:** Getting exam papers into the bank and maintaining them — the admin import wizard, the
server-side PDF→image pipeline, and the Manage Papers editor. The AI part-split/topic step that
follows import is in [ai-labelling.md](./ai-labelling.md); filename metadata extraction is there
too.

## Import API — admin only

```
POST   /api/import/upload-pdf       -- upload a single PDF; returns page images + AI-suggested metadata
POST   /api/import/confirm          -- submit labeled paper + questions
POST   /api/import/ai-topics        -- AI part split + topic/marks suggestions for one question
POST   /api/import/save-topics      -- persist user-reviewed parts for a paper's questions
DELETE /api/import/papers/{paper_id} -- delete a paper, its questions/pages, and their S3 objects
```

The two AI-topics routes are documented in [ai-labelling.md](./ai-labelling.md).

## Server-side pipeline

### 1. `POST /api/import/upload-pdf`

- Accepts a single PDF (multipart). Non-PDF content types → `422`.
- **PyMuPDF** renders every page to an RGB image at 300 dpi.
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
