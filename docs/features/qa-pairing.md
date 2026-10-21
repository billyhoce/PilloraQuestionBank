# Question/answer pairing

**Scope:** getting a paper's answers onto its questions when they arrive separately, either as an
answer booklet uploaded on its own or as a booklet whose answers are for a paper already in the
bank. The design rationale is in [ADR 0002](../adr/0002-qa-booklet-pairing.md); the job flow around
it is in [auto-import.md](./auto-import.md).

## Proposal papers have a role

| `role` | Comes from | Questions | Review page |
|---|---|---|---|
| `question` | A question section, with or without its answer section | `question_rects` (+ `answer_rects`) | Metadata sidebar, Confirm / Skip |
| `answer_only` | An answer section with no question section | Built from the numbered answer rectangles: `question_rects: []`, `answer_rects` filled | "Answer N (k rectangles)" list, Match panel, Skip |

- A proposal without `role` (an old job) is treated as `question`.
- A question section with no answer section adds a warning, both on the paper and at the top level,
  so question-only booklets are flagged.
- An `answer_only` paper cannot be confirmed (`422`). It is attached, linked or skipped.
- Proposal shape: [ingestion/README.md](../../ingestion/README.md#the-proposal).

## Per-paper metadata and the `ingest_paper` row

- **Metadata source:** each paper's metadata is read from its own cover
  ([ai-labelling.md](./ai-labelling.md#paper-metadata-extraction)). A school name that matched no
  school is kept (`extracted.school`) and shown on the review page, but it counts as blank for
  matching: only `school_id` is in the key.
- **The `ingest_paper` row** ([DATA_MODEL.md](../DATA_MODEL.md#auto-import-jobs)) is one row per
  proposed paper. It holds the role, the seven-field key, metadata source, status, the created or
  attached paper, the link and the match result.
- **When it is written:**

  | Event | What changes |
  |---|---|
  | `report` finishes | Upserted, with metadata source `cover`, or `filename` for old jobs. A re-run refreshes cover metadata only while the paper is pending and the admin has not edited it. |
  | Sidebar edit (`PUT .../papers/{key}/metadata`) | Stores the values; source becomes `admin` if a value changed. `409` unless the job is `review_ready` and the paper pending; unknown key → `404`. Re-runs matching. |
  | Confirm, skip or attach | Status and `paper_id`, in the same transaction as the job outcome. |

- **Source of truth:** the proposal JSON holds the paper's contents and `report.review_outcome` the
  decision. `ingest_paper` mirrors role, metadata and status for querying and matching.
- **Seven-field key:** `school_id, year, level_id, subject_id, exam_type_id, stream_id,
  paper_number`.
- **`paper_number` comparison:** trimmed and case-folded only (`"2A"` = `" 2a "`, but ≠ `"02A"`).
  There is no normalisation; see [Not built](#not-built).

## Attaching answers to an existing paper

`POST /api/import/jobs/{id}/attach` `{key, paper_id, mode?}`.

- **Refused when:** the paper is not `answer_only` → `422`; the target paper is unknown → `404`;
  the job is not `review_ready` or the paper is already decided → `409`.
- **Matching:** by question number. `1`, `"1"` and `" 01 "` all mean 1. Duplicate numbers have
  their rectangles merged.
  - Numbers that are not plain integers (`"3a"`), or have no question in the target, are not
    attached. They are returned in `unmatched` and recorded on the row and the event.
  - Nothing matching at all → `422`, and nothing changes.
- **Mode, per question:**
  - `replace`: the question's existing answer pages are removed.
  - `append`: new answer pages go after the existing ones.
  - Omitted: `replace` if the question has no answer pages, else `append`.
- **UI:** the UI fetches the target paper. It asks append or replace (default **append**) only when
  a receiving question already has answer pages; otherwise it sends no `mode`.
- **New answer pages:** cropped like confirm, with provenance, and written with collision-safe
  `page_order`.
- **One transaction:** the page rows, `review_outcome[key] = attached` (`paper_id` is added to
  `confirmed_paper_ids`), the `ingest_paper` row (`attached`, `paper_id`) and a `paper_attached`
  event.
  - On failure the paper is unchanged and the temp crops are removed.
  - Replaced answer images and temp crops are deleted after the commit.
- **Response:** `{attached, unmatched, modes, job_settled, job_status}`. `attached` counts as
  decided for settling the job.

## Match panel (manual)

On the review page of an answer-only paper (`MatchPanel.jsx`).

- **Filters:** subject, stream, level, school, exam type, year and paper number. Pre-filled from
  the paper's metadata; the search re-runs on every change.
- **Candidates:**
  - Confirmed papers, from `GET /api/papers`. That route has no paper-number filter, so the panel
    filters its first 50 results by paper number in the browser.
  - Pending question papers of other `review_ready` jobs, from `GET /api/import/papers/pending`:
    exact match on the given filters, `exclude_job_id`, newest job first. Each comes with a preview
    of its first question rectangle.
- **Preview:** the candidate's first question beside this paper's first answer.
- **Confirmed candidate → Attach** (above). A paper id can also be typed.
- **Pending candidate → Link:**
  - `POST .../papers/{key}/match {ingest_paper_id}` sets `matched_ingest_paper_id` on both rows and
    releases any earlier link of either row.
  - `422` unless this paper is answer-only and the target is a pending question paper of another
    review-ready job. `409` unless this job is `review_ready`.
  - `DELETE` on the same path unlinks both rows.
- **Link display:**
  - Answer side: "Linked to <filename> <key>" with Unlink.
  - Question side: "Answers available from <filename> (<key>) — they will be attached when you
    confirm", with Unlink.

## Automatic matching

For each **pending answer-only** paper. The result is stored on its row (`match_status`,
`proposed_paper_id`, `match_note`).

**Order of rules:**

| # | Situation | Result |
|---|---|---|
| 1 | Linked to a pending question paper (admin link, or an auto link that still holds) | Untouched; any proposal is hidden |
| 2 | All seven fields known, exactly one confirmed paper with that key | `proposed`. The panel shows "Answers match <paper> — Attach" (one click; asks append/replace only if needed) |
| 3 | All seven known, several confirmed papers share the key | `manual` ("N papers have this key") |
| 4 | All seven known, no confirmed match, exactly one pending `question` paper of another `review_ready` job, unlinked, same key | **Auto link** on both rows (`match_status = auto`, "auto-linked") |
| 5 | Same as 4, but several pending question papers | `manual` ("N pending question papers have this key") |
| 6 | Otherwise, if papers share `school_id` + `year` + `subject_id` (all three known) | `manual` ("partial: … differ" / "partial: unknown …") |
| 7 | Otherwise | NULL (nothing to do) |

- **`manual`** shows "Several or partial matches — pick one below" in the Match panel.
- **Auto links** are recomputed from scratch on every re-evaluation, so a metadata change that breaks
  the key drops them.
- **Unlinking** sets both rows to `unlinked`, which stops auto-linking until either paper's metadata
  is edited.
- **Settling** an answer paper (attach or skip) clears its proposal.

**When matching runs:**
- At the end of `report`, in the same transaction as the proposal. For a question job, this also
  links its question papers to older pending answer papers with the same key. If several answer
  papers share the key, none is linked: the question paper and those answer papers are all marked
  `manual` ("N pending answer papers have this key").
- On `PUT .../papers/{key}/metadata`. The response includes the new `proposal`.
- On unlink.
- On every new paper (auto-import confirm and manual import). Pending answer-only papers sharing the
  new paper's school, year and subject are re-matched, so the new paper becomes a ready-to-attach
  target. This runs in a savepoint and never fails the confirm.

**Review response:**
- `matches`: `{key: {ingest_paper_id, job_id, filename, paper_key}}`, covering manual and auto
  links.
- `proposals`: `{key: {status, note, paper}}`.

## Confirming a linked pair

When a question paper is linked to a pending answer-only paper of another job, confirming it also
attaches those answers and settles both papers.

- **Locking:** both job rows are locked, lowest job id first.
- **The answer paper is used only if:**
  - its job is still `review_ready`
  - the paper is still pending and undecided
  - it still links back

  Otherwise the confirm proceeds without it and logs a warning.
- **Cropping:** answer rectangles come from the **answer job's** `source.pdf` (its edited proposal
  if any). They are mapped by question number and added **after** the question paper's own answer
  pages, with provenance from the answer job's PDF.
- **Unmatched numbers** are returned in `unmatched`. If none match, the answer paper stays pending
  and linked, and `answers_from` is null.
- **One transaction:**
  - question paper `confirmed`, answer paper `attached` (with `paper_id`), in both jobs' outcomes and
    `ingest_paper` rows
  - events on both jobs (`paper_confirmed` with `answers_from_job`; `paper_attached` with `via_job`)
  - each fully decided job becomes `confirmed`, and its prefix is dropped after the commit
- **Response:** adds `answers_from` (`{job_id, filename, paper_key, attached}` or null) and
  `unmatched`. Both are shown above the topic review.

## Not built

**Duplicate-paper protection (#81)** waits on a live-DB check:
- `paper` has no unique index on the seven-field key, so duplicates are possible. Matching treats
  them as "several".
- Planned:
  - normalise `paper_number` on write ("P1", "Paper 1", "I" → "1"; letters kept)
  - add a unique index
  - turn a duplicate confirm into `409` "attach instead"
