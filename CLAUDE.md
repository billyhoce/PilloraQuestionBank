# PilloraQuestionBank

A web application that serves as a database of secondary school exam questions (Singapore curriculum). Admins import exam papers (PDFs), split them into individual questions as page images, label metadata and topics, and store them. Public users browse, filter, and generate custom exam papers as downloadable PDFs.

## Scale

- 1–10 concurrent users
- ~640 papers/year, ~9,600 images/year
- ~2 GB/year of image data

## User Roles

| Role | Capabilities |
|---|---|
| **Admin** (1–2 users) | Import papers, CRUD all reference data (subjects, streams, levels, schools, exam types, topics/subtopics), configure paper generation (cover titles, subtitle placeholders, cover body, header/footer presets — the Generation Config page), full control of cover/header/footer when generating, manage users (change tiers), all premium capabilities |
| **Premium** (registered, paid) | All public capabilities, plus view images of premium papers and generate papers using premium questions |
| **Public / Normal** (registered) | View/filter questions (metadata for all; images only for non-premium papers), generate and download custom papers from non-premium questions — always with a cover page, choosing a title from the admin-configured list; the cover body, header, and footer are admin presets |

The stored role values are `admin`, `premium`, and `public` (shown as "Normal" in the UI).
Papers carry an `is_premium` flag; their images/questions are gated to premium & admin users.
Premium is granted by an admin via the User Management page — the Subscribe page is a payment
stub for now.

Auth is email/password with bcrypt hashing. Session-based or JWT. No OAuth in v1.

## Tech Stack (Summary)

| Layer | Technology |
|---|---|
| Frontend | React (Vite) — SPA |
| Backend API | Python 3.11+ / FastAPI |
| Database | PostgreSQL on Supabase (managed, free tier) |
| Object Store | AWS S3 |
| Hosting | Oracle Cloud Free Tier — 1 Ampere ARM VM (arm64), 1 OCPU / 6 GB RAM |
| AI | Anthropic Claude API (Sonnet for vision, Haiku for text) |

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

| Doc | What's inside |
|---|---|
| [docs/DATA_MODEL.md](./docs/DATA_MODEL.md) | Database schema (reference + core tables), image storage conventions, image dimension standards |
| [docs/BACKEND.md](./docs/BACKEND.md) | FastAPI app, API endpoints, import pipeline (server side), PDF generation engine, auth & security |
| [docs/FRONTEND.md](./docs/FRONTEND.md) | React app, import flow UI, browse/filter UI, paper generation UI, admin CRUD UI |
| [docs/AI_INTEGRATION.md](./docs/AI_INTEGRATION.md) | Claude API usage: topic auto-labeling and filename metadata extraction |
| [docs/PDF_GENERATION_TESTING.md](./docs/PDF_GENERATION_TESTING.md) | DB-free sample-PDF generation and the visual self-verification workflow |
| [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) | Hosting plan, deployment checklist, env vars, backup strategy |

## Contribution Requirements

Every new feature or behavior change must, **in the same change**:

- **Update the docs.** Revise the relevant doc(s) under `docs/` (and `CLAUDE.md` itself when the
  scope, stack, or architecture changes) so they never drift from the code. The Documentation Map
  above says which doc owns which area (DATA_MODEL / BACKEND / FRONTEND / AI_INTEGRATION /
  DEPLOYMENT). Fix any statement the change makes stale, not just add new prose.
- **Visually verify PDF layout changes.** After changing `app/pdf/layout_engine.py`,
  `app/pdf/cover_body.py`, or anything else that affects generated-PDF appearance, run
  `python scripts/generate_sample_pdf.py --png --out <scratch>/sample.pdf` (no DB/S3 needed) and
  inspect the emitted page PNGs before concluding. See
  [docs/PDF_GENERATION_TESTING.md](./docs/PDF_GENERATION_TESTING.md).
- **Write tests where the change is testable.** Add or update backend tests (`pytest`, in `tests/`)
  and frontend tests (Vitest, colocated `*.test.js` / `*.test.jsx`) to cover new or changed
  behavior. Both suites run in CI's `frontend-build` job. Pure-config / asset-only changes with no
  testable behavior are exempt.

## Out of Scope (v1)

- AI-assisted marks extraction from question images
- OCR for full-text search within questions
- Difficulty rating / analytics per topic
- Student-facing mode (practice tests, tracking)
- OAuth / social login
- CDN for image delivery
