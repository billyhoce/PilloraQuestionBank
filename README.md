# PilloraQuestionBank

A repository of questions from schools and national exams (Singapore secondary curriculum). Admins import exam paper PDFs and split them into per-question images; public users browse, filter, and generate custom papers as PDFs.

For project context and architecture, see [CLAUDE.md](./CLAUDE.md). Detailed component docs live in [`docs/`](./docs) — deployment specifics are in [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md).

---

## Recommended Development Workflow

This project is small (1–2 devs, low traffic). The workflow below favours simplicity over ceremony — pick what's useful, skip what isn't.

### Repo Layout

```
.
├── app/                # FastAPI app (Python)
│   ├── routes/         # API endpoints (auth, reference, questions, ingest, papers)
│   ├── services/       # business logic (auth, ingest, generate)
│   ├── models/         # SQLAlchemy ORM
│   ├── schemas/        # Pydantic request/response models
│   ├── storage/        # S3-compatible client (boto3) — Cloudflare R2 in prod, MinIO locally
│   ├── pdf/            # PyMuPDF rasterization + PDF layout engine
│   ├── ai/             # Anthropic Claude clients (filename + topic labeling)
│   └── main.py         # app factory + /api/health
├── alembic/            # DB migrations (initial schema + seed reference data)
├── tests/              # pytest — unit (SQLite + moto); tests/integration needs live creds
├── frontend/           # React + Vite SPA
│   └── src/
├── deploy/             # prod compose, nginx config, backup script, systemd timer, prod env template
├── docs/
├── .github/workflows/  # ci.yml (PRs), deploy.yml (push to main)
├── Dockerfile          # backend production image
├── docker-compose.yml  # local MinIO (S3-compatible dev only)
├── requirements.txt    # runtime deps
├── requirements-dev.txt # test/dev deps (pytest, moto, httpx, ...)
└── .env.example        # local dev env template
```

### Prerequisites (local machine)

- Python 3.11+
- Node.js 20+ (with `npm`)
- Docker (only if you want local MinIO instead of a dev S3 bucket)
- A **dev Supabase project** (free; separate from prod) — copy its connection string
- A **dev Cloudflare R2 bucket** (separate from prod) — or run [MinIO](https://min.io) locally via `docker compose up` as an S3-compatible stand-in (set `S3_ENDPOINT_URL=http://localhost:9000`)
- An **Anthropic API key** for AI features

### Local Setup

```bash
# Backend (from the repo root)
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                  # fill in DATABASE_URL, AWS_*, S3_BUCKET, ANTHROPIC_API_KEY, JWT_SECRET_KEY

# Optional: local S3 via MinIO instead of a dev S3 bucket
docker compose up -d                                  # MinIO on :9000/:9001, creates the pillora-dev bucket

alembic upgrade head                                  # applies migrations AND seeds reference data into the dev DB

# Frontend (in another terminal)
cd frontend
npm install
```

Reference data (subjects, levels, schools, exam types, …) is seeded by the `seed_reference_data` Alembic migration — there is no separate seed command; `alembic upgrade head` handles it. The frontend needs no `.env`: it calls the API at the relative path `/api/*`.

### Running Locally

```bash
# Terminal 1 — backend (repo root)
uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm run dev                                           # Vite on :5173, proxies /api → :8000
```

Visit `http://localhost:5173`. The dev proxy is configured in `frontend/vite.config.js` to forward `/api/*` to `http://localhost:8000`, so there's no CORS pain in dev (and none in prod either, since Nginx serves both at the same origin).

### Database Migrations

Use **Alembic** for schema changes (run from the repo root):

```bash
alembic revision --autogenerate -m "add foo"   # generate from SQLAlchemy model diffs
alembic upgrade head                            # apply locally
# review the generated migration before committing
```

Migrations are auto-applied on deploy (see [CD](#cd-on-push-to-main)), after a safety DB dump.

### Testing

| Layer | Tool | Run |
|---|---|---|
| Backend unit + API | `pytest` (SQLite in-memory + `moto` for S3 — fully offline) | `pytest tests/ --ignore=tests/integration` |
| Backend integration | `pytest` hitting live Anthropic + R2 | `pytest tests/integration` (needs real creds; **excluded from CI**) |
| Frontend lint | ESLint | `cd frontend && npm run lint` |
| Frontend build | Vite | `cd frontend && npm run build` |

Notes:
- The paper-generation engine (`app/services/generate.py`, `app/pdf/layout_engine.py`) is still a stub. Its tests in `tests/test_generate.py` are marked `xfail` until it's implemented — they'll turn green (XPASS) automatically once it lands.
- Frontend lint currently reports pre-existing warnings under the newer ESLint/react-hooks rules; it's informational and does not block CI.

### Git Workflow

- `main` is always deployable, and **every push to `main` deploys to production**.
- Work on short-lived feature branches: `feat/import-grid`, `fix/pdf-margin`, etc.
- Open a PR against `main`. CI must be green before merge.
- **Squash-merge** to keep `main` history clean.

### CI (on every PR)

GitHub Actions workflow at [`.github/workflows/ci.yml`](./.github/workflows/ci.yml). Runs on PRs and non-`main` branches. Two parallel jobs:

**Backend job**
1. `pip install -r requirements-dev.txt`
2. `pytest tests/ --ignore=tests/integration` (offline — SQLite + moto; integration tests need live creds)

**Frontend job**
1. `npm ci`
2. `npm run lint` (non-blocking / informational)
3. `npm run build` (catches build-only errors)

### CD (on push to `main`)

Workflow at [`.github/workflows/deploy.yml`](./.github/workflows/deploy.yml). Builds a Docker image, pushes it to GHCR, and deploys to the Oracle Cloud VM over SSH:

1. **test** — re-runs the CI checks as a deploy gate.
2. **build-and-push** — builds the `Dockerfile` → `ghcr.io/billyhoce/pillora-api:<sha>` (+ `:latest`); builds the frontend → uploads `dist/` as an artifact.
3. **deploy** (SSH to the VM):
   - SCP the new `dist/` to `/var/www/pillora` (atomic swap).
   - `docker compose pull` the new image.
   - **Take a fresh `pg_dump` → S3 _before_ migrating** (aborts the deploy on failure — data durability first).
   - `alembic upgrade head`, then `docker compose up -d`.
   - `curl /api/health` to confirm before declaring success.

Required GitHub Actions secrets:
- `DEPLOY_SSH_KEY` — private key authorized on the VM
- `DEPLOY_HOST` — VM public IP or DNS
- `DEPLOY_USER` — SSH user (the deploy account on the Ubuntu VM)

GHCR push/pull uses the built-in `GITHUB_TOKEN` — no extra secret. **Production app secrets never touch GitHub**; they live only in `/opt/pillora/.env` on the VM, and migrations run there.

We deploy a Docker image to a single VM via SSH + `docker compose` rather than running an orchestrator (Kubernetes/Nomad): at 1 VM + 1 GB RAM the orchestration overhead costs more than it saves. Full infra setup is in [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md).

### Environments

| Env | DB | Object Store | URL |
|---|---|---|---|
| Local | Dev Supabase project | MinIO (Docker) or dev S3 bucket | `http://localhost:5173` |
| Production | Supabase production project | Cloudflare R2 prod bucket | `https://questionbank.pillora.com.sg` (Cloudflare → Oracle VM) |

The app is served on its own subdomain; `www.pillora.com.sg` stays on Wix and is untouched. Skip a dedicated staging environment for v1 — at this scale, a thorough PR review + green CI + fast rollback is enough.

### Secrets

- **Local:** `.env` (gitignored). Use `.env.example` for the shape; prod values are templated in `deploy/pillora.env.example`.
- **CI:** GitHub Actions secrets (Settings → Secrets and variables → Actions) — deploy SSH credentials only, no app secrets.
- **Production:** `/opt/pillora/.env` on the VM (mode `0600`), loaded by `docker-compose.prod.yml` via `env_file`.

Never commit secrets. Rotate the Anthropic key and `JWT_SECRET_KEY` if a leak is even suspected.

### Observability (lightweight)

- **App logs:** `docker compose -f deploy/docker-compose.prod.yml logs -f` on the VM (or `docker logs <container>`).
- **Errors:** [Sentry](https://sentry.io) free tier — wire up backend and frontend SDKs if/when noise warrants it.
- **Uptime:** a free uptime check (UptimeRobot, BetterStack) hitting `https://questionbank.pillora.com.sg/api/health` every 5 min.
- **Logs to watch:** PDF generation failures, AI call errors, auth failures.

### Rollback

- **Code / backend:** re-deploy a previous image — SSH to the VM and run, from `/opt/pillora/repo/deploy`:
  `IMAGE_TAG=<previous-sha> docker compose -f docker-compose.prod.yml up -d`. Or `git revert <bad-commit>` and let CD redeploy.
- **Database:** the free Supabase tier has **no PITR** — recover from the most recent `pg_dump` in `s3://<bucket>-backups/` (weekly + the dump taken before every deploy). Prefer forward-fix migrations over `alembic downgrade`.
- **Static frontend:** re-run the deploy, or restore a previous `dist/` to `/var/www/pillora`.

### Build Order (followed)

1. Reference data CRUD (backend + admin UI). ✅
2. Auth (register, login, role guard). ✅
3. Import pipeline — server side (PDF→image, S3, confirm endpoint). ✅
4. Import UI — wizard. ✅
5. Browse / filter UI. ✅
6. AI integrations (filename extraction, topic labeling). ✅
7. Deployment + CI/CD wiring. ✅
8. Paper generation engine (backend) + UI. ⏳ _in progress — `generate.py` / `layout_engine.py` are stubs._

Each step ends with the app usable and deployable, even if features are missing.
