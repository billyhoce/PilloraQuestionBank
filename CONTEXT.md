# Context

The words this project uses on purpose. The ingestion pipeline (`ingestion/pipeline/`) is the
part that leans on them most; see [docs/adr/0001-stage-pipeline.md](./docs/adr/0001-stage-pipeline.md).

**Job**
One booklet PDF being ingested. It has an id (a string, a UUID in the webapp), a source PDF, a
status (`queued`, `running`, `done`, `failed`, ...) and a folder of artefacts. A job is made of tasks.

**Task**
One run of one stage on one job (and, for a section stage, one section). Its identity is
`(job_id, section, stage)`; `section` is empty for a job-scope stage. A task has a status
(`pending`, `ready`, `running`, `done`, `skipped`, `failed`, `blocked`), an attempt count, a
lease, its warnings and, when it did not finish normally, a reason or an error.

**Stage**
A named, registered unit of work with a scope (job or section), a kind (cpu, api, subprocess),
the stages it depends on and whether it fans out. `register`, `segment`, `split`, ... A stage is
a function `run(ctx) -> outcome`; a task is what running it once leaves behind. Stage boundaries
sit where an external dependency lives, where a human may edit the artefact, or where work is
costly and separately useful. Smaller steps are function calls inside a stage.

**Artefact**
A file a stage leaves under its job's folder (`job.json`, `segments.json`, `_split/q1.pdf`, ...),
written atomically. Stages hand work to each other only through artefacts, so a stage can run in
another process and a human can read or edit the file in between.

**Section**
One labelled page range of a booklet, named in `segments.json`: `q1`, `q2` for question papers,
`a1`, `a2` for the answer papers that belong to them. Section stages run once per section.

**Proposal**
What the pipeline offers for a booklet: its sections, the questions found in each and their
rectangles, with every flag raised along the way. A proposal is a suggestion for an admin to
review and correct; nothing in it is a stored question until the admin confirms it.

**Fingerprint**
A hash of what a task's artefact was produced from (the input artefacts, the stage's
configuration and its code version). A task whose recorded fingerprint no longer matches what its
inputs would give is stale and is run again.
