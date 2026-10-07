# PilloraQuestionBank

A web application that serves as a database of secondary school exam questions (Singapore curriculum). Admins import exam papers (PDFs), split them into individual questions as page images, label metadata and topics, and store them. Public users browse, filter, and generate custom exam papers as downloadable PDFs.

A question is stored as **one set of page images** but labelled as a list of
**parts** — (a), (b), (a)(i) … — each with its own topics/subtopics and its own
marks. The images are never split per part; the split is produced by the AI
labeller and corrected by the admin. A question's marks total is derived by
summing its parts. See [docs/DATA_MODEL.md](./docs/DATA_MODEL.md#questions-have-parts) and
[docs/features/ai-labelling.md](./docs/features/ai-labelling.md).

## Scale

- 1–10 concurrent users
- ~640 papers/year, ~9,600 images/year
- ~2 GB/year of image data

## User Roles

| Who | Capabilities |
|---|---|
| **Admin** (1–2 users) | Import papers, CRUD all reference data (subjects, streams, levels, schools, exam types, topics/subtopics), configure paper generation (cover titles, subtitle placeholders, cover body, header/footer presets — the Generation Config page), full control of cover/header/footer when generating, manage users (roles and premium access), unrestricted by the paywall |
| **Normal + premium for a school level** (registered, paid) | All Normal capabilities, plus view images of, and generate papers from, premium papers **in that school level** |
| **Public / Normal** (registered) | View/filter questions (metadata for all; images only for non-premium papers), generate and download custom papers from non-premium questions — always with a cover page, choosing a title from the admin-configured list; the cover body, header, and footer are admin presets |

The stored role values are just `admin` and `public` (shown as "Normal" in the UI).
**Premium is not a role — it is the set of school levels a user has paid for** (`Primary`,
`Secondary`, …), held in `user_premium_school_level`; a user may hold several, and "is this user
premium" is derived from those rows rather than stored. Papers carry an `is_premium` flag, and a
premium paper unlocks only for admins and for users holding **its** school level — the one on its
`level`. Premium is granted per school level by an admin via the User Management page — the
Subscribe page (one plan per school level) is a payment stub for now.

Users hold a first name, last name and email address. Accounts are created either manually
(email + password, bcrypt-hashed) or with **Google OAuth 2.0** — a server-side authorization-code
flow; the browser never handles the client ID, the client secret or any Google token. Signing in
with Google on an address that already has a password account links the two, keeping the existing
role. Either way the session is a JWT in an httpOnly cookie.

## Tech Stack (Summary)

| Layer | Technology |
|---|---|
| Frontend | React (Vite) — SPA |
| Backend API | Python 3.11+ / FastAPI |
| Database | PostgreSQL on Supabase (managed, free tier) |
| Object Store | AWS S3 |
| Hosting | Oracle Cloud Free Tier — 1 Ampere ARM VM (arm64), 1 OCPU / 6 GB RAM |
| AI | Anthropic Claude API — Haiku 4.5 for both the vision and text calls |

Full rationale and alternatives are in [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md).

## Architecture (Text Diagram)

```
Browser (React SPA)
    │  HTTPS
    ▼
Nginx (static + reverse proxy)  ── Oracle Cloud VM ──┐
    │  /api/*                                        │
    ▼                                                │
FastAPI                                              │
    ├──► PostgreSQL (Supabase)        — metadata    │
    ├──► AWS S3                       — images      │
    └──► Anthropic Claude API         — AI labeling │
─────────────────────────────────────────────────────┘
```

## Documentation Map

Docs are organised **by feature**, not by layer: each file under `docs/features/` covers one
capability end-to-end (its API, its UI, and any AI or PDF work it involves), so answering a question
usually means opening one file. [docs/README.md](./docs/README.md) is the full index.

| Doc | What's inside |
|---|---|
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | Stacks, backend/frontend code layout, object store, routes, navigation, cross-cutting conventions |
| [docs/DATA_MODEL.md](./docs/DATA_MODEL.md) | Database schema (reference + core tables), image storage conventions, image dimension standards |
| [docs/features/auth.md](./docs/features/auth.md) | Registration, password login, Google OAuth 2.0, JWT sessions, security posture, auth UI |
| [docs/features/users-and-premium.md](./docs/features/users-and-premium.md) | The three tiers, user management, `is_premium`, how the paywall is enforced |
| [docs/features/reference-data.md](./docs/features/reference-data.md) | Subjects/streams/levels/schools/exam types/topics CRUD + admin UI |
| [docs/features/ingestion.md](./docs/features/ingestion.md) | Import wizard UI, PDF→image pipeline, confirm/delete, Manage Papers editor |
| [docs/features/ai-labelling.md](./docs/features/ai-labelling.md) | Claude part-split + topic/marks labelling, filename extraction, parts write path, review UI, costs |
| [docs/features/browse.md](./docs/features/browse.md) | `/api/questions` filtering + search, filter panel and results UI |
| [docs/features/paper-generation.md](./docs/features/paper-generation.md) | Selection algorithms, generate endpoints, role enforcement, `/generate` UI |
| [docs/features/generation-config.md](./docs/features/generation-config.md) | Admin presets + cover titles that constrain non-admin generations |
| [docs/features/pdf-rendering.md](./docs/features/pdf-rendering.md) | Layout engine, packing, page chrome, cover page, rich-text cover body |
| [docs/PDF_GENERATION_TESTING.md](./docs/PDF_GENERATION_TESTING.md) | DB-free sample-PDF generation and the visual self-verification workflow |
| [ingestion/README.md](./ingestion/README.md) | The PDF ingester (`question_extractor`, `ingester`): segments a booklet, splits it, locates each question's rectangle, reads answer tables (OCR via the Tesseract image). Has its own [CLAUDE.md](./ingestion/CLAUDE.md) and per-package READMEs |
| [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) | Hosting plan, deployment checklist, env vars, backup strategy |

## Contribution Requirements

Every new feature or behavior change must, **in the same change**:

- **Update the docs.** Revise the relevant doc(s) under `docs/` (and `CLAUDE.md` itself when the
  scope, stack, or architecture changes) so they never drift from the code. Put the change in the
  **feature** doc that owns the capability — the Documentation Map above and
  [docs/README.md](./docs/README.md) say which. Only genuinely cross-cutting facts belong in
  `ARCHITECTURE.md` / `DATA_MODEL.md`. Fix any statement the change makes stale, not just add new
  prose.
- **Visually verify PDF layout changes.** After changing `app/pdf/layout_engine.py`,
  `app/pdf/rich_text.py`, or anything else that affects generated-PDF appearance (see
  [docs/features/pdf-rendering.md](./docs/features/pdf-rendering.md)), run
  `python scripts/generate_sample_pdf.py --png --out <scratch>/sample.pdf` (no DB/S3 needed) and
  inspect the emitted page PNGs before concluding. See
  [docs/PDF_GENERATION_TESTING.md](./docs/PDF_GENERATION_TESTING.md).
- **Write tests where the change is testable.** Add or update backend tests (`pytest`, in `tests/`)
  and frontend tests (Vitest, colocated `*.test.js` / `*.test.jsx`) to cover new or changed
  behavior. Both suites run in CI's `frontend-build` job. Pure-config / asset-only changes with no
  testable behavior are exempt.

## Ingestion package

`ingestion/` is the PDF ingester, moved in from the former `PilloraQuestionBankIngester` repo
(history stays in that archived repo). It holds three packages — `question_extractor` (inside one paper),
`ingester` (the booklet) and `pipeline` (runs the booklet-level stages as tasks in a store; see
[docs/adr/0001-stage-pipeline.md](./docs/adr/0001-stage-pipeline.md) and [CONTEXT.md](./CONTEXT.md)). It is a separate installable library
(`pip install -e ./ingestion`; its own `pyproject.toml`) that must never import `app` — a pytest
(`tests/test_ingestion_independence.py`) enforces it. It keeps its own conventions
([ingestion/CLAUDE.md](./ingestion/CLAUDE.md)) and **its own verification rule**: it has no unit-test
suite and is verified by running its commands over `ingestion/samples/` before and after a change and
diffing the output — **not** by the "write tests" rule below. The webapp's `samples/` folder is
unrelated to `ingestion/samples/`. The Tesseract image is built with
`docker compose build tesseract` from the repo root.

## Out of Scope (v1)

- OCR for full-text search within questions
- Difficulty rating / analytics per topic
- Student-facing mode (practice tests, tracking)
- Social login beyond Google (Facebook, Apple, …)
- Self-service profile editing / password reset
- CDN for image delivery

## Agent skills

### Issue tracker

Issues live as GitHub issues in `billyhoce/PilloraQuestionBank`, driven by the `gh` CLI. See
`docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See
`docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
