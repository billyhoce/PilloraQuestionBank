# PilloraQuestionBank

Question bank of Singapore school exam questions. Admins import exam-paper PDFs, which become
per-question page images labelled with metadata, topics and marks. Users browse, filter and
generate custom papers as PDFs; premium papers unlock per school level.

- Stack: React (Vite) SPA · FastAPI · Postgres (Supabase) · S3 · ingest worker (same image, 2nd
  container) · Claude API (Haiku 4.5; segmentation retries on Opus) · Tesseract OCR.
- A **question** is one set of page images labelled as a list of **parts** ((a), (b)(i) …), each
  with its own topics and marks; the question's marks are the sum of its parts.
- Domain vocabulary (job, task, stage, section, proposal, link, …): [docs/GLOSSARY.md](docs/GLOSSARY.md).

## Where to look

**[docs/README.md](docs/README.md) indexes all docs** — read the feature doc before changing a
feature; each one opens with a `Code:` line naming its implementation paths.

| Task touches | Read |
|---|---|
| Code layout, components, page routes | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Tables, S3 keys, image conventions | [docs/DATA_MODEL.md](docs/DATA_MODEL.md) |
| Roles, premium, paywall | [docs/features/users-and-premium.md](docs/features/users-and-premium.md) |
| PDF → proposal (`ingestion/`) | [docs/features/ingestion-pipeline.md](docs/features/ingestion-pipeline.md) |
| Upload, jobs, worker, review, confirm | [docs/features/auto-import.md](docs/features/auto-import.md) |
| Question ↔ answer booklet matching | [docs/features/qa-pairing.md](docs/features/qa-pairing.md) |
| Tests, PDF visual check, ingestion sample diff | [docs/TESTING.md](docs/TESTING.md) |
| Deploy, env vars, CI/CD | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Why it is built this way | [docs/adr/](docs/adr/) |

Issues: GitHub `billyhoce/PilloraQuestionBank` via `gh` ([docs/agents/](docs/agents/)).

## Rules for every change

- **Update the owning doc in `docs/` in the same change** (the feature doc, per docs/README.md).
  Docs describe business behaviour, high level and in bullets; fix stale lines, don't append.
- **Write tests** for testable behaviour: pytest in `tests/`, Vitest colocated `*.test.js(x)`.
- **PDF appearance changes** (`app/pdf/`): render samples and inspect the PNGs (docs/TESTING.md).
- **`ingestion/` changes**: no unit tests — diff its output over `ingestion/samples/` before and
  after (docs/TESTING.md).

## Gotchas

- `ingestion/` is a separate library and must never import `app` (`tests/test_ingestion_independence.py`).
- Ingestion: warn, never raise — collect problems into `warnings` / `needs_review`; one section or
  paper failing must not stop the rest. Every threshold lives in its package's config dataclass with
  its justification. Only `question_extractor/geometry.py` touches PyMuPDF extraction, only
  `question_extractor/ocr.py` runs Tesseract, only `ingester/request.py` calls Claude.
- Ingestion stages: declare inputs/settings/outputs for the fingerprint and bump the stage `version`
  when its output changes, or stale results are silently reused. Keep `pipeline/store.py`'s Protocol
  free of SQLite specifics (the worker implements it on Postgres).
- Union PyMuPDF rects with explicit `min`/`max`, not `|` — a zero-width stroke counts as empty and is dropped.
- Premium is one rule written twice: `premium_gate` (Python) and `restrict_premium_pool` (SQL) in
  `app/services/premium.py` — change both. A paper's premium school level comes from its **level**,
  never its stream.
- Browse and Generate share filter semantics in `app/services/question_query.py`; the Generate page
  builds its own select payload in `frontend/src/pages/GeneratePage.jsx`.
- Non-admin cover/header/footer rules are enforced server-side in `app/routes/generate.py`; hiding
  fields in the UI is not the guard. `header_text: null` means "use the preset"; `""` means none.
- PDF layout: packing and drawing in `app/pdf/layout_engine.py` must mirror each other's flow and
  gaps exactly. Test rich-text emptiness with `is_blank` (a cleared editor stores `<p></p>`).
- Emails go through `normalize_email` on every write and lookup, or one person gets two accounts.
- Stored About HTML is sanitised on write and is the only `dangerouslySetInnerHTML`; reuse that
  sanitiser for any new stored HTML.
- `paper` has no unique key (#81); matching must tolerate duplicates. Automatic matching only
  rewrites links with `match_status = 'auto'` — an admin-made link has NULL; keep it that way.
- Ingestion: Tesseract-backed scanned tables need Docker and `docker compose build tesseract`;
  without it those pages come back flagged, not erroring.
- Unit tests build the schema from ORM models, so migrations are never tested — run new ones with
  `alembic upgrade head` on the dev DB. Tests swap I/O via the seams in `tests/conftest.py`; patch
  those, not names inside route modules.
- Auto-import job files live under S3 `ingest/{job_id}/` and are deleted on settle; derive a job's
  prefix from its stored `source_key` (legacy jobs sit under `tmp/ingest/`), and never put a
  lifecycle rule on `ingest/`.
- Job statuses are derived only in `app/worker/store.py`; the API alone owns `awaiting_upload`,
  `confirmed` and `cancelled`.
- The repo `.venv` is Windows layout: `.venv/Scripts/python`.
