# pipeline

Runs a booklet as a **job** of small, file-based **stages**, each a **task** in a store. The
decision and its alternatives are in [docs/adr/0001-stage-pipeline.md](../../docs/adr/0001-stage-pipeline.md);
the vocabulary is in [CONTEXT.md](../../CONTEXT.md). The webapp's worker will run these same stages over
Postgres; this package is the local version over SQLite.

```bash
python -m pipeline submit paper.pdf      # creates the job and its tasks, prints the job id
                                         #   --debug also writes each section's _debug/ renders
python -m pipeline run                   # drains the queue (--watch keeps polling)
                                         #   --ocr-command tesseract: the OCR command, as in `ingester ingest`
python -m pipeline status [job-id]       # per task: status, duration, warnings, reason/error
```

State lives under `--root` (default `output/pipeline`): `pipeline.db` and one folder per job id.

## Stages so far

| stage | scope | kind | needs | writes |
|---|---|---|---|---|
| `register` | job | cpu | | `job.json`: sha256, page count, size, config hash, the too-large-to-ask check |
| `segment` | job | api | register | `segments.json`: the committed `<paper>.segments.json` fixture if there is one, else the Messages API; fails when no sections come out |
| `split` | job (fans out) | cpu | segment | `_split/<label>.pdf` and `_split/split.json`; creates each section's tasks from its route's chain (below) |
| `locate` | section (question route) | cpu | split | `<label>/manifest.json` and `<label>/detections.json`; `skipped` when no page has text (a scan) |
| `render` | section (question route) | cpu | locate | `<label>/pNN.png`, `<label>/review/pNN.webp` and, for a `--debug` job, `<label>/_debug/pNN.png`, drawn from `detections.json` |
| `grid` | section (table route) | cpu | split | `<label>/grid.json`: each page's column pairs and row bands, labels unread, plus the metadata of every OCR cell; for a scan, `<label>/cells.tiff`: the question cells cropped from the straightened pages, one TIFF page per cell |
| `ocr` | section (table route) | subprocess | grid | `<label>/ocr.json`: one read (text lines, lowest confidence) per TIFF page, from the configured OCR command; `skipped` when no page is scanned; `failed` when the command is missing, errors, times out or answers for the wrong number of cells |
| `questions` | section (table route) | cpu | grid; **soft**: ocr | `<label>/manifest.json`, `<label>/tables.json` and `<label>/labelled.json` (the labelled grid and the question rectangles `render` draws from). Without OCR reads the scanned pages are flagged with the `ocr` task's error |
| `render` | section (table route) | cpu | questions | `<label>/pNN.png` (rectangles, on the straightened image for a scan), `<label>/review/pNN.webp` (clean, **unstraightened**) and, for a `--debug` job, `<label>/_debug/pNN.png`, drawn from `labelled.json` |
| `unrouted` | section (unrouted route) | cpu | split | nothing; `skipped` with the reason (an answer section with no template) |

### Routes

A section's route is chosen once, at fan-out, by `ingester.router.choose_route` (`pipeline.sections`): a
**question** section or an `annotated_booklet` answer section takes the `question` chain
`locate` -> `render`; a `table` answer section takes the `table` chain (`grid` -> `ocr` ->
`questions` -> `render`, scanned ones included); anything else takes `unrouted`. A section only ever has the tasks of its own chain, and the route is recovered from the
stages it has (`Registry.route_of`), so `render` may exist in two chains: a task is
`(job_id, section, stage)` and a section has one route. A new route is added by writing its stages
with `route=<ROUTE>` and adding them to `default_registry()`; `split` needs no change.

### Soft needs: a stage that can run without its predecessor

`needs` are hard: a dependent runs only once every need is `done`, is `blocked` behind a failed
one and `skipped` behind a skipped one. A stage may instead list a predecessor in `soft_needs`: it
waits until that task has *settled* (`done`, `skipped`, `failed` or `blocked`) and then runs
whichever way it ended. The runner hands the stage the ones that did not end `done` as
`ctx.unmet[stage] = Unmet(status, detail)` (the task's error or reason), so the stage can say why its
input is absent. `questions` uses it for `ocr`: a failed OCR must not stop the manifest, because the
grid is as good as ever and the scanned pages are flagged ("the ocr stage failed: ...") instead,
exactly as `question_extractor --table` flags them when its OCR cannot run; and a digital section's
`ocr` is `skipped`, which with a hard need would skip `questions` too. The job still ends `failed`
(one of its tasks did), so the failure stays visible. The mechanism is in the registry and
`settle`, reads only task statuses and so works over any `Store`.

### The table chain's artefacts

`grid.json` is the grid before any label is read, and `questions` leaves it alone: it saves the
labelled grid and the question rectangles as `labelled.json`, so rerunning `questions` always starts
from the unlabelled grid. (`ingester ingest` writes one `grid.json`, labelled; the pipeline's
differs in content, not in what the debug renders are drawn from.) `ocr.json` and `cells.tiff` are
the OCR stage's input and output, so a human or a different OCR can replace either. The OCR command is
`ExtractConfig.ocr_command`, set on `python -m pipeline run --ocr-command` like `--model` (a
property of the runner's machine, not of the job). `questions` re-reads the section's text layer and
furniture from the split PDF for the digital pages; only the pixel-level work is saved. The grid
stage's `render`-side images for a scan: `pNN.png` is the straightened page, the review image the
original, as `ingester ingest --review` writes them.

### Why `locate` writes the manifest and `render` the images

`manifest.json` names each page's image (`pNN.png`) and the name depends on the page number alone,
so `locate` writes the manifest before the pixels exist and `render` fills in the files it names.
The manifest is then exactly the one `ingester ingest` writes, the review page can read rectangles as
soon as `locate` is done, and `render` can be rerun (for debug) without detecting again. The
only difference: warnings logged while rendering (a review image that would not encode) belong to the
`render` task, not the manifest's `warnings`.

`--debug` is kept in the job folder as `options.json`, written by `submit`; the runner reads it into
`StageContext.debug`. Review images are always written (the webapp's review page needs them).

`segment` and `split` call `ingester.segmenter.segment_into` and `ingester.splitter.split_into`,
the same code `ingester ingest` runs, so their artefacts match its output.

## Modules

- `registry.py`: `Stage` (with `needs` and `soft_needs`), `Registry`, `default_registry()`. The place to add a stage.
- `sections.py`: `load_section` (rebuilds an `ingester` section from the job's artefacts) and `section_route`.
- `outcome.py`: `StageContext` (job dir, source PDF, section, config, `unmet` soft needs) and `Outcome` (`done`, `skipped`, `failed`).
- `artefacts.py`: artefact names and atomic writes.
- `store.py`: the `Store` Protocol and its dataclasses; no SQL. `sqlite_store.py` implements it.
- `runner.py`: `Runner` (claim, run, record, expand fan-out) and `settle` (promote/block/skip dependents; a soft need only has to have settled).
- `stages/`: one module per stage. `cli.py`: the three commands.
- `config.py`: `PipelineConfig` (lease, poll interval, retry limit, each with its justification).

## Adding a stage

Write `stages/<name>.py` with `run(ctx) -> Outcome` and a `STAGE = Stage(...)`, and add it to
`default_registry()`. Read inputs from and write outputs to files under `ctx.job_dir` with
`artefacts.write_*`; log problems with `log.warning` (the runner collects them into the task's
warnings, as `question_extractor.warnscope` does elsewhere); keep stage names to 16 characters.
Put a stage boundary only where an external dependency lives, a human may edit the artefact, or the
work is costly and separately useful.

## Verifying a change

Submit (with `--debug`) and run `ingestion/samples/` into a scratch `--root`, then compare each job's
`segments.json`, `_split/` and every section folder (`manifest.json`, `detections.json`, `tables.json`,
`pNN.png`, `_debug/`; a table section's `grid.json`/`labelled.json` are the pipeline's own) against `python -m ingester ingest samples --recursive --output-dir <dir>` (ignoring
`generated_at` and the recorded `pdf` path; compare split PDFs by page count, text and rendered
pixels, as their bytes carry timestamps). To check failure handling, submit a PDF with no fixture
and no `ANTHROPIC_API_KEY`: its `segment` fails, `split` is `blocked`, and other jobs finish.

A table section is checked the same way, over the scanned samples with `--ocr-command tesseract`
(or the Docker default). To check the soft need, run with `--ocr-command false`: every scanned
section's `ocr` ends `failed`, its `questions` and `render` still complete, and the scanned pages are
flagged in `tables.json` and the manifest.
