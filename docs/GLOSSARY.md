# Glossary

The words this project uses on purpose. Most belong to ingestion
([features/ingestion-pipeline.md](./features/ingestion-pipeline.md),
[adr/0001-stage-pipeline.md](./adr/0001-stage-pipeline.md)) and Q/A pairing
([features/qa-pairing.md](./features/qa-pairing.md)).

## Pipeline

**Booklet** — One uploaded PDF: one or more question papers, often bound with their answer papers.

**Job** — One booklet being ingested: an id (a UUID in the webapp), a source PDF, a status and a
folder of artefacts. Made of tasks. Local statuses: `queued`, `running`, `done`, `failed`; the
webapp's lifecycle is in [features/auto-import.md](./features/auto-import.md).

**Stage** — A registered unit of work (`register`, `segment`, `split`, `scan`, `locate`, `render`,
`grid`, `ocr`, `questions`, `unrouted`, `report`) with a scope (job or section), a kind (cpu, api,
subprocess) and its dependencies. Boundaries sit where an external dependency lives, where a human
may edit the artefact, or where work is costly and separately useful; smaller steps are function calls.

**Task** — One run of one stage on one job (and one section, for a section stage); identity
`(job, section, stage)`. Status `pending`, `ready`, `running`, `done`, `skipped`, `failed` or
`blocked`, plus attempts, a lease, warnings and a reason or error.

**Soft need** — A dependency the stage waits for but does not require: it runs however the
predecessor ended (`questions` after `ocr`, `locate` after `scan`).

**Lease** — How long a claimed task stays its runner's without a heartbeat; when it lapses the task
is handed back automatically, up to the retry limit.

**Artefact** — A file a stage writes (atomically) under its job's folder (`segments.json`,
`_split/q1.pdf`, `manifest.json`, …). Stages hand work over only through artefacts.

**Section** — One labelled page range of a booklet: `q1`, `q2` for question papers, `a1`, `a2` for
their answer papers (an answer paper takes its question paper's index). Section stages run once per section.

**Template** — An answer section's shape: `table` (answers tabulated, no question text) or
`annotated_booklet` (the question booklet with answers written in). None when the model was unsure.

**Cover pages** — A section's cover/instruction pages outside its range; the webapp reads each
paper's metadata from them.

**Route** — The chain of section stages a section runs, chosen once at `split`: `question`
(question sections and `annotated_booklet` answers: `scan`, `locate`, `render`), `table` (table answers:
`grid`, `ocr`, `questions`, `render`) or `unrouted` (one `skipped` task with the reason).

**Scan** — A page that is one page-sized image with no text layer. Scans are deskewed and OCR'd:
tables cell by cell, question and annotated sections page by page (the `scan` stage). Their
rectangles and review images are in the straightened frame (`straightened_deg` on the proposal page).
A question section of mostly **picture pages** (born-digital, but the questions pasted in as images)
is OCR'd the same way.

**Flag / needs review** — A page or section a human should check, with a reason. Raised instead of
guessing or raising an error ("warn, never raise").

**Report** — `ingest.json`, written by `report` once every section task has settled: each section's
route, status (`extracted`, `not_routed`, `failed`), question count, warnings and review flag.

**Proposal** — What the pipeline offers for a booklet (`proposal.json` plus booklet-numbered page
images): its papers, each question's rectangles in PDF points on booklet pages, and every flag. A
suggestion for the admin to correct; nothing is a stored question until confirmed.

**Role** — A proposal paper is `question` (a question section, with or without answers) or
`answer_only` (an answer section with no question section; its answers keep their numbers and are
attached to a question paper rather than confirmed). See [adr/0002](./adr/0002-qa-booklet-pairing.md).

**Orphan answers** — Answer rectangles in a question paper whose number matches no question; kept
on the paper so nothing is lost.

**Fingerprint** — A hash of what a `done` task was produced from (input contents, the settings it
reads, its stage version). A task whose fingerprint no longer matches, or whose artefacts are gone,
is **stale** and reruns with everything downstream; one that matches completes without running.

**Retry** — A person's request to return a job's failed and blocked tasks, and everything
downstream, to the queue. Distinct from a lapsed lease, which is handed back automatically.

## Review and pairing

**Paper key** — How a proposal paper is named: its question label (`q1`), else its answer label
(`a1`), else `paper{n}`. Each proposal paper has one `ingest_paper` row keyed by it.

**Outcome / settled** — Each proposal paper ends `confirmed` (became a paper), `skipped`, or
`attached` (its answers went onto an existing paper). A job is **settled** when every paper has an
outcome (the job becomes `confirmed`), or when it is `cancelled` or `expired`; a settled job's S3
prefix is emptied.

**Seven-field key** — `school, year, level, subject, exam type, stream, paper number`: what
identifies a paper: matching to a bank paper needs all seven to agree; two pending booklets are
scored, and need only not disagree on any. A school typed during review that is not yet
in the reference list is a **new school**, created only when a question paper carrying it is confirmed.

**Link** — Pairs a pending answer-only paper with a pending question paper that has no answers of
its own (partly answered counts as answered), from another job or the same booklet; confirming the
question paper brings the answers in.

**Proposed attach** — The one confirmed paper an answer-only paper matches; the admin accepts it with
one click.

**Suggested pair** — A pending question paper that looks like an answer-only paper's partner, on
evidence too weak to link them unasked; the admin pairs it or turns it down ("Not a pair").

**Pair (review)** — A question paper and its linked answer-only paper in another booklet, shown as
one review queue card and reviewed on one page.

**Rejected pair** — A pair the admin turned down (Unmatch, "Not this one" or "Not a pair"); automatic matching
never offers it again, but both papers stay free to match others.
