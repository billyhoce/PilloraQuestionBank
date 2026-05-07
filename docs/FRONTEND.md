# Frontend

**Scope:** React SPA — all browser-side UX. The import flow's user-facing steps live here; the server-side processing is in [BACKEND.md](./BACKEND.md). For data shapes (filter values, result rows), see [DATA_MODEL.md](./DATA_MODEL.md). For the AI review UI specifically, see [AI_INTEGRATION.md](./AI_INTEGRATION.md).

## Stack

- **Framework:** React (with Vite for dev/build)
- **Type:** SPA (single-page app)
- **Styling:** developer's choice — pick once and stick to it (Tailwind, CSS Modules, or vanilla CSS all fine at this scale)

## Routes / Pages

| Path | Page | Access |
|---|---|---|
| `/login` | Login | Public |
| `/register` | Register | Public |
| `/` or `/browse` | Browse / Filter questions | Authenticated |
| `/questions/:id` | Question detail (all pages) | Authenticated |
| `/generate` | Paper generation | Authenticated |
| `/admin/import` | Import flow | Admin |
| `/admin/reference` | Reference data CRUD | Admin |
| `/admin/users` | User management | Admin |

## Import Flow UI (Admin)

The full UX sequence the admin walks through. Each step is a UI state in the same page (or a wizard).

### Step 1 — Upload PDF(s)
- Drag-drop zone. Accepts multiple PDF files.
- Multiple files are appended in upload order (preserved through the flow).

### Step 2 — Server processes PDF → Page Images
- After upload, frontend shows a loading state while the server renders pages.
- Server returns image URLs for every page (see `POST /api/import/upload-pdf` in [BACKEND.md](./BACKEND.md)).

### Step 3 — Grid Preview
- Render all returned page images as a thumbnail grid.
- Click a thumbnail to open a **lightbox / zoom modal**.

### Step 4 — Auto-label Questions
- On entering this step, every page is auto-assigned `Q1, Q2, Q3, ...` sequentially.
- Render the assigned label on each thumbnail.

### Step 5 — Manual Adjust (Merge Pages into One Question)
- Each page has a "merge with previous" toggle (e.g. "this is Q2 continued").
- When a page is marked as a continuation, **all subsequent pages auto-renumber** (Q4 → Q3, Q5 → Q4, etc.).
- Visual cue (e.g. left bracket grouping) for which pages belong to the same question.

### Step 6 — Set Q/A Divider
- Click between two adjacent pages, or drag a divider line, to mark where Questions end and Answers begin.
- Pages after the divider auto-relabel as `A1, A2, A3, ...`.
- Answer pages also support multi-page merging (same UI as step 5).

### Step 7 — Set Paper Metadata (Sidebar)
- Sidebar form with dropdowns populated from reference tables:
  - Subject, Stream, Level, School, Exam Type
  - Year (number), Paper Number (string: "1", "2", "a", "b")
- **AI pre-fill:** when the upload completes, call AI filename extraction (see [AI_INTEGRATION.md](./AI_INTEGRATION.md)) and pre-populate the form. User confirms or edits.

### Step 8 — Confirm Upload
- Show a summary: # questions, # answers, metadata.
- On confirm, call `POST /api/import/confirm`. Saves Paper + Questions + QuestionPages and uploads images to canonical paths.

### Step 9 — AI Topic Labeling (Review)
- After confirm, frontend calls `POST /api/import/ai-topics` and shows progress.
- For each question, render: question image(s) + AI-suggested topic/subtopic chips.
- User can accept, modify, or replace suggestions before saving. See [AI_INTEGRATION.md](./AI_INTEGRATION.md).

### Step 10 — Set Marks
- Per-question numeric input.
- Save to `Question.marks` via API.

### Components Suggested

- `<UploadDropZone />`
- `<PageGrid />` + `<PageThumbnail />` + `<Lightbox />`
- `<QuestionGroupingControls />` (the merge / un-merge toggle, with auto-renumbering)
- `<QADivider />`
- `<MetadataSidebar />`
- `<TopicReviewer />` (step 9)
- `<MarksEntry />` (step 10)

## Browse / Filter UI

### Filter Panel — all optional, combinable

- **Subject** — single-select dropdown
- **Stream** — single-select dropdown
- **Level** — single-select dropdown
- **Year** — single-select dropdown OR range
- **School** — multi-select
- **Exam Type** — multi-select
- **Topic** — multi-select, **scoped to selected Subject + Stream** (greyed out until both are chosen)
- **Subtopic** — multi-select, **scoped to selected Topic(s)**

### Results View

- Grid (or list) of matching questions.
- Each card shows: thumbnail of first page, paper-local question number, paper info (school / year / level / exam type), marks, topic chips.
- **Click to expand** — show all pages of the question (use the same `<Lightbox />` as the import flow).
- **Pagination or infinite scroll.**

## Paper Generation UI

Two modes selectable via a tab/toggle:

### Manual Selection
- Filter questions (reuses the Browse filter panel).
- Add/remove questions to a "selection cart" sidebar.
- Cart shows per-question marks and running total.
- "Generate" button enabled when cart has ≥ 1 question.

### Auto-fill by Marks
- Filter inputs (same as above) **plus** a target-marks number input.
- "Generate" hits `POST /api/generate/paper` with `{ filters, target_marks }`.

### Common Options
- **Header / instructions text** — multi-line text input rendered on the first page of the generated PDF.
- **Include answers** — toggle (appends answer pages).
- On submit, the response is a PDF file → trigger a browser download.

## Admin CRUD UI

A simple management surface — list / create / edit / delete — for each of:

- Subjects
- Streams
- Levels (with `sort_order`)
- Schools
- Exam Types
- Topics (scoped to a Subject + Stream; includes `topic_number` and a nested editor for Subtopics)

### User Management
- List users.
- Promote/demote between `public` and `admin`.
- Delete accounts.

## Auth UI

- `/login`, `/register`, logout button in app shell.
- Role-aware routing: redirect non-admins away from `/admin/*`.
- Persist session in `httpOnly` cookie (set by backend) — no token handling in JS.
