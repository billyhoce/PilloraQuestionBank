# pipeline

Runs a booklet as a **job** of small, file-based **stages**, each a **task** in a store. The
decision and its alternatives are in [docs/adr/0001-stage-pipeline.md](../../docs/adr/0001-stage-pipeline.md);
the vocabulary is in [CONTEXT.md](../../CONTEXT.md). The webapp's worker will run these same stages over
Postgres; this package is the local version over SQLite.

```bash
python -m pipeline submit paper.pdf      # creates the job and its tasks, prints the job id
python -m pipeline run                   # drains the queue (--watch keeps polling)
python -m pipeline status [job-id]       # per task: status, duration, warnings, reason/error
```

State lives under `--root` (default `output/pipeline`): `pipeline.db` and one folder per job id.

## Stages so far

| stage | scope | kind | needs | writes |
|---|---|---|---|---|
| `register` | job | cpu | | `job.json`: sha256, page count, size, config hash, the too-large-to-ask check |
| `segment` | job | api | register | `segments.json`: the committed `<paper>.segments.json` fixture if there is one, else the Messages API; fails when no sections come out |
| `split` | job (fans out) | cpu | segment | `_split/<label>.pdf` and `_split/split.json`; creates a task per section for every section stage in the registry (none yet) |

`segment` and `split` call `ingester.segmenter.segment_into` and `ingester.splitter.split_into`,
the same code `ingester ingest` runs, so their artefacts match its output.

## Modules

- `registry.py`: `Stage`, `Registry`, `default_registry()`. The place to add a stage.
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

Submit and run `ingestion/samples/` into a scratch `--root`, then compare each job's `segments.json`
and `_split/` against `python -m ingester ingest samples --recursive --output-dir <dir>` (ignoring
`generated_at` and the recorded `pdf` path; compare split PDFs by page count, text and rendered
pixels, as their bytes carry timestamps). To check failure handling, submit a PDF with no fixture
and no `ANTHROPIC_API_KEY`: its `segment` fails, `split` is `blocked`, and other jobs finish.
