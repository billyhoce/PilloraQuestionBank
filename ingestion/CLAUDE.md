# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Three packages, at three scales. Read a package's README before changing it — it holds the
module map, the reasoning behind each heuristic and how to verify a change.

- **`ingester`** — works on the booklet a paper arrived in. A vision model labels page
  ranges (`q1`, `a1`, …) and classifies each answer paper's template into
  `segments.json` (`segment`), then the PDF is cut into one PDF per section with a page
  map back to the original (`split`). For a `table` answer section the model also
  reports which columns hold the question numbers and the reading order. `ingest` (now
  `pipeline ingest`; `ingester ingest` forwards to it) runs both, then routes each section into `output/<paper>/<label>/`: question and
  `annotated_booklet` answer sections go through `question_extractor`, `table` answer
  sections (scanned ones included) through `question_extractor --table` with that
  layout; textless (scanned) question and annotated sections are recorded as not
  routed. `output/<paper>/ingest.json` (the `report` stage's) reports every section. See
  [`ingester/README.md`](ingester/README.md).
- **`question_extractor`** — works inside one question paper. Finds each question and
  records its rectangle in PDF points in `manifest.json`; it does not crop, it draws the
  rectangles in red on whole-page renders. With `--table` it reads a table-format answer
  PDF instead, digital or scanned: a scan is straightened and its rules read off the
  pixels (`scanpage.py`), its question cells OCR'd in the Tesseract container
  (`ocr.py`), each page's column pairs and row bands read (`tables.py`), and the rows
  grouped into questions, one rectangle per run of rows (`tablequestions.py`), into the
  same `manifest.json`; the row-level reading goes to `tables.json`. See
  [`question_extractor/README.md`](question_extractor/README.md).

- **`pipeline`** — runs a booklet as a job of small, file-based stages, each a task in a
  store (`register` → `segment` → `split`, then per section `locate` → `render` for question and
  `annotated_booklet` sections; `grid` → `ocr` → `questions` → `render` for table sections, and `report` once every section has settled; `pipeline retry` and a fingerprint per task resume a killed or partly failed job). `python -m pipeline ingest` runs a folder of PDFs and is what `ingester ingest` forwards to. A stage is
  `run(ctx) -> outcome` that reads and writes artefacts under the job's folder; the runner
  claims, runs, records and fans out; the `Store` Protocol has a SQLite implementation here and
  a Postgres one in the webapp. `segment` and `split` call `ingester`'s functions, they do not
  copy them. See [`pipeline/README.md`](pipeline/README.md), the repo's `CONTEXT.md` and
  `docs/adr/0001-stage-pipeline.md`.

```
pipeline/                      the stage runner: registry, store, runner, one module per stage
question_extractor/            the extractor; one module per pipeline stage
ingester/                      the booklet-level package
samples/                       the regression corpus
docker/tesseract/              Tesseract OCR image (the root docker-compose.yml's `tesseract` service, tag
                               pillora-tesseract); question_extractor/ocr.py runs it for
                               scanned answer tables (see README.md, OCR)
samples/<paper>.segments.json  hand-written segmentation fixture, one per sample paper
output/pipeline/               `pipeline`'s pipeline.db and one folder per job id (job.json, segments.json, _split/)
output/<paper name>/           manifest.json, segments.json, pNN.png, _split/, _debug/,
                               ingest.json, proposal.json, pages/pNN.webp (booklet numbering), <label>/ (one extractor run per routed section),
                               tables.json (a --table run's row-level reading),
                               detections.json / grid.json (the saved intermediates the --debug renders are drawn from),
                               review/pNN.webp (--review: clean pages, nothing drawn, for the admin review page)
```

## Verifying a change

There is no test suite. Run the package's command over `samples/` before and after the
change and diff the output (`manifest.json` or `segments.json`); each README has the
exact command and what to look at. The ingester run reuses the committed fixtures and
makes no API call — there is no Anthropic credential on this machine. The scanned
answer tables need Docker running and the Tesseract image built
(`docker compose build tesseract`); without them their pages come back flagged.

Run the commands from `ingestion/` (`pip install -e ./ingestion` from the repo root installs both
packages). The repo's `.venv` is Windows-layout: `.venv/Scripts/python`, not `.venv/bin/`.

`ingestion/` must never import `app` (the webapp); `tests/test_ingestion_independence.py`
enforces it.

`pipeline` is verified the same way: run `python -m pipeline ingest samples --recursive --debug --output-dir <dir>`
and compare the tree (`ingest.json`, every manifest, `tables.json`, `segments.json`, the PNGs) with the
last run's (see `pipeline/README.md`).

## Conventions

- **Every threshold goes in its package's config dataclass** (`ExtractConfig`,
  `IngestConfig`) with its measured justification. No magic numbers in pipeline modules.
- **Warn, never raise.** Problems are logged and collected into the output file's
  `warnings`, flagged `needs_review` where a human should look. One paper failing must
  not stop a folder run.
- **Union rects with explicit `min`/`max`, not `Rect.__or__`** — a zero-width stroke is
  "empty" to PyMuPDF and `|` silently drops it.
- `question_extractor/geometry.py` is the only module that talks to PyMuPDF extraction,
  `question_extractor/ocr.py` the only one that runs Tesseract, and
  `ingester/request.py` the only one that talks to the Messages API.
- **Stage boundaries** sit where an external dependency lives (the API, Tesseract), where a human
  may edit the artefact before the next stage reads it, or where the work is costly and separately
  useful. Smaller steps are function calls inside a stage. `pipeline.PipelineConfig` holds the
  scheduling thresholds with their justification; the `Store` Protocol (`pipeline/store.py`) stays
  free of SQLite specifics so Postgres can satisfy it.
- Module docstrings carry the reasoning behind their heuristics; extend them, and the
  package README, when you change the logic.
