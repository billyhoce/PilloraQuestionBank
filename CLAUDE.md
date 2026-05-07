# PilloraQuestionBank

A web application that serves as a database of secondary school exam questions (Singapore curriculum). Admins import exam papers (PDFs), split them into individual questions as page images, label metadata and topics, and store them. Public users browse, filter, and generate custom exam papers as downloadable PDFs.

## Scale

- 1–10 concurrent users
- ~640 papers/year, ~9,600 images/year
- ~2 GB/year of image data

## User Roles

| Role | Capabilities |
|---|---|
| **Admin** (1–2 users) | Import papers, CRUD all reference data (subjects, streams, levels, schools, exam types, topics/subtopics), all public capabilities |
| **Public** (registered) | View/filter questions, generate and download custom papers |

Auth is email/password with bcrypt hashing. Session-based or JWT. No OAuth in v1.

## Tech Stack (Summary)

| Layer | Technology |
|---|---|
| Frontend | React (Vite) — SPA |
| Backend API | Python 3.11+ / FastAPI |
| Database | PostgreSQL on Supabase (managed, free tier) |
| Object Store | AWS S3 |
| Hosting | Oracle Cloud Free Tier — 1 AMD VM, 1 GB RAM |
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
| [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) | Hosting plan, deployment checklist, env vars, backup strategy |

## Out of Scope (v1)

- AI-assisted marks extraction from question images
- OCR for full-text search within questions
- Difficulty rating / analytics per topic
- Student-facing mode (practice tests, tracking)
- OAuth / social login
- CDN for image delivery
