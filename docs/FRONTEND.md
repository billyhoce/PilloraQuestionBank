# Frontend

**Scope:** React SPA — all browser-side UX. The import flow's user-facing steps live here; the server-side processing is in [BACKEND.md](./BACKEND.md). For data shapes (filter values, result rows), see [DATA_MODEL.md](./DATA_MODEL.md). For the AI review UI specifically, see [AI_INTEGRATION.md](./AI_INTEGRATION.md).

## Stack

- **Framework:** React (with Vite for dev/build)
- **Type:** SPA (single-page app)
- **Styling:** developer's choice — pick once and stick to it (Tailwind, CSS Modules, or vanilla CSS all fine at this scale)

## Testing

- **Runner:** [Vitest](https://vitest.dev/) with `jsdom` + React Testing Library (`@testing-library/react`, `@testing-library/jest-dom`).
- **Run:** `cd frontend && npm test` (also runs in CI's `frontend-build` job).
- **Location:** tests are colocated with the code they cover as `*.test.js` / `*.test.jsx`; shared setup lives in `src/test/setup.js` (registers jest-dom matchers), configured via the `test` block in `vite.config.js`.
- **Convention:** import test APIs explicitly (`import { describe, it, expect, vi } from 'vitest'`) — vitest globals are not enabled.

## Page Layout Convention

Content pages span ~90% of the viewport: the page-level wrapper uses `max-w-[90%] mx-auto` (Browse, Generate, admin Reference, Papers list/editor, import Topic Review). Exceptions: the import review grid is already full-width under the app shell, and the Login/Register auth cards stay narrow (`max-w-sm`).

## Topic Display Convention

Topics are always displayed with their topic number as a `T{n}:` prefix, e.g. **"T1: Algebra"** — on Browse question cards, the topic filter chips, the AI topic-labelling review, the paper editor's topic labels, and the add-topic combobox. Use the shared helper `formatTopic(topicNumber, name)` in `src/utils/topicFormat.js` (falls back to the bare name when no number is available). The admin Topics tab shows the number in its own editable column instead. The keyword search matches the `T{n}` token too (e.g. typing "T10" surfaces questions tagged topic number 10).

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

## Navigation (App Shell)

All main routes (`/`, `/generate`, `/admin/*`) render inside a shared `<AppShell />`
(`src/components/AppShell.jsx`) — a role-aware menubar (`<NavBar />`) plus the page content.
`/login` and `/register` stay outside the shell. The menubar is always fully visible for the
user's role — there is no "Admin" button to unlock it:

- **Everyone:** Question Bank (`/`), Generate Paper (`/generate` — signed-out clicks land on
  `/login` via `ProtectedRoute`).
- **Admins additionally:** Reference, Import, Papers.
- **Top right:** signed-in users get an account button (their email) opening a dropdown
  (`<UserMenu />`) with **Log out** (closes on outside click / Escape; logging out returns to
  `/`). Signed-out visitors see a **Log in** link instead.

## Import Flow UI (Admin)

The full UX sequence the admin walks through. Each step is a UI state in the same page (or a wizard).

### Step 1 — Upload PDF(s)
- Drag-drop zone. Accepts multiple PDF files.
- Multiple files are appended in upload order (preserved through the flow).

### Step 2 — Server processes PDF → Page Images
- After upload, frontend shows a loading state while the server renders pages.
- Server returns image URLs for every page (see `POST /api/import/upload-pdf` in [BACKEND.md](./BACKEND.md)).

### Step 3 — Grid Preview
- Render all returned page images as a thumbnail grid — **max 5 pages per row** (fewer on narrow
  screens), thumbnails at an A4 aspect ratio so they scale with the cell width.
- Click a thumbnail to open a **lightbox / zoom modal**.

### Step 4 — Auto-label Questions
- On entering this step, every page is auto-assigned `Q1, Q2, Q3, ...` sequentially.
- Render the assigned label on each thumbnail.

### Step 5 — Manual Adjust (Merge Pages into One Question)
- Each page has a "Merge with prev" toggle (e.g. "this is Q2 continued") — available both on the thumbnail and inside the lightbox, so pages can be merged while paging through the zoomed images without leaving fullscreen.
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
- **Paper Number** — free-text input, case-insensitive exact match (values may contain letters, e.g. "1", "a")
- **Topic** — multi-select, **scoped to selected Subject + Stream** (greyed out until both are chosen)
- **Subtopic** — multi-select, **scoped to selected Topic(s)**
- **Search** — free-text keyword box. Runs **live as the user types**, debounced ~300ms after the last keystroke (Enter or the Search button commit instantly); clearing the box returns to all questions. Matches topic/subtopic/tag/school/subject/level/school-level tier ("Secondary")/stream/exam-type names, the `T{n}` topic-number token, and — for an all-digit keyword — the paper year.

### Results View

- Grid (or list) of matching questions.
- Each card shows: thumbnail of first page, paper-local question number, paper info (school / year / level / exam type), marks, topic chips.
- **Click to expand** — show all pages of the question (use the same `<Lightbox />` as the import flow).
- **Pagination or infinite scroll.**

## Paper Generation UI

`/generate` (`src/pages/GeneratePage.jsx`), authenticated-only. A single page combining manual
selection and marks-based autofill — not separate tabs. Reached via the "Generate Paper" link in
the shared menubar. Layout: filtered results on the left, a sticky sidebar (autocreate panel +
selection cart) on the right.

### Filtered results (left)
- Reuses the Browse `<FilterBar />` and `<QuestionCard />` (in `selectable` mode) plus paginated
  "Load more". Each card shows an `+ Add` / `✓ Added` toggle and the question's marks.
- Clicking a card's preview opens the shared `<QuestionDetailModal />`.

### Manual selection cart (right)
- Adding/removing questions maintains a **selection cart** — full list-item objects, de-duped by id.
- Cart lists each question (school / year / Q-number, marks) with a remove button, a running
  **total marks**, and a warning when any selected question has no marks set. "Clear" empties it.

### Autocreate panel (right)
- A **target marks** number input plus a **Replace selection / Add to selection** radio.
- "Autocreate Paper" calls `POST /api/generate/select` with
  `{ filters, target_marks, exclude_question_ids }`:
  - **Replace** — sends the raw target; the response items become the new cart.
  - **Add** — sends `target_marks - cartTotalMarks` and the current cart ids as
    `exclude_question_ids`, so the picked questions top up the existing selection (guards against a
    non-positive remaining target).
- Surfaces the server's `warning` (e.g. inexact total, no matches) or a success summary as an inline
  notice.

### Generate PDF (right)
- **Cover page** controls: an **"Include cover page"** checkbox (on by default) revealing editable
  **title** (default "Topical Worksheets"), **subtitle 1** (topic/subject), **subtitle 2** (e.g.
  "2024 Prelim"), and a **letter body** `<textarea>` pre-filled with `DEFAULT_COVER_BODY` (a JS
  constant mirroring the backend default). These map to `include_cover, cover_title,
  cover_subtitle1, cover_subtitle2, cover_body` in the request body and are sent on **every** call
  (the answer PDF's cover reads "Answers"). The cover's marks box is filled server-side from the
  selected questions' total.
- Optional **header / instructions** `<textarea>` printed on the first page of the question PDF.
- A **"Download as"** radio selector chooses the output mode, defaulting to **1 combined PDF**:
  - **Combined (default):** one call to `api.generate.paper` with `variant: "combined"` (and
    `header_text`); the single blob downloads as `{timestamp}_paper.pdf` — question paper first,
    answer paper appended behind it.
  - **Separate:** calls `api.generate.paper` **twice in parallel** — `variant: "question"` (with
    `header_text`) and `variant: "answer"` — downloading `{timestamp}_question.pdf` and
    `{timestamp}_answer.pdf` (one shared client-generated timestamp; a short gap between the two so
    browsers don't drop the second download).
- Each call returns a PDF `Blob` (a binary fetch that bypasses the JSON-only `request` helper) and
  auto-downloads via a local `downloadBlob` helper.
- **Generate PDF** button (enabled once the cart is non-empty). An **estimated progress bar**
  (client-side only, no backend streaming) eases toward ~90% while the requests are in flight, then
  snaps to 100% on completion. Errors surface as an inline notice.
  See [BACKEND.md](./BACKEND.md#paper-generation-engine-implemented).

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

- `/login`, `/register`; **Log out** lives in the menubar's account dropdown (`<UserMenu />`, see
  [Navigation](#navigation-app-shell)).
- After login (and for already-authenticated visits to `/login`/`/register`), **all roles redirect
  to `/`** (Question Bank).
- Role-aware routing: redirect non-admins away from `/admin/*`.
- Persist session in `httpOnly` cookie (set by backend) — no token handling in JS.
