# pipeline

Runs a booklet as a **job** of small, file-based **stages**, each a **task** in a store. The
decision and its alternatives are in [docs/adr/0001-stage-pipeline.md](../../docs/adr/0001-stage-pipeline.md);
the vocabulary is in [CONTEXT.md](../../CONTEXT.md). The webapp's worker will run these same stages over
Postgres; this package is the local version over SQLite.

```bash
python -m pipeline submit paper.pdf      # creates the job and its tasks, prints the job id
                                         #   --debug also writes each section's _debug/ renders
python -m pipeline run                   # drains the queue (--watch keeps polling)
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
| `unrouted` | section (unrouted route) | cpu | split | nothing; `skipped` with the reason (an answer section with no template; a `table` section until its chain exists) |

### Routes

A section's route is chosen once, at fan-out, by `ingester.router.choose_route` (`pipeline.sections`): a
**question** section or an `annotated_booklet` answer section takes the `question` chain
`locate` -> `render`; a `table` answer section will take the `table` chain (`grid` -> `ocr` ->
`questions` -> `render`, not written yet, so for now it gets an `unrouted` task); anything else takes
`unrouted`. A section only ever has the tasks of its own chain, and the route is recovered from the
stages it has (`Registry.route_of`), so `render` may exist in two chains: a task is
`(job_id, section, stage)` and a section has one route. To add the table chain, write its stages with
`route=TABLE` and add them to `default_registry()`; `split` and the runner need no change.

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

- `registry.py`: `Stage`, `Registry`, `default_registry()`. The place to add a stage.
- `sections.py`: `load_section` (rebuilds an `ingester` section from the job's artefacts) and `section_route`.
- `outcome.py`: `StageContext` (job dir, source PDF, section, config) and `Outcome` (`done`, `skipped`, `failed`).
- `artefacts.py`: artefact names and atomic writes.
- `store.py`: the `Store` Protocol and its dataclasses; no SQL. `sqlite_store.py` implements it.
- `runner.py`: `Runner` (claim, run, record, expand fan-out) and `settle` (promote/block/skip dependents).
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
`segments.json`, `_split/` and every section folder (`manifest.json`, `detections.json`, `pNN.png`,
`_debug/`) against `python -m ingester ingest samples --recursive --output-dir <dir>` (ignoring
`generated_at` and the recorded `pdf` path; compare split PDFs by page count, text and rendered
pixels, as their bytes carry timestamps). To check failure handling, submit a PDF with no fixture
and no `ANTHROPIC_API_KEY`: its `segment` fails, `split` is `blocked`, and other jobs finish.
