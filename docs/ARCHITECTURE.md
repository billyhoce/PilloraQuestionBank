# Architecture

**Scope:** The orientation doc — stacks, code layout, and the cross-cutting conventions every
feature obeys. Feature behaviour lives in [`features/`](./features); schema lives in
[DATA_MODEL.md](./DATA_MODEL.md).

```
Browser (React SPA)
    │  HTTPS
    ▼
Nginx (static + reverse proxy)  ── Oracle Cloud VM ──┐
    │  /api/*                                        │
    ▼                                                │
FastAPI                                              │
    ├──► PostgreSQL (Supabase)        — metadata     │
    ├──► AWS S3                       — images       │
    └──► Anthropic Claude API         — AI labeling  │
─────────────────────────────────────────────────────┘
```

Infrastructure detail (Cloudflare, CI/CD, provisioning) is in [DEPLOYMENT.md](./DEPLOYMENT.md).

## Backend

- **Python:** 3.11+
- **Framework:** FastAPI (REST; first-class Pydantic validation and Anthropic SDK)
- **PDF → Image:** **PyMuPDF** (`fitz`) at 300 dpi — no system dependency, unlike `pdf2image`/Poppler
- **Image processing:** Pillow (WebP encoder)
- **PDF generation:** ReportLab
- **Auth:** bcrypt, JWT via `python-jose`, Google OAuth 2.0 over `httpx`
- **Object store:** `boto3`

```
app/
├── routes/         # FastAPI route handlers — auth.py, reference.py, ingest.py, questions.py,
│                   #   papers.py, generate.py, generation_config.py
├── schemas/        # Pydantic request/response models — auth.py, reference.py, questions.py, generate.py
├── models/         # SQLAlchemy ORM models — orm.py
├── services/       # business logic — auth.py, google_oauth.py, ingest.py, generate.py
│                   #   (question selection), question_query.py (filter/eager-load),
│                   #   question_serialization.py, question_parts.py, generation_config.py,
│                   #   premium.py (who may open which premium paper)
├── pdf/            # image_processing.py (PDF→image, standardization), layout_engine.py
│                   #   (PDF packing + render), rich_text.py, sample_data.py (synthetic fixtures)
├── storage/        # s3_client.py — AWS S3 / MinIO client + signed URL helpers
├── ai/             # Claude API clients — filename_extractor.py, topic_labeler.py
├── db.py           # SQLAlchemy engine/session, declarative Base, get_db dependency
├── deps.py         # FastAPI providers for outbound I/O (presigner, image fetcher, AI labeller)
├── logger.py       # file logger + Timer + token/cost logging helper
└── main.py
```

Pydantic schemas and ORM models live in **separate** `schemas/` and `models/` packages.

**Route modules hold routes only.** Anything a second module needs — query building, serialization,
selection — lives in `services/` under a public name. A route module reaching into another route
module's internals is the smell that puts something here.

### Outbound I/O goes through `Depends`

S3 and the Claude API reach the routes as injected callables from `app/deps.py` —
`get_presigner`, `get_image_fetcher`, `get_question_labeller` — not as module-level imports the
route calls directly. Production gets the real client; `tests/conftest.py` swaps in a fake via
`app.dependency_overrides` (the `fake_presign`, `fake_image_bytes` and `stub_labeller` fixtures).

The point is that callers and tests cross the **same** seam. Patching a name inside a route module
couples a test to that module's import list, so relocating a helper breaks tests that never
mentioned it. `app/pdf/layout_engine.py` already worked this way with its `fetch_bytes` parameter —
which is why `scripts/generate_sample_pdf.py` can drive the real engine from an in-memory dict.

### Object store integration

`app/storage/s3_client.py` wraps boto3. Keys follow the pattern in
[DATA_MODEL.md](./DATA_MODEL.md#image-storage-conventions).

- `put_image(key, bytes)` — import writes (`ContentType="image/webp"`).
- `get_presigned_url(key, expires_in)` — how images reach the frontend; they are **never** proxied
  through the backend.
- `copy_only(src_key, dst_key)` — server-side copy leaving the source intact. Import/edit flows copy
  temp uploads to their canonical key, commit the DB, and only then delete the temp sources, so a
  failed copy or commit leaves the temp uploads retryable and never orphans canonical objects.
- `delete_object(key)` — callers commit the DB deletion **before** removing objects, since S3
  deletes are irreversible.
- `get_image_bytes(key)` — raw bytes for server-side use (AI labelling, PDF rendering).

**Local dev:** `boto3` points at an S3-compatible endpoint via `S3_ENDPOINT_URL` (unset in
production) — same code path, no special-casing.

### Testing

`pytest`, in `tests/`. Unit tests are fully offline (SQLite in-memory + `moto` for S3);
`tests/integration` hits live Anthropic + S3 and is excluded from CI.

## Frontend

- **Framework:** React with Vite
- **Type:** SPA
- **Styling:** developer's choice, picked once (Tailwind / CSS Modules / vanilla CSS all fine at
  this scale)

```
frontend/src/
├── api/            # client.js (fetch wrapper + friendlyMessage) and per-resource modules
├── components/     # shared UI — AppShell, NavBar, UserMenu, QuestionCard, QuestionDetailModal,
│                   #   PartsEditor, TopicCombobox, InfoTooltip, ErrorBanner, RichTextEditor
│   ├── browse/     #   FilterBar, TopicMultiSelect
│   └── generate/   #   autocreate panel, selection cart
├── context/        # AuthContext
├── features/       # import/, papers/, reference/, users/
├── hooks/          # useQuestionSearch.js — the shared question-search state machine
├── pages/          # route-level pages, incl. admin/
├── utils/          # topicFormat.js, premium.js, userName.js, pdfFilename.js
└── test/           # setup.js
```

**`useQuestionSearch(filters)`** owns the filtered, paginated question list that Browse and Generate
both render: fetch-on-change with abort, "Load more" paging, and de-duplication of appended pages by
id. Only where the filters *live* differs between the two pages — Browse keeps them in the URL,
Generate in local state — so the hook takes them as input and owns everything downstream. It also
exports `filtersToListArgs`, which Generate's "Select All" reuses for its one-off fetch.

### Testing

- **Runner:** [Vitest](https://vitest.dev/) with `jsdom` + React Testing Library.
- **Run:** `cd frontend && npm test` (also runs in CI's `frontend-build` job).
- **Location:** colocated with the code they cover as `*.test.js` / `*.test.jsx`; shared setup in
  `src/test/setup.js`, configured via the `test` block in `vite.config.js`.
- **Convention:** import test APIs explicitly (`import { describe, it, expect, vi } from 'vitest'`)
  — vitest globals are not enabled.

### Routes / pages

| Path | Page | Access | Feature doc |
|---|---|---|---|
| `/login` | Login | Public | [auth](./features/auth.md) |
| `/register` | Register | Public | [auth](./features/auth.md) |
| `/` or `/browse` | Browse / Filter questions | Authenticated | [browse](./features/browse.md) |
| `/questions/:id` | Question detail (all pages) | Authenticated | [browse](./features/browse.md) |
| `/generate` | Paper generation | Authenticated | [paper-generation](./features/paper-generation.md) |
| `/subscribe` | Subscribe — one plan per school level (payment stub) | Authenticated | [users-and-premium](./features/users-and-premium.md) |
| `/admin/import` | Import flow | Admin | [ingestion](./features/ingestion.md) |
| `/admin/reference` | Reference data CRUD | Admin | [reference-data](./features/reference-data.md) |
| `/admin/papers` | Papers list + editor | Admin | [ingestion](./features/ingestion.md) |
| `/admin/users` | User management (roles + premium access) | Admin | [users-and-premium](./features/users-and-premium.md) |
| `/admin/generation-config` | Generation config | Admin | [generation-config](./features/generation-config.md) |

### Navigation (app shell)

All main routes (`/`, `/generate`, `/admin/*`) render inside a shared `<AppShell />`
(`src/components/AppShell.jsx`) — a role-aware menubar (`<NavBar />`) plus page content. `/login`
and `/register` stay outside the shell. The menubar is always fully visible for the user's role —
there is no "Admin" button to unlock it:

- **Everyone:** Question Bank (`/`), Generate Paper (`/generate` — signed-out clicks land on
  `/login` via `ProtectedRoute`).
- **Admins additionally:** Reference, Import, Papers, User Management, Generation Config.
- **Normal (`public`) users:** a **⭐ Go Premium** link to `/subscribe` at the top right.
- **Top right:** signed-in users get an account button (`<UserMenu />`) with **Log out** (closes on
  outside click / Escape; logging out returns to `/`). Signed-out visitors see **Log in**.

## Cross-cutting conventions

**Page layout.** Content pages span ~90% of the viewport via `max-w-[90%] mx-auto` (Browse,
Generate, admin Reference, Papers list/editor, import Topic Review). Exceptions: the import review
grid is already full-width under the app shell, and the Login/Register cards stay narrow
(`max-w-sm`).

**Topic display.** Topics always render with their topic number as a `T{n}:` prefix — **"T1:
Algebra"** — on Browse cards, filter chips, the AI review, the paper editor, and the add-topic
combobox. Use `formatTopic(topicNumber, name)` in `src/utils/topicFormat.js` (falls back to the bare
name when no number exists). The admin Topics tab shows the number in its own editable column
instead. Keyword search matches the `T{n}` token too.

**Marks are derived.** No question-level marks field exists anywhere — a question's total is
`SUM(QuestionPart.marks)`. See [DATA_MODEL.md](./DATA_MODEL.md#questions-have-parts).

**Images are presigned, never proxied.** There is no `/api/questions/:id/image/:page` endpoint;
every image reaches the browser as a presigned S3 URL embedded in the JSON response. The premium
paywall works by *withholding* that URL — see
[users-and-premium.md](./features/users-and-premium.md).
