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

**Route**
Which chain of section stages a section runs, chosen once when `split` fans out, mirroring
`ingester.router`: `question` (question sections and `annotated_booklet` answer sections: `locate`
then `render`), `table` (table answer sections: `grid`, `ocr`, `questions`, then `render`) or `unrouted` (nothing can take it; one `skipped` task
with the reason).

**Report**
`ingest.json`, written by the `report` stage once every section task of the job has settled
(whatever became of them): each section's route, status (`extracted`, `not_routed`, `failed`),
question count, warnings and review flag, plus the segment and split stages' warnings.

**Proposal**
What the pipeline offers for a booklet: its sections, the questions found in each and their
rectangles, with every flag raised along the way. A proposal is a suggestion for an admin to
review and correct; nothing in it is a stored question until the admin confirms it. It is
`proposal.json`, written by the `report` stage with the booklet-numbered review images in
`pages/`: one paper per question section, paired with its answer section by segment index, with
rectangles in PDF points on booklet pages (shape in `ingestion/README.md`). Each paper has a `role`:
`question`, or `answer_only` for an answer section with no question section, whose answers keep their
question numbers and are attached to a question paper rather than confirmed (docs/adr/0002-qa-booklet-pairing.md).

**Paper key**
How a proposal paper is named in the API: its question label (`q1`), else its answer label (`a1`),
else `paper{n}`. Each proposal paper has one `ingest_paper` row keyed by it.

**Outcome / settled**
Each proposal paper ends `confirmed` (became a paper), `skipped`, or `attached` (its answers were
added to an existing paper). A job is **settled** when every paper has an outcome, or when it is
cancelled; a settled job's S3 prefix is empty.

**Seven-field key**
`school, year, level, subject, exam type, stream, paper number`: what identifies a paper when
matching an answer booklet to its question paper. A school typed during review that is not in the
reference list yet is a **new school**: held by name on the pending paper and created only when a
question paper carrying it is confirmed.

**Link / proposed attach**
A **link** pairs a pending answer-only paper with a pending question paper of another job; confirming
the question paper brings the answers in. A **proposed attach** names the one confirmed paper an
answer-only paper matches; the admin accepts it with one click. A pair the admin turns down
(Unmatch, or "Not this one") is **rejected**: automatic matching never offers that pair again, but
both papers stay free to match another. See docs/features/qa-pairing.md.

**Fingerprint**
A hash of what a task's artefact was produced from (the content of the input artefacts, the
slice of configuration and options the stage reads, and its code version), recorded when the task is
`done`. A task whose recorded fingerprint no longer matches what its inputs would give, or whose
artefacts are gone, is stale and is run again, with everything downstream of it; one whose fingerprint
matches and whose artefacts exist completes without running.

**Retry**
Returning a job's failed and blocked tasks, and everything downstream of them, to the queue
(`pipeline retry`). Distinct from the lease: a task whose runner died is handed back automatically
until its retry limit; a retry is a person's request.
