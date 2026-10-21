# Question/answer pairing

**Scope:** getting a paper's answers onto its questions when they arrive separately, either as an
answer booklet uploaded on its own or as a booklet whose answers are for a paper already in the
bank. The design rationale is in [ADR 0002](../adr/0002-qa-booklet-pairing.md); the job flow around
it is in [auto-import.md](./auto-import.md).

## Proposal papers have a role

| `role` | Comes from | Questions | Review page |
|---|---|---|---|
| `question` | A question section, with or without its answer section | `question_rects` (+ `answer_rects`) | Metadata sidebar, Confirm / Skip |
| `answer_only` | An answer section with no question section | Built from the numbered answer rectangles: `question_rects: []`, `answer_rects` filled | "Answer N (k rectangles)" list, [Pairing block](#the-pairing-block-and-match-this-paper), Skip |

- A proposal without `role` (an old job) is treated as `question`.
- A question section with no answer section adds a warning, both on the paper and at the top level,
  so question-only booklets are flagged.
- An `answer_only` paper cannot be confirmed (`422`). It is attached, linked or skipped.
- Proposal shape: [ingestion/README.md](../../ingestion/README.md#the-proposal).

## Per-paper metadata and the `ingest_paper` row

- **Metadata source:** each paper's metadata is read from its own cover
  ([ai-labelling.md](./ai-labelling.md#paper-metadata-extraction)). A school name that matched no
  school is kept (`extracted.school`) and shown on the review page, but it counts as blank for
  matching until the admin picks a school or types it as a [new school](#new-schools).
- **The `ingest_paper` row** ([DATA_MODEL.md](../DATA_MODEL.md#auto-import-jobs)) is one row per
  proposed paper. It holds the role, the seven-field key, metadata source, status, the created or
  attached paper, the link and the match result.
- **When it is written:**

  | Event | What changes |
  |---|---|
  | `report` finishes | Upserted, with metadata source `cover`, or `filename` for old jobs. A re-run refreshes cover metadata only while the paper is pending and the admin has not edited it. |
  | Sidebar edit (`PUT .../papers/{key}/metadata`) | Stores the values (and `new_school_name`, see [New schools](#new-schools)); source becomes `admin` if a value changed. `409` unless the job is `review_ready` and the paper pending; unknown key → `404`. Re-runs matching. |
  | Confirm, skip or attach | Status and `paper_id`, in the same transaction as the job outcome. Confirming a new school also gives its id to the other pending papers carrying its name. |

- **Source of truth:** the proposal JSON holds the paper's contents and `report.review_outcome` the
  decision. `ingest_paper` mirrors role, metadata and status for querying and matching.
- **Seven-field key:** `school_id, year, level_id, subject_id, exam_type_id, stream_id,
  paper_number`.
- **`paper_number` comparison:** trimmed and case-folded only (`"2A"` = `" 2a "`, but ≠ `"02A"`).
  There is no normalisation; see [Not built](#not-built).

### New schools

The admin can enter a school that is not in the reference list during review, without leaving for
the Reference page. Nothing is added to the list until a question paper is confirmed, so a skipped
job or a typo leaves nothing behind.

- **Before confirm,** the row holds the typed name in `new_school_name` and no `school_id`. The
  review sidebar sends it on `PUT .../papers/{key}/metadata`; a name equal to an existing school
  (trimmed, any case) is stored as that school's id instead, and choosing a school drops the name.
- **Matching** treats two papers as having the same school if their `school_id`s are equal, or if
  both have no id and the same `new_school_name` (trimmed, case-folded). A new school counts as a
  known field. A bank paper always has an id, so a new-school paper only matches pending papers
  (rules 4–5 below; rules 2, 3 and 6 find nothing).
- **Confirming a question paper** with `new_school_name` and no `school_id`: finds the school by
  case-insensitive name, creating it if missing (another admin may have created it meanwhile), uses
  its id for the paper, and gives the same id to every other pending paper carrying that name, all
  in the confirm's transaction. Neither a `school_id` nor a name → `422`.
- **Attaching answers to a bank paper** creates nothing: the bank paper's school is kept.
- **Only school** accepts new values; subject, stream, level and exam type still need the Reference
  page.

## Answers are all or none

A paper has answers on **every** question or on **none**. Anything in between raises a
**warning**, never a hard stop: the admin can always go ahead. The refusals are attaching to a
bank paper that already has answers everywhere, and pairing a pending question paper that has any
answers of its own.

- **Answer coverage** (`app/services/answer_coverage.py`) is `none`, `partial` or `all`. A paper
  with no questions is `none`.
  - **Pending paper:** a question "has an answer" when it has an answer box (`answer_rects`) in
    the job's current proposal (the admin's edit, else the worker's). `job_coverage(job)` gives
    `{key: {answer_coverage, unanswered}}`; an answer-only paper covers its own entries, so it is
    normally `all`.
  - **Bank paper:** a question has an answer when it has a `question_page` with
    `page_type = 'answer'`. `bank_coverage(db, paper_ids)` computes it in one query.
- **Job list summary:** each paper carries `answer_coverage` and `unanswered` (its question numbers
  without an answer box), from its own booklet only. The review queue flags a pending question
  paper whose coverage is `partial` ("Q5–Q7 have no answers"), and gives one whose coverage is
  `none` a [**Match** button](#from-the-review-queue).
- **Automatic matching** never counts a bank paper with coverage `all` as a candidate, exact or
  partial. A partly answered bank paper is still a normal candidate.
- **Attach** to a bank paper with coverage `all` is refused (`409`).
- **Another booklet's answers go only onto a question paper with none of its own.** A pending
  question paper is a pairing target only while its coverage is `none`; a partly answered one counts
  as answered, exactly like a fully answered one. Automatic matching never links it (from either
  side), [pairing by hand](#pairing-by-hand) refuses it (`409`), and the popup greys it out as
  "Already has answers". Coverage is read from the job's current proposal, so removing the boxes in
  the answer-box editor makes the paper a target again.
- **A question paper whose own booklet answered only some questions** counts as having answers: it
  cannot be paired, and its missing answers cannot come from a second booklet. Its review page shows "Q5–Q7 have no answers. Add them with the answer-box editor, or confirm anyway."
  above **Confirm paper**, which stays enabled. The warning follows the admin's box edits.
- **A linked pair** is judged as it will be confirmed: the questions the linked answers land on
  (`matches[key].answer_numbers`, placed by the pair's [mapping](#the-answer-mapping-table)). It
  warns when that is partial. A question paper with no answers at all is not warned about; it needs
  a partner instead.

## Attaching answers to an existing paper

`POST /api/import/jobs/{id}/attach` `{key, paper_id, mode?, mapping?}`.

- **Refused when:** the paper is not `answer_only` → `422`; the target paper is unknown → `404`;
  the job is not `review_ready`, the paper is already decided, or every question of the target
  already has answers ([coverage](#answers-are-all-or-none) `all`) → `409`.
- **Placing:** by `mapping` (the [answer mapping table](#the-answer-mapping-table)'s
  `{answer label: question label | null}`) where it names an answer, else by question number.
  `1`, `"1"` and `" 01 "` all mean 1. Several answers on one question have their rectangles merged.
  - Answers that land on no question of the target (a number that is not a plain integer, like
    `"3a"`, with no mapping; a number or mapped label the target lacks; or mapped to `null`) are not
    attached. They are returned in `unmatched` and recorded on the row and the event.
  - Nothing placed at all → `422`, and nothing changes.
- **Mode, per question:**
  - `replace`: the question's existing answer pages are removed.
  - `append`: new answer pages go after the existing ones.
  - Omitted: `replace` if the question has no answer pages, else `append`.
- **UI:** **Attach** in the popup, or **Attach…** on a proposed paper; both go through the mapping
  table, which sends its `mapping`. The table asks append or replace (default **append**) only when
  the bank paper is partly answered (coverage `partial`); otherwise it sends no `mode`.
- **New answer pages:** cropped like confirm, with provenance, and written with collision-safe
  `page_order`.
- **One transaction:** the page rows, `review_outcome[key] = attached` (`paper_id` is added to
  `confirmed_paper_ids`), the `ingest_paper` row (`attached`, `paper_id`) and a `paper_attached`
  event.
  - On failure the paper is unchanged and the temp crops are removed.
  - Replaced answer images and temp crops are deleted after the commit.
- **Response:** `{attached, unmatched, modes, job_settled, job_status}`. `attached` counts as
  decided for settling the job.

## The Pairing block and "Match this paper"

A paper **needs a partner** when it is pending and either answer-only, or a question paper whose
own booklet had no answers at all ([coverage](#answers-are-all-or-none) `none`; a partly answered
one is warned about instead). A paper with no questions can only be skipped.

### The Pairing block

On the review page (`PairingBlock.jsx`), above the metadata sidebar of a question paper and in
place of it on an answer-only paper, on every paper that needs a partner or has one:

| State | Shown | Actions |
|---|---|---|
| No partner | "No match found" / "N possible matches" (exact candidates for the paper's current details) | **Match this paper…** |
| Linked to a pending paper | "Paired with <filename> (<key>)" ("this file" for the same booklet), the partner's details, and "matched automatically" or "matched by an admin" | **Check answers…**, **Change match…**, **Unmatch** |
| Answer-only paper with a proposed bank paper | "Answers match <paper>" | **Attach…**, **Change match…**, **Not this one** |

- **Check answers…** opens the [answer mapping table](#the-answer-mapping-table) for the pair; its
  **Save** stores the edited mapping (`PUT .../answer-map`).
- **Attach…** opens the mapping table for the proposed paper; its **Attach answers** attaches with
  that mapping. It asks append or replace (default append) only when the proposed paper is partly
  answered (`proposal.paper.answer_coverage` `partial`).
- **Change match…** opens the popup. **Unmatch** and **Not this one**: [Rejecting a
  match](#rejecting-a-match).
- An attach shows what was attached and which numbers were not, then **Continue** moves on.

### The popup

`MatchDialog.jsx`, opened by **Match this paper…** or **Change match…**, or by a queue card's
[**Match** button](#from-the-review-queue).

- **Fields:** subject, stream, level, school, exam type, year, paper number, pre-filled from the
  paper. Each reference field is a type-to-search picker of existing entries; school is the
  [school combobox](#new-schools) (an unresolved extracted school is shown in amber and counts as
  blank). Clearing a field means "any".
- **Search** (`GET .../papers/{key}/candidates`, below) re-runs as the fields change (debounced).
  **Exact matches** are listed; when there are none, **Best matches**, with each differing field
  highlighted ("paper no. 2A ≠ 2").
- **Each row:** where the booklet is ("In the bank (paper 7)", "Pending in <file> (<key>)", "Same
  file (<key>)"), its details in words, its first question beside this paper's first answer (or the
  other way round for a question paper), "This will unpair it from <file>" when it is paired
  already, and for a bank paper "Only 8 of 12 questions have answers" (partly answered). Greyed out
  with no action, "Already has answers": a bank paper with answers on every question, or a pending
  question paper with any answers of its own (`alreadyAnswered` in `pairing.js`).
- **Pair** (a pending booklet) or **Attach** (a bank paper) moves on to the
  [answer mapping table](#the-answer-mapping-table) for that booklet; nothing is saved yet. Its
  **Pair** button links the two papers and stores the mapping; its **Attach answers** button attaches
  with the mapping, asking append or replace only for a partly answered paper. **Back** returns to
  the list.
- **Also update this paper's details** (ticked by default) saves the fields on the paper with the
  pair, in the same transaction. Untick it when you only cleared fields to widen the search. It is
  shown only while a pending booklet is listed: an answer paper's own details are not kept after an
  attach.
- Before saving, any pending proposal edit is flushed (the server crops the saved proposal).

### From the review queue

On the [Review queue](./auto-import.md#review-queue), each paper line that needs a partner has a
**Match** button that opens the same popup without opening the job (`ReviewQueuePage.jsx`).

- **Which lines:** decided from the job list summary (`needsPartner` in `reviewQueueText.js`): a
  pending paper that is not linked and has questions, and is answer-only or has
  `answer_coverage` `none`. A linked paper's match is changed or undone on the review page.
- **Pre-filled** from the summary's fields, with `extracted_school` as the unresolved school.
- **No previews of the paper's own pages:** the queue has no page images, so only the candidates'
  thumbnails show. The mapping table loads its own previews (`GET .../answer-map`).
- After a pair or an attach the popup closes and the queue refreshes, so the card shows the new
  state (or leaves the queue once every paper is decided).

### Candidates

`GET /api/import/jobs/{id}/papers/{key}/candidates` with the field values as query parameters
(`school_id` or `new_school_name`, `year`, `level_id`, `subject_id`, `exam_type_id`, `stream_id`,
`paper_number`), in `app/services/match_candidates.py`. Returns `{exact, best}`. Unknown key →
`404`.

- **Blank means "any":** only the given fields are compared, each **exactly** (`paper_number`
  trimmed and case-folded; schools [as in matching](#new-schools)). There is no fuzzy matching.
- **Exact:** every given field agrees (at most 50). **Best**, only when nothing is exact: the top 10
  by number of agreeing fields; a booklet agreeing on none is left out.
- **Sources:**
  - pending papers of the other role (an answer-only paper finds question papers and vice versa) in
    `review_ready` jobs or in the paper's own job (its own job first, then newest), not the paper
    itself nor its current partner. Rejected pairs are listed: the admin may still pair them by hand;
  - for an answer-only paper only, bank papers. A question paper never matches a bank paper (that
    would be a duplicate).
  - Candidates that cannot take the answers are returned, not dropped, with their
    `answer_coverage`, so the popup can grey them out: bank papers with coverage `all`, and pending
    question papers with any answers of their own (coverage `partial` or `all`).
- **Each candidate:** `kind` (`pending`/`bank`), `ingest_paper_id` or `paper_id`, `job_id`,
  `filename`, `paper_key`, `same_job`, `role`, `details` (the seven fields and `new_school_name`),
  `agree` and `differ` (field names), `partner` (`{ingest_paper_id, job_id, filename, paper_key}`
  or null), `preview` (a pending paper: `{number, url, page, rect}` of its first question, or first
  answer for an answer-only paper; a bank paper: `{number, url}` of its first question image),
  `question_numbers`, `answer_numbers`, `answer_coverage`.

### Pairing by hand

`POST /api/import/jobs/{id}/papers/{key}/match {ingest_paper_id, metadata?, mapping?}`.

- **Either role:** an answer-only paper pairs with a pending question paper and a question paper
  with a pending answer-only paper, of another `review_ready` job **or the same job**. Anything else
  (same role, itself, a decided paper, a job no longer under review) → `422`; unknown key or target
  → `404`; this job not `review_ready`, this paper decided, or the question paper of the pair has
  answers of its own ([coverage](#answers-are-all-or-none) not `none`) → `409`.
- Sets `matched_ingest_paper_id` on both rows (no automatic status: "matched by an admin") and
  releases any earlier link of either one **without** rejecting it, so automatic matching may still
  propose that old pair later.
- **`metadata`** (the seven fields and `new_school_name`, as `PUT .../metadata` takes them) is saved
  on this paper first, in the same transaction; a refused pair saves nothing.
- **`mapping`** is stored as the answer paper's `answer_map`, whichever side the pair was made
  from; omitted, the pair goes by number. Any mapping of an earlier link of either paper is
  discarded.
- **Response:** `{matches, proposal}`, as Unmatch's.
- Answers are placed by the mapping, else by question number, when the question paper is confirmed
  ([Confirming a linked pair](#confirming-a-linked-pair)).

## The answer mapping table

Which answers go onto which questions when an answer-only paper is paired or attached
(`AnswerMappingTable.jsx`, `app/services/answer_mapping.py`). It is shown between choosing a
booklet in the popup and saving, from **Check answers…** on a linked pair, and from **Attach…** on a
proposed bank paper. It covers answers coming from **another** booklet; answers inside one booklet
are fixed with the answer-box editor ([auto-import.md](./auto-import.md#editing)).

- **A mapping** is `{answer label: question label | null}`. An answer's label is its number as
  written, trimmed (`"1"`, `"3a"`); `null` leaves it off. An answer the mapping does not name goes
  onto the question with its number.
- **The table:** each question, with a thumbnail, beside the answers that will go onto it, each with
  a thumbnail and a picker to move it to another question or to **Not placed**. Answers placed
  nowhere are listed last. Rows start by number, or from the pair's stored mapping.
  - **Shift all answers by N** re-places every answer by number + N (a Section B that restarts at
    1), discarding row edits.
  - **Warnings**, updated as rows change and never blocking: "Q11–Q12 would get no answers" (a
    question with no answers placed and none of its own) and "Answer 13 has no question".
- **Where it is kept:** on the answer paper's `ingest_paper.answer_map`
  ([DATA_MODEL.md](../DATA_MODEL.md#auto-import-jobs)). NULL means by number, which is what an
  automatic link uses until someone edits it.
- **Changing the match discards it:** a new pair, Unmatch, skipping either paper, or an automatic
  link that is dropped (a metadata edit that breaks the key) all clear it. An automatic link that is
  re-made with the same partner on a re-match keeps it.
- **Used** by the linked confirm ([Confirming a linked pair](#confirming-a-linked-pair)) and by
  attach (sent as its `mapping`; an attach's mapping is not stored).

**Endpoints:**

- `GET /api/import/jobs/{id}/papers/{key}/answer-map` with `ingest_paper_id` (a pending booklet),
  `paper_id` (a bank paper; an answer-only paper only, else `422`) or neither (the paper's current
  link; none → `409`). Either role may ask. Returns `{questions, answers, mapping}`:
  - `questions`: `{label, answered, preview}` in order; `answered` means it has answers of its own
    (answer boxes on a pending paper, answer pages on a bank paper);
  - `answers`: `{label, preview}`, the answer paper's entries with answer boxes;
  - `preview`: as a candidate's (a page crop for a pending paper, the question image for a bank
    paper), or null;
  - `mapping`: the pair's stored mapping if the partner is the current link, else null.
  Unknown key or partner → `404`; a partner of the same role → `422`.
- `PUT /api/import/jobs/{id}/papers/{key}/answer-map {mapping}` saves an edited mapping on a linked
  pair, from either side (`null` goes back to by number). `409` unless the job is `review_ready` and
  the paper pending and linked; unknown key → `404`. Returns `{matches, proposal}`.

## Automatic matching

For each **pending answer-only** paper, and from the **question side** for each pending question
paper (rules 4–5 only: a question paper never matches a bank paper). The result is stored on its row
(`match_status`, `proposed_paper_id`, `match_note`).

- **Same booklet:** a pending partner may be in the paper's own job, so a question paper and an
  answer-only paper of one booklet that the pipeline did not pair are linked on the seven-field key.
  The own job counts whatever its status, because `report` matches before the job turns
  `review_ready`; other jobs must be `review_ready`.

**Order of rules:**

| # | Situation | Result |
|---|---|---|
| 1 | Linked to a pending question paper (admin link, or an auto link that still holds) | Untouched; any proposal is hidden |
| 2 | All seven fields known, exactly one confirmed paper with that key | `proposed`. The Pairing block shows "Answers match <paper>" with **Attach…**, **Change match…** and **Not this one** |
| 3 | All seven known, several confirmed papers share the key | `manual` ("N papers have this key") |
| 4 | All seven known, no confirmed match, exactly one pending `question` paper with the same key, not linked to anything, with no answers of its own, in another `review_ready` job **or the same job** | **Auto link** on both rows (`match_status = auto`, "auto-linked") |
| 5 | Same as 4, but several pending question papers | `manual` ("N pending question papers have this key") |
| 6 | Otherwise, if papers share `school_id` + `year` + `subject_id` (all three known; never for a [new school](#new-schools)) | `manual` ("partial: … differ" / "partial: unknown …") |
| 7 | Otherwise | NULL (nothing to do) |

- **`manual`** leaves the paper unpaired; the Pairing block offers **Match this paper…**.
- **Auto links** are recomputed from scratch on every re-evaluation, so a metadata change that breaks
  the key drops them (and their [mapping](#the-answer-mapping-table); one re-made with the same
  partner keeps it).
- **Fully answered bank papers are skipped** by rules 2, 3 and 6: a confirmed paper whose
  [coverage](#answers-are-all-or-none) is `all` is never a candidate.
- **Answered question papers are skipped** by rules 4 and 5: a pending question paper whose coverage
  is not `none` is never linked, and from the question side such a paper looks for no partner.
- **Rejected pairs are skipped** by every rule: a rejected candidate is not counted, proposed,
  linked or used as a partial hint ([Rejecting a match](#rejecting-a-match)).
- **Settling** an answer paper (attach or skip) clears its proposal.

**When matching runs:**
- At the end of `report`, in the same transaction as the proposal. This also links the job's
  question papers to pending answer papers with the same key, of older jobs or of the same job. If
  several answer papers share the key, none is linked: the question paper and those answer papers
  are all marked `manual` ("N pending answer papers have this key").
- On `PUT .../papers/{key}/metadata`, of an answer-only or a question paper. The response includes
  the new `proposal`.
- On Unmatch (both papers) and on "Not this one".
- On every new paper (auto-import confirm and manual import). Pending answer-only papers sharing the
  new paper's school, year and subject are re-matched, so the new paper becomes a ready-to-attach
  target. This runs in a savepoint and never fails the confirm.

**Review response:**
- `matches`: `{key: {ingest_paper_id, job_id, filename, paper_key, details, matched_by,
  answer_numbers}}`, covering manual and auto links. `details` are the partner's seven fields and
  `new_school_name`; `matched_by` is `auto` or `admin`. `answer_numbers` are the partner's question numbers that have an answer box;
  for a question paper they are the questions its confirm puts the linked answers on, by the pair's
  mapping. `answer_map` is the pair's stored [mapping](#the-answer-mapping-table), or null (by
  number).
- `proposals`: `{key: {status, note, paper}}`; `paper` carries the proposed paper's
  `answer_coverage`.

## Rejecting a match

Turning down one wrong pair rejects only that pair. It is recorded in `ingest_match_rejection`
([DATA_MODEL.md](../DATA_MODEL.md#auto-import-jobs)); automatic matching never proposes or
auto-links it again, but both papers stay free to match something else. Nothing lifts a rejection,
not even a metadata edit; the admin can still link the pair by hand.

- **Unmatch** (`DELETE /api/import/jobs/{id}/papers/{key}/match`, from either side of a link,
  auto or by hand): breaks the link on both rows, rejects the pair, and re-matches both papers, so
  either may be linked to, or proposed, another partner at once.
- **Not this one** (`DELETE /api/import/jobs/{id}/papers/{key}/proposed-paper`, an answer-only
  paper with a `proposed` bank paper): rejects that bank paper and re-matches the paper, which may
  propose another bank paper, auto-link a pending question paper, or find nothing. `404` for an
  unknown key; `409` unless the job is `review_ready` and the paper pending with a proposal.
- **Response** of both: what the paper has now, `{matches, proposal}` (each as in the review
  response, or null). The review page shows it in place of the old link or proposal.

## Confirming a linked pair

When a question paper is linked to a pending answer-only paper, of another job or of the same job,
confirming it also attaches those answers and settles both papers.

- **Locking:** both job rows are locked, lowest job id first. A same-job pair locks its one job.
- **The answer paper is used only if:**
  - its job is still `review_ready`
  - the paper is still pending and undecided
  - it still links back

  Otherwise the confirm proceeds without it and logs a warning.
- **Cropping:** answer rectangles come from the **answer job's** `source.pdf` (its edited proposal
  if any). For a same-job pair that is the one `source.pdf`, read once. They are placed by the answer paper's stored
  [`answer_map`](#the-answer-mapping-table), falling back to question number, and added **after** the question paper's own answer
  pages (it has none when the link was made: [answers are all or
  none](#answers-are-all-or-none)), with provenance from the answer job's PDF.
- **Unplaced answers** (no question with that number or mapped label, or mapped to `null`) are
  returned in `unmatched`. If none is placed, the answer paper stays pending and linked, and
  `answers_from` is null.
- **One transaction:**
  - question paper `confirmed`, answer paper `attached` (with `paper_id`), in both jobs' outcomes and
    `ingest_paper` rows
  - events on both jobs (`paper_confirmed` with `answers_from_job`; `paper_attached` with `via_job`)
  - each fully decided job becomes `confirmed`, and its prefix is dropped after the commit (a
    same-job pair is judged after both outcomes are recorded, so confirming it can settle the job)
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
