# 0002. Pair question and answer booklets by metadata, and attach answers to a confirmed paper

Status: accepted

## Context

Schools often publish a paper's questions and its answers as two PDFs, and the admin uploads them
as two jobs. The pipeline handles one booklet at a time, so the two jobs know nothing of each other:

- The answer-only job's rectangles had no question section to be matched to and collapsed into
  numberless `orphan_answers`. Confirming it returned 422, so the answers were lost.
- A question-only booklet raised no warning, so nothing told the admin the answers were missing.
- The metadata extractor reads only the filename, returns no `stream`, and runs once per job
  although a booklet can hold several papers.
- The `paper` table has no unique constraint, so the same paper can be imported twice.

The full plan is in `docs/plans/ingest-hardening-and-qa-pairing.md` (Phase 4).

## Decision

Treat a question paper and its answers as two **papers** in a proposal that are matched afterwards,
rather than forcing them into one job.

- **A paper has a `role`**: `question` (the usual paper) or `answer_only` (an answer section with no
  question section of its own). A proposal without `role` is a `question` paper.
- **An answer-only paper keeps its question numbers.** Its numbered rectangles become questions with
  empty `question_rects` and populated `answer_rects`, instead of `orphan_answers`. The review page
  groups them by number. It cannot be confirmed as a paper (422); it can be **attached** to a
  question paper or skipped. Review validation allows empty `question_rects` only for an
  `answer_only` paper; every rectangle check stays strict.
- **A question section with no answer section adds a warning**, so question-only booklets are flagged.
- **Cover pages come from the existing segment call** (an optional `cover_pages` per segment), not a
  second model call. Metadata is then read per paper from its cover pages (plus `stream`), in a new
  `after_segment` hook, and stored per paper.
- **A queryable `ingest_paper` row per proposal paper** (key, role, the seven metadata fields,
  `metadata_source`, status `pending|confirmed|skipped|attached`, links to the confirmed `paper` and
  to a matched `ingest_paper`) replaces the per-paper facts buried in `job.report`.
- **Matching is automatic only when unambiguous.** The matching key is all seven paper fields:
  `school_id, year, level_id, subject_id, exam_type_id, stream_id, paper_number`. One candidate is
  proposed to the admin, who accepts with one click. Several candidates, or a partial match, are left
  for manual matching on the review page.
- **Attaching** (`attach_answers(job, key, paper_id, mode)`) crops the answer rectangles from the
  answer job's `source.pdf`, maps them to the paper's `Question` rows by number, adds `answer`
  `QuestionPage` rows and records the outcome `attached` in the same transaction as the page rows.
  Numbers with no matching question are reported back, never dropped.
  - Mode is `replace` when the question has no answer pages, because there is nothing to lose.
  - Otherwise the UI asks, defaulting to `append`.

## Consequences

- The answer-only job is no longer a dead end: its answers are numbered, reviewable and attachable.
- `ingestion/` only labels the role and builds the numbered questions; matching and attaching live
  in the webapp, which owns the database (`ingestion/` must not import `app`).
- Costs: one more table, a metadata call per paper rather than per job, and an attach flow to build
  and test.

## Deferred

- **A unique index on `paper`** over the seven-field key (with `paper_number` normalisation and a
  409 "this paper already exists, attach to it instead?" from `confirm_import`) is deferred. The live
  Supabase database may carry indexes the ORM and migrations do not show, so it must first be
  checked with `SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'paper';`, and any
  existing duplicates resolved by hand.

## Alternatives considered

- **One job per paper family (upload both PDFs together).** Needs a multi-file upload flow and
  breaks when the answers arrive later, which is the common case.
- **Always `replace` (or always `append`) on attach.** Replace loses answers already attached;
  append duplicates them. Hence replace only when there is nothing to lose, otherwise ask.
- **Match on school, year and paper number alone.** Ambiguous across subjects, levels and streams.
