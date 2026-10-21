# PilloraQuestionBank

A question bank of Singapore school exam questions: admins import exam-paper PDFs and label each
question; users browse, filter and generate custom papers as PDFs.

Everything beyond local setup — architecture, data model, features, deployment, testing — is in
[`docs/`](./docs/README.md).

## Prerequisites

- Python 3.11+ (CI and the production image use 3.11)
- Node.js 22 with `npm`
- Docker — for local MinIO (optional) and the Tesseract image the ingest worker uses for scanned
  answer tables
- A **dev Supabase project** (separate from production) — its session-pooler connection string
- A **dev S3 bucket**, or local MinIO
- An **Anthropic API key** for AI features (labelling, metadata, auto-import segmentation)
- Optional: a Google OAuth client for "Sign in with Google" (see
  [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#google-oauth-setup))

## Setup

```bash
# Backend (repo root)
python -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt       # app + test deps + the ingestion/ package (editable)
cp .env.example .env                      # fill in DATABASE_URL, JWT_SECRET_KEY, S3/AWS values, ANTHROPIC_API_KEY

# Optional: local S3 instead of a dev bucket (MinIO on :9000, console on :9001, bucket pillora-dev)
docker compose up -d                      # keep S3_ENDPOINT_URL=http://localhost:9000 in .env

# Optional: Tesseract image for the worker's OCR of scanned answer tables
docker compose build tesseract

# Database schema + seed data
alembic upgrade head

# Frontend
cd frontend && npm install
```

- `alembic upgrade head` also seeds reference data (school levels, subjects, streams, levels, exam
  types) and an admin account `admin@pillora.com`; there is no separate seed command.
- With no MinIO, remove `S3_ENDPOINT_URL` from `.env` and point the AWS values at your dev bucket
  (it needs the CORS rule in [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#one-time-vm-provisioning)
  for auto-import uploads, with `http://localhost:5173` as the origin).
- The frontend needs no `.env`: it calls `/api/*` on its own origin.

## Running locally

```bash
# Terminal 1 — API (repo root)
uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev                # http://localhost:5173, proxies /api to :8000

# Terminal 3 — ingest worker, only needed for Auto import
python -m app.worker
```

- The worker reads the same `.env`. By default it runs OCR through the `pillora-tesseract` Docker
  image; set `INGEST_OCR_COMMAND=tesseract` if the binary is installed locally. Other worker
  settings are in [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#configuration).
- For Google sign-in locally, set the three `GOOGLE_*` values with
  `GOOGLE_REDIRECT_URI=http://localhost:5173/api/auth/google/callback`.

## Database migrations

```bash
alembic revision --autogenerate -m "add foo"   # from ORM model changes; review the file before committing
alembic upgrade head                           # apply to the dev database
```

Production applies migrations automatically on deploy, after a safety dump. Unit tests build the
schema from the models, not from migrations, so always run new migrations against the dev database.

## Tests

See [docs/TESTING.md](./docs/TESTING.md). Quick reference:

```bash
pytest tests/ --ignore=tests/integration       # backend, offline
cd frontend && npm test                        # frontend
```
