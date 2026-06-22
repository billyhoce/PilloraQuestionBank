# PilloraQuestionBank

A repository of questions from schools and national exams (Singapore secondary curriculum). Admins import exam paper PDFs and split them into per-question images; public users browse, filter, and generate custom papers as PDFs.

For project context and architecture, see [CLAUDE.md](./CLAUDE.md). Detailed component docs live in [`docs/`](./docs).

---

## Recommended Development Workflow

This project is small (1–2 devs, low traffic). The workflow below favours simplicity over ceremony — pick what's useful, skip what isn't.

### Repo Layout

```
.
├── backend/          # FastAPI app (Python)
│   ├── app/
│   ├── tests/
│   ├── alembic/      # DB migrations
│   ├── pyproject.toml
│   └── .env.example
├── frontend/         # React + Vite app
│   ├── src/
│   ├── package.json
│   └── .env.example
├── docs/
├── .github/workflows/
└── CLAUDE.md
```

### Prerequisites (local machine)

- Python 3.11+
- Node.js 20+ (with `npm`)
- **Poppler** (for PDF → image; `brew install poppler` / `choco install poppler` / `apt install poppler-utils`)
- A **dev Supabase project** (free; separate from prod) — copy its connection string
- A **dev AWS S3 bucket** (separate from prod) — or run [MinIO](https://min.io) locally via Docker as an S3-compatible stand-in if you want to develop offline (set `S3_ENDPOINT_URL=http://localhost:9000`)
- An **Anthropic API key** for AI features

### Local Setup

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                  # fill in DATABASE_URL, AWS_*, S3_BUCKET, ANTHROPIC_API_KEY, JWT_SECRET_KEY
alembic upgrade head                                  # apply migrations to dev DB
python -m app.seed                                    # seed reference data (subjects, levels, ...)

# Frontend (in another terminal)
cd frontend
npm install
cp .env.example .env                                  # set VITE_API_BASE if needed
```

### Running Locally

```bash
# Terminal 1 — backend
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm run dev                                           # Vite on :5173, proxies /api → :8000
```

Visit `http://localhost:5173`. Vite's proxy is configured in `vite.config.js` to forward `/api/*` to `http://localhost:8000`, so no CORS pain in dev.

### Database Migrations

Use **Alembic** for schema changes. Workflow:

```bash
cd backend
alembic revision --autogenerate -m "add foo"   # generate from SQLAlchemy model diffs
alembic upgrade head                            # apply locally
# review the generated migration before committing
```

Migrations are auto-applied on deploy (see CD section).

### Testing

| Layer | Tool | Run |
|---|---|---|
| Backend unit + API | `pytest` + `httpx.AsyncClient` | `cd backend && pytest` |
| Frontend unit | Not configured yet | — |
| End-to-end (optional) | Not configured yet | — |
| Lint (Python) | Not configured yet | — |
| Lint (JS/TS) | `eslint` | `cd frontend && npm run lint` |

**Worth investing in:**
- PDF generation tests (golden-file: render a known selection, byte-compare or visual-diff the PDF).
- Filter logic tests (combinations of subject/topic/year/etc.).
- Auth + admin-route guard tests.

**Don't bother:**
- Mocking Anthropic in every test. Add one or two integration-style tests behind a flag (`ANTHROPIC_LIVE=1`) and unit-test the prompt-construction layer instead.

### Git Workflow

- `main` is always deployable.
- Work on short-lived feature branches: `feat/import-grid`, `fix/pdf-margin`, etc.
- Open a PR against `main`. CI must be green before merge.
- **Squash-merge** to keep `main` history clean.
- Solo? You can commit straight to `main` for trivial changes — but still let CI run.

### CI (on every PR)

GitHub Actions workflow at `.github/workflows/ci.yml`. Two parallel jobs:

**Backend job**
1. `ruff check`
2. `pytest` against an ephemeral Postgres service container (`services: postgres:16`)

**Frontend job**
1. `npm ci`
2. `npm run lint`
3. `npm run build` (catches build-only errors)

Target: PR feedback in <3 minutes. If it grows beyond 5 minutes, prune slow tests or parallelize.

### CD (on push to `main`)

Workflow at `.github/workflows/deploy.yml`. Simple SSH-based deploy to the Oracle VM:

1. **Build** the frontend in CI (`npm run build` → `frontend/dist/`).
2. **Upload** to the VM via `rsync` over SSH:
   - `frontend/dist/` → `/var/www/pilloraqb/`
   - `backend/` → `/opt/pilloraqb/app/`
3. **Remote commands** over SSH:
   ```bash
   cd /opt/pilloraqb/app
   .venv/bin/pip install -e .
   .venv/bin/alembic upgrade head
   sudo systemctl restart pilloraqb-api
   sudo systemctl reload nginx        # only if nginx config changed
   ```

Required GitHub Actions secrets:
- `DEPLOY_SSH_KEY` — private key authorized on the VM
- `DEPLOY_HOST` — VM public IP or DNS
- `DEPLOY_USER` — SSH user (e.g. `opc` for Oracle Linux)

Why SSH-deploy and not Docker / Kubernetes / GitOps? At 1 VM + 1 GB RAM, the orchestration overhead costs more than it saves. Re-evaluate when you have >1 server.

### Environments

| Env | DB | Object Store | Domain |
|---|---|---|---|
| Local | Local Postgres or dev Supabase project | MinIO (Docker) or dev S3 bucket | `localhost:5173` |
| Production | Supabase production project | AWS S3 prod bucket | your domain |

Skip a dedicated staging environment for v1 — at this scale, a thorough PR review + green CI + fast rollback is enough. Add staging later if/when production breakage starts hurting.

### Secrets

- **Local:** `.env` files (gitignored). Provide `.env.example` with placeholder values.
- **CI:** GitHub Actions secrets (Settings → Secrets and variables → Actions).
- **Production:** environment file loaded by the systemd unit (e.g. `/etc/pilloraqb/env`, mode `0600`, owned by the service user). Referenced via `EnvironmentFile=` in the unit.

Never commit secrets. Rotate the Anthropic key and `JWT_SECRET_KEY` if a leak is even suspected.

### Observability (lightweight)

- **App logs:** structured JSON to stdout → captured by `journalctl -u pilloraqb-api`.
- **Errors:** [Sentry](https://sentry.io) free tier — wire up both backend and frontend SDKs. Worth the 10 minutes.
- **Uptime:** a free uptime check (UptimeRobot, BetterStack) hitting `/api/health` every 5 min.
- **Logs to keep an eye on:** PDF generation failures, AI call errors, auth failures.

### Rollback

- **Code:** `git revert <bad-commit>` and let CD redeploy.
- **DB schema:** Alembic supports `alembic downgrade -1`, but treat schema rollback as a last resort — prefer forward-fix migrations. Supabase point-in-time recovery is the escape hatch for data corruption.
- **Static frontend:** if a release is bad and you need it now, SSH in and `rsync` the previous `dist/` from a backup. Keep the last 2–3 builds on the VM under `/var/www/pilloraqb-releases/<sha>/` and symlink `current` to make this trivial.

### Suggested Build Order

1. Reference data CRUD (backend + admin UI). Smallest, gets the schema running end-to-end.
2. Auth (register, login, role guard).
3. Import pipeline — server side (PDF→image, object store, confirm endpoint).
4. Import UI — wizard.
5. Browse / filter UI.
6. Paper generation engine (backend) + UI.
7. AI integrations (filename extraction first — easiest; topic labeling second).
8. Deployment + CI/CD wiring.

Each step should end with the app being usable and deployable, even if features are missing.
