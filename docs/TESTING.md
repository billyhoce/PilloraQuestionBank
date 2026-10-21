# Testing

Test suites, how to run them, what CI runs, and the two verification workflows that are not unit
tests: the PDF visual check and the ingestion sample diff.

**Code:** `tests/`, `tests/conftest.py`, `frontend/vite.config.js`, `frontend/src/test/setup.js`,
`scripts/generate_sample_pdf.py`, `scripts/pdf_to_images.py`, `app/pdf/sample_data.py`,
`ingestion/samples/`

## The rule

Every testable change adds or updates tests in the same change: backend in `tests/`, frontend as
colocated `*.test.js` / `*.test.jsx`. Pure config or asset changes are exempt. PDF appearance
changes also need the [visual check](#pdf-visual-verification); `ingestion/` changes are verified by
[sample diff](#ingestion-library) instead of unit tests.

## Suites

| Suite | Command | Needs | In CI |
|---|---|---|---|
| Backend unit + API | `pytest tests/ --ignore=tests/integration` | Nothing (offline) | `backend-tests` job; also the deploy gate |
| Backend integration | `pytest tests/integration` | Real S3 bucket and Anthropic key in `.env` | No |
| Frontend unit | `cd frontend && npm test` | — | `frontend-build` job |
| Frontend lint | `cd frontend && npm run lint` | — | `frontend-build`, informational (known pre-existing warnings never fail the job) |
| Frontend build | `cd frontend && npm run build` | — | `frontend-build`; also before every deploy |

The deploy workflow re-runs only the backend unit suite before building; frontend tests run on PRs
and branches only. See [DEPLOYMENT.md](./DEPLOYMENT.md#ci-pull-requests-and-non-main-branches).

### Backend (`tests/`)

- `pytest` with `asyncio_mode = auto`; `requirements-dev.txt` installs pytest, moto, pypdf and the
  `ingestion/` package.
- Unit tests force `DATABASE_URL` to in-memory SQLite (whatever `.env` says) and build the schema
  from the ORM models, so **migrations are not exercised by tests** — run `alembic upgrade head`
  against a dev database when changing them.
- S3 is mocked with `moto`; Claude is never called.
- Outbound I/O is swapped through dependency overrides (fake presigner, image fetcher, labeller,
  object store, metadata extractor, pipeline runner) — see `tests/conftest.py`. Patch these seams,
  not names inside route modules.
- Worker tests use a SQLite file per test. Set `WORKER_TEST_DATABASE_URL` to a **scratch** Postgres
  database to run them on Postgres (row locking with `SKIP LOCKED` only behaves for real there).
- `tests/test_ingestion_independence.py` fails if anything under `ingestion/` imports `app`.
- `tests/integration/` hits real S3 and the Anthropic API and cleans up after itself; run it
  deliberately, never in CI.

### Frontend (Vitest)

- Vitest + jsdom + React Testing Library; configured in the `test` block of `vite.config.js`, with
  shared setup (jest-dom matchers, cleanup after each test) in `src/test/setup.js`.
- Tests sit next to the code they cover.
- Vitest globals are off: import `describe`, `it`, `expect`, `vi` from `vitest` explicitly.
- `npx vitest` (from `frontend/`) runs in watch mode.

## PDF visual verification

Required after any change that affects how generated PDFs look (`app/pdf/layout_engine.py`,
`app/pdf/rich_text.py`, cover/chrome options). The scripts drive the real layout engine with **no
database, S3 or network**. Engine behaviour: [features/pdf-rendering.md](./features/pdf-rendering.md).

1. Change the layout code.
2. Generate a sample paper and its page images:
   ```bash
   python scripts/generate_sample_pdf.py --png --out <scratch>/sample.pdf
   ```
   PNGs land in `<scratch>/sample_pages/page_NN.png` (120 dpi, ~992 × 1403 px per A4 page).
3. Read the PNGs and check: cover (title, subtitles, marks box, rich-text body), page chrome
   (branding header, instructions, footer), question numbering, credits, packing, section
   boundaries, answer-paper layout.
4. Compare against a run from before the change. Compare **PNGs, not PDFs** — PDFs embed
   timestamps; rendered pixels are deterministic.

Sample generator:
- Mirrors the generate endpoint's orchestration, fed with deterministic synthetic pages
  (bordered, labelled, answers faintly tinted).
- The default 3 questions cover every synthetic shape: small blocks that pack together, a narrower
  page that is upscaled to 1760 px, a two-image block, and a question with no answer pages whose
  number stays reserved in the answer paper. Sizes stay within what import can produce (≤ 1760 px
  wide, ≤ ~2490 px tall).
- Options: `--variant question|answer|combined` (default combined), `--questions N`,
  `--no-cover`, `--cover-title`, `--cover-subtitle1`, `--cover-subtitle2`, `--cover-body` (rich-text
  HTML), `--page-header`, `--instructions`, `--footer`, `--dpi`, and repeatable `--image PATH` to
  use real page images.
- Synthetic pages cannot show problems that depend on real scans (grey backgrounds, ink near the
  margin, WebP artefacts). For those, rasterise a real paper and feed its pages back in:
  ```bash
  python scripts/pdf_to_images.py "samples/<paper>.pdf" --dpi 120
  python scripts/generate_sample_pdf.py --png --out <scratch>/real.pdf --image <page_01.png> --image <page_02.png>
  ```
- Covered by `tests/test_sample_pdf.py`.

## Ingestion library

`ingestion/` has no unit-test suite. Verify a change by running its commands over
`ingestion/samples/` before and after and diffing the output. Stages and the CLI are described in
[features/ingestion-pipeline.md](./features/ingestion-pipeline.md#verifying-changes).

Run from `ingestion/` (`pip install -r requirements-dev.txt` or `pip install -e ./ingestion`
installs the packages):

```bash
python -m pipeline ingest samples --recursive --debug --output-dir <scratch>       # whole chain
python -m ingester segment samples/ --recursive --output-dir <scratch>             # segmentation only
python -m question_extractor samples/ --recursive --output-dir <scratch> --debug   # question papers, whole PDF
```

What to compare between the before and after trees:
- Equal: every `ingest.json`, `manifest.json` (question counts, rectangles, `warnings`,
  `needs_review`, `skip_reason`), `detections.json`, `tables.json` (pairs, row bounds, labels,
  reading order) and `segments.json` — ignoring `generated_at` and recorded PDF path prefixes.
- Byte-identical: every `pNN.png` and `_debug/pNN.png`.
- Split PDFs: compare page count, text and rendered pixels (their bytes carry timestamps).
- Segmentation: diff `segments.json` against the committed fixtures.

Notes:
- Every sample PDF has a committed `<paper>.segments.json` fixture beside it, so runs make **no
  Claude call** and need no credential. A prompt or schema change cannot be judged this way: it
  needs `--force` and a key.
- A previous run's `output/<paper>/segments.json` is reused before the fixture: delete it first when
  checking segmentation.
- Scanned answer tables need Docker running and the Tesseract image built
  (`docker compose build tesseract`); without it their pages come back flagged.
- The webapp's root `samples/` folder is unrelated.

### Ingestion sample corpus

`python -m pipeline ingest samples --recursive --debug --output-dir <dir>` over the 13 sample PDFs
gives **13 papers, 27 sections**: every section `extracted` except q1/q2 of the two scanned EOY
papers (Bedok View, Yuying), which are `not_routed`.

| Sample | Expected |
|---|---|
| `ACSBR 2024 4E5N Prelim Math P1 QP` | 22 pages → 25 questions; page 22 skipped as blank; one warning on Q25 |
| `standard`, `coverpage_formulae_numberheader_footer_blankpage` | Pipeline manifests match `question_extractor` run on the whole PDF |
| `coverpage_formulae_numberheader_footer_endofpaper` | Same question count as the whole-PDF run, but even pages' rectangles end 12.5 pt higher (fewer pages after split → even-side footer not detected); no ink lost — expected |
| `coverpage_formulae_footer_funnyheader_endofpaper` a1 (table, `[0,2]` across) | 12 questions from 2 pairs × 13 rows; Q5 in two segments; p1 flagged (the key prints no Q6) |
| `coverpage_formulae_numberheader_footer_blankpage_graphgrid` a1 (table, `[0,2]` down) | 12 questions, pairs of 22 and 10 rows |
| `coverpage_formulae_blankpageinmiddle_endofpaper` a1 (scanned table, `[0]` down) | 13 questions, right edge inferred on every page; p5 flagged (broken row rule between 7(ii) and 7(iii)) |
| `2024 S2 M (G3) EOY - Bedok View` a1/a2 (scanned tables, `[0]` down) | 14 and 9 questions, none flagged |
| `2024 S2 M (G3) EOY - Yuying` a1/a2 (scanned tables, `[0]` down) | Q1–Q11 and Q12–Q18; `l(a)` repaired to Q1, with a warning |
| `2024 S2 M WA1 Nan Hua` a1 (table, `[0,2]` across) | 7 questions; blank pair-2 cells join none |
| `2026 S1 M WA3 Prac 2 Clementi Town - Chap 4,5,6,7` a1 (table, `[0]` down) | 10 questions; Q5 split across the page break |
| `answer_tables/two_pairs_column_break` (table, `[0,2]` down) | 15 questions; Q4 split across the column break; p2 flagged (reads across), p4 flagged (borderless) |

- `[0,2] across` is the table layout: the question columns and reading order from the fixture.
- No sample fires the straddle or uncovered-text flags; a change to those needs a purpose-built
  broken table.
- `ACSBR … QP` q1 `p17.png` may differ by up to 12 per channel between runs: ignore.
- Failure handling: run on a folder holding a garbage `.pdf`, a real PDF with no fixture and a good
  sample, without `ANTHROPIC_API_KEY` — the garbage fails `register`, the unfixtured one fails
  `segment`, each still gets an `ingest.json` with `segmented: false`; the good one is extracted.
  With `--ocr-command false`, every scanned section's `ocr` fails but its questions still complete,
  with the scanned pages flagged.
