# Ingestion

**Scope:** getting papers into the bank and maintaining them. This file covers the **Manual** import,
the Manage Papers editor and provenance.

Related docs:
- **Auto-detect** import (jobs, worker, review): [auto-import.md](./auto-import.md).
- Answer booklets and matching: [qa-pairing.md](./qa-pairing.md).
- AI part split, topics and metadata extraction: [ai-labelling.md](./ai-labelling.md).

## Three pages

The import area (`ImportLayout.jsx`) is three pages under one sub-navigation. `/admin/import` itself
redirects to Auto import, or to Manual import when a manual import is in progress in
`sessionStorage` (so a reload or a review page's **Handle manually** lands back on it).

| Page | Input | Who splits the booklet | Result |
|---|---|---|---|
| **Auto import** (`/admin/import/auto`) | Whole booklets, one job each | Worker pipeline | Jobs, which move to the review queue when processed |
| **Review queue** (`/admin/import/review`) | Processed jobs | Admin checks and corrects the proposal | One or more papers per booklet |
| **Manual import** (`/admin/import/manual`) | One paper's PDF | The admin, in the wizard | One paper |

The tabs carry live counts: files uploading (Auto import) and jobs ready for review (Review queue).

## Import API (admin only)

| Route | Behaviour |
|---|---|
| `POST /api/import/upload-pdf` | Manual. Multipart PDF (non-PDF → `422`). Renders pages, returns `{pages, suggested_metadata}`. |
| `POST /api/import/confirm` | Creates the paper, its questions and pages from temp images. |
| `POST /api/import/ai-topics`, `POST /api/import/save-topics` | Part split / topic labelling; see [ai-labelling.md](./ai-labelling.md). |
| `DELETE /api/import/papers/{paper_id}` | Deletes a paper (same as `DELETE /api/papers/{id}`). |
| `/api/import/uploads`, `/api/import/jobs/…`, `/api/import/papers/pending` | Auto-detect; see [auto-import.md](./auto-import.md#routes). |

Upload routes are plain `def` (run in the thread pool, reading `file.file.read()`), so a large PDF
never blocks other requests. This also applies to `POST /api/papers/upload-image`.

### `POST /api/import/upload-pdf`

- Renders each page at 300 dpi (PyMuPDF), **one page at a time**: render, standardise, encode,
  upload, free. Memory peaks at about one page.
- Standardise: content only (no margin). Width is capped at 1760 px (downscale only, aspect kept).
  See [DATA_MODEL.md](../DATA_MODEL.md#image-dimension-standards).
- Saves WebP q85 to `tmp/{upload_id}/page_{i}.webp`. Returns presigned URLs (2 h) and each page's
  size.
- **Always** returns `suggested_metadata` from the filename
  ([ai-labelling.md](./ai-labelling.md#paper-metadata-extraction)).

### `POST /api/import/confirm`

- **Input:** paper metadata, `is_premium` (default **true**), and ordered questions, each with its
  pages (`temp_key`, `page_type`, `page_order`, `width_px`, `height_px`).
- **Rejected with `422` (`school_level_conflict`)** if the stream and level belong to different
  school levels ([users-and-premium.md](./users-and-premium.md)).
- **Creates** the `Paper`, `Question` and `QuestionPage` rows, plus one blank `QuestionPart` per
  question. Topics and marks come at the review step.
- **Images:**
  - Copied to `papers/{paper_id}/q{n}/{page_type}_{page_order}.webp` before the commit.
  - Temp keys are deleted after it. A failed temp delete is logged and skipped; the `tmp/` lifecycle
    rule and the reconciler clean up.
  - If anything fails, nothing is committed and the canonical copies are removed.
- **After creating the paper:** re-runs answer matching for pending answer-only papers
  ([qa-pairing.md](./qa-pairing.md#automatic-matching)).
- **Returns** `paper_id` and the questions/pages with fresh presigned URLs.

### Deleting a paper

- Deletes the row and cascades to its questions, pages, parts, topics and subtopics.
- S3 objects are deleted **after** the commit.
- If the paper came from an ingest job, a `paper_deleted` event is recorded on that job.

## Manual wizard UI

Each step is a state of one page.

1. **Upload:** a drop zone for multiple PDFs, kept in upload order.
2. **Processing:** a loading state while pages render.
3. **Grid:** thumbnails at A4 aspect, at most 5 per row. Click one to open a lightbox.
4. **Auto-label:** pages are numbered `Q1, Q2, …`.
5. **Merge:** "Merge with prev" on each thumbnail and in the lightbox. Later pages renumber
   automatically, and a bracket groups a question's pages.
6. **Q/A divider:** click or drag between pages. Pages after it become `A1, A2, …` and can be merged
   the same way.
7. **Metadata sidebar:** subject, stream, level, school, exam type (from the reference tables), year,
   paper number (string: "1", "2", "a", …) and **Premium** (ticked by default). Pre-filled from the
   filename; the admin edits.
8. **Confirm:** a summary (# questions, # answers, metadata), then `POST /api/import/confirm`.
9. **Part split, topics and marks:** see
   [ai-labelling.md](./ai-labelling.md#the-review-step-topicreviewjsx). There is no separate marks
   step.

Components: `UploadDropZone`, `PageGrid` + `PageThumbnail` + `Lightbox`, `QuestionGroupingControls`,
`QADivider`, `MetadataSidebar` (also used on the auto-import review page), `PartsEditor`.

## Editing an imported paper

`/admin/papers` lists papers; `PaperEditor.jsx` opens one. Each question is a `QuestionEditor.jsx`
card with its number, page-image editors, tags and a `PartsEditor`.

| Route | Behaviour |
|---|---|
| `POST /api/papers/{id}/questions` | `{question_number, parts, tag_ids, pages}` |
| `PUT /api/questions/{id}` | Same shape |
| `PUT /api/papers/{paper_id}` | Full metadata update (every FK id required) |

- **No question-level marks.**
  - Input: `parts: [{label, marks, topic_assignments}]`.
  - Output: `marks` (the sum) plus `parts: [{part_order, label, marks, selections}]`.
  - See [ai-labelling.md](./ai-labelling.md#the-shared-parts-write-path).
- **Re-run AI** re-labels one question (`ai-topics`) and replaces its parts.
- **Changing the paper's subject or stream** re-labels every question. Topic assignments out of the
  new (subject, stream) scope are cleared; the parts and their marks survive.
- **Page edits** go through the same copy-before-commit, delete-after-commit rule, with
  collision-safe `page_order`.
- **Premium checkbox:** [users-and-premium.md](./users-and-premium.md#flagging-a-paper-premium).

## Provenance

Content confirmed from an auto-import job records its origin. All fields are nullable, and Manual
imports leave them null.

| Column | Value |
|---|---|
| `paper.source_job_id` | The ingest job |
| `question.section` | The paper's question label (`q1`), or its answer label for an answer-only paper |
| `question.proposal_question_index` | 0-based position in the proposal paper's `questions` |
| `question_page.source_page` | Booklet page number (as in the proposal) |
| `question_page.source_rect` | `{x0, y0, x1, y1}` in PDF points |

Attached answer pages carry the provenance of the job they came from. From a paper id, the job list
search finds its job; see [auto-import.md](./auto-import.md#job-list-ui).
