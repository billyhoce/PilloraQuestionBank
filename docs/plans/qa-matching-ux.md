# Fixing and forcing question/answer matches (plan)

**Status: under review.** The "Match this paper" popup (below) is agreed in outline; a few small
points are still [open](#still-open). Nothing here is built yet. What exists today is in
[features/qa-pairing.md](../features/qa-pairing.md).

Terms: the **no-match paper** is the paper being matched (question or answer-only); a **found
booklet** is a candidate partner for it.

## What exists

- **Same booklet:** the pipeline matches answers to questions. On the review page the admin can move
  any answer box to another question, make it an orphan, give an orphan to a question, or draw a
  missing answer box ([auto-import.md](../features/auto-import.md#editing)).
- **Answer-only paper → confirmed paper:** automatic `proposed` match on the seven-field key
  (one-click Attach), or the Match panel's search + Attach.
- **Answer-only paper → pending question paper of another job:** automatic link on the seven-field
  key, or the Match panel's Link. Unlink exists on both sides.
- Answers always go onto questions **by question number**.
- **Extracted names are lost when they don't match exactly.** `resolve_metadata` keeps only ids; a
  cover that reads "Raffles Instn" leaves `school_id` blank and the text is discarded.

## The gaps

1. Only an answer-only paper can go looking for its partner, through a panel of filters that hide
   near misses. A question paper with no answers cannot search, and two papers in the same booklet
   that the pipeline failed to pair cannot be linked at all.
2. A school that is not in the reference list cannot be entered during review; the admin has to
   leave the review, add it on the Reference page, and come back.
3. Unlink sets both rows `unlinked`, which blocks *all* automatic linking for them until their
   metadata changes, not just the one wrong pair. A wrong `proposed` match to a confirmed paper
   cannot be dismissed.
4. Numbering is assumed to agree (Section B restarting at 1, answers numbered `3a`/`3b`).
5. No undo after confirm.

## Agreed: the "Match this paper" popup

### Where it opens

- **Review page:** a Pairing block on every paper that needs a partner, replacing today's Match
  panel and the question-side banner.
- **Review queue:** a **Match** button on each such paper line of a card, so pairing does not need
  the job opened.

A paper **needs a partner** when it is pending and either an answer-only paper, or a question paper
whose own booklet had no answers. Its Pairing block shows one of:

| State | Shown | Actions |
|---|---|---|
| No partner (no match found, or several) | "No match found" / "N possible matches" | **Match this paper…** |
| Linked to a pending paper (auto or by an admin) | Partner's filename, key and details, and "matched automatically" or "matched by an admin" | **Change match…**, **Unmatch** |
| Answer-only paper with a proposed bank paper | "Answers match <paper>" | **Attach**, **Change match…**, **Not this one** |

**Unmatch** and **Not this one** remember the rejected pair, so automatic matching never proposes
that pair again but stays free to find another (this replaces the blanket `unlinked` state).

### The popup

**1. Fields.** Subject, stream, level, school, exam type, year, paper number. Each is pre-filled
from the no-match paper.

- **School** is a combobox. Typing lists the existing schools that match. The last option is
  **Use "<typed text>" as a new school**.
- **Subject, stream, level and exam type** pick only from existing entries, with type-to-search.
- **A school the extraction read but could not resolve** (e.g. "Raffles Instn") is shown in amber
  as "*Raffles Instn* — not in the list", with the closest existing schools suggested first.
  - It counts as **blank** for searching.
  - The paper cannot be confirmed until the admin picks an existing school or chooses **Use as a
    new school**.
- **Also update this paper's details**, ticked by default, saves the fields to the no-match paper
  when it is paired. Untick it when you only cleared fields to widen the search.
  - It is hidden for an attach to a bank paper, because an answer paper's own details are not kept
    after attaching.

**2. Found booklets.** The search re-runs as the fields change.

- **Blank means "any":** only the filled-in fields must match.
- **Sources:**
  - pending papers in other jobs that are waiting for review;
  - pending papers in the **same** job, which today are excluded;
  - for an answer-only paper only, papers already in the bank.

  A question paper never matches a bank paper, because that pair would be a duplicate.
- **Exact matches** are listed first.
- **When there is no exact match, "Best matches" are listed instead:** the top 10, ranked by how
  many of the filled fields agree **exactly**.
  - The fields that differ are highlighted ("paper no. 2A ≠ 2").
  - There is no fuzzy name or number matching here; fuzzy suggestions exist only inside the school
    combobox.
- **Each row shows:**
  - where the booklet is ("In the bank", "Pending in <file>", or "Same file");
  - its details in words;
  - a thumbnail of its first question beside the no-match paper's first answer (or the other way
    round);
  - whether it is already paired with something else.
- **Action:** **Pair**, which links a pending paper, or **Attach**, which attaches to a bank paper.
  Attach asks append/replace only when a question already has answer pages, as today.

**3. After pairing.** It works as today: a linked pair settles when the question paper is
confirmed, and an attach settles the answer paper at once. The question ↔ answer mapping table
(point B under [Still to review](#still-to-review)) can later be placed between choosing a booklet
and pairing it.

### New schools are created on confirm

- **Before confirm,** the paper stores the typed name (`new_school_name`) and no `school_id`.
  Nothing is added to the reference list yet, so a skipped job or a typo leaves nothing behind.
- **Matching** treats two papers as having the same school if their `school_id`s are equal, or if
  both have no id and the same `new_school_name` (trimmed, case-folded). A bank paper always has an
  id, so a paper with a new school can only match pending papers.
- **Confirming a question paper:**
  1. Finds the school by case-insensitive name, creating it if it does not exist. Another admin may
     have created it in the meantime.
  2. Sets `school_id`.
  3. Gives the same id to every other pending paper that carries the same `new_school_name`.
- **Typing a name that already exists** (in any case) selects the existing school.
- **Attaching answers to a bank paper** creates nothing, because the bank paper's school is the
  one kept.
- **Other fields:** only school accepts new values. Subject, stream, level and exam type still need
  the Reference page.
- **Review page sidebar:** its school dropdown becomes the same combobox, with the same rule. The
  Manual import sidebar keeps its plain dropdown.

## Build plan

**Backend**

1. **Keep what was read.** `extract_paper_metadata` also returns the raw names
   (`report["paper_metadata"][key]["extracted"]`), and the review response carries them. Jobs
   processed before this change have none, so the popup shows nothing extra for them.
2. **Migration:**
   - `ingest_paper.new_school_name` (nullable string);
   - table `ingest_match_rejection (ingest_paper_id, rejected_ingest_paper_id | rejected_paper_id)`;
   - drop the use of `match_status = unlinked`.
3. **`PUT .../papers/{key}/metadata`** accepts `new_school_name`. A name equal to an existing school
   resolves to its id.
4. **`ingest_matching`:**
   - compare schools by id, or by `new_school_name` when neither paper has an id;
   - skip rejected pairs;
   - allow pending partners in the same job;
   - let question papers be matched to pending answer-only papers, not only the other way round.
5. **`GET .../jobs/{id}/papers/{key}/candidates`** with the field values as query parameters
   returns `{exact, best}`.
   - Each candidate carries its kind (`pending`/`bank`), ids, job, filename, key, details, the
     fields that agree and those that differ, its current partner, and a preview.
   - This replaces `GET /papers/pending` and the Match panel's browser-side paper-number filter.
6. **Match route:**
   - callable from either role;
   - same job allowed;
   - optional `metadata` saved in the same transaction (the tick box);
   - `DELETE` records a rejection.
7. **"Not this one" for a proposed bank paper:** records a rejection and re-runs matching.
8. **Linked confirm:**
   - handles a pair from the same job (one lock, one `source.pdf`);
   - creates the new school and back-fills the id to other pending papers, as above.
9. **Job list summary:** gains `has_answers` and `new_school_name`, so queue cards know which
   papers need a partner and can name a new school.

**Frontend**

1. **`SchoolCombobox`:** type-to-search, closest-name suggestions for an unresolved extracted
   name, and "Use as a new school". It is used in the review page sidebar and in the popup.
2. **`MatchDialog`:**
   - fields and the tick box;
   - found booklets with exact and best lists, differing fields highlighted, and previews;
   - Pair or Attach.
3. **Pairing block on the review page,** for both roles. It replaces `MatchPanel.jsx` and the
   question-side banner.
4. **Queue cards:** a **Match** button on each paper line that needs a partner. A new school is
   named as "School: Raffles Instn (new)".
5. **Confirm:** disabled when a paper still has an unresolved school, with the reason shown.

**Order:** backend 1–4 with the combobox, then 5–8 with the popup and Pairing block, then the queue
button. Each step updates [qa-pairing.md](../features/qa-pairing.md) and
[ai-labelling.md](../features/ai-labelling.md) and adds tests.

## Still open

1. **Pairing with a booklet that is already paired elsewhere.** The suggestion is to allow it with
   a warning ("This will unpair it from <file>"), as the Link route does today.
2. **A question paper whose own booklet had some answers.** The suggestion is that it gets no Match
   button, since its answers are already there. Adding answers from a second booklet would wait for
   point B.

## Still to review

The rest of the earlier proposal, not yet agreed:

- **B. A question ↔ answer table before anything is attached.**
  - Each question is shown beside the answers that will go onto it, pre-filled by number.
  - The admin can change any row, or shift all answers by ±N for a Section B that restarts at 1.
  - What the admin confirms is what gets attached.
  - *Backend:* an optional `mapping` on attach/link, stored as `answer_map` on the answer paper's
    row.
- **E. Detach after confirm.**
  - In Manage Papers, answer pages that came from an import are grouped as "Answers from <file>",
    with **Detach**.
  - Re-attaching means uploading the answer PDF again, because a settled job's files are deleted.

The earlier points **C** (pair from either side or from the queue) and **D** (rank instead of
filter) are folded into the popup above. Point **A** (per-pair rejection) is folded into Unmatch and
Not this one.
