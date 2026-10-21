# Fixing and forcing question/answer matches (plan)

**Status: built.** Every step below is built: keeping the extracted names and the review-sidebar
school combobox (#86); per-pair rejection with Unmatch and "Not this one" (#88); new schools during
review (#87); answer coverage and the all-or-none warnings (#89); wider automatic matching (#90); the
popup and the Pairing block (#91); the answer mapping table (#92); and the **Match** button on Review
queue cards (#93: frontend step 5, with `extracted_school` added to the job list summary). What
exists today is in [features/qa-pairing.md](../features/qa-pairing.md); this plan is kept for its
rationale.

Terms: the **no-match paper** is the paper being matched (question or answer-only); a **found
booklet** is a candidate partner for it.

## What exists

- **Same booklet:** the pipeline matches answers to questions. On the review page the admin can move
  any answer box to another question, make it an orphan, give an orphan to a question, or draw a
  missing answer box ([auto-import.md](../features/auto-import.md#editing)).
- **Answer-only paper → confirmed paper:** automatic `proposed` match on the seven-field key
  (one-click Attach), or the Match panel's search + Attach.
- **Answer-only paper → pending question paper of another job:** automatic link on the seven-field
  key, or the Match panel's Link. Unlink exists on both sides. Automatic linking also runs from the
  question side and within one booklet (#90); linking by hand is still across jobs only.
- Answers always go onto questions **by question number**.
- **Extracted names were lost when they did not match exactly** (fixed by #86: they are now kept as
  `extracted` and shown in the review sidebar's school combobox).

## The gaps

1. Only an answer-only paper can go looking for its partner, through a panel of filters that hide
   near misses. A question paper with no answers cannot search, and two papers in the same booklet
   that the pipeline failed to pair cannot be linked at all.
2. A school that is not in the reference list cannot be entered during review; the admin has to
   leave the review, add it on the Reference page, and come back.
3. Unlink set both rows `unlinked`, which blocked *all* automatic linking for them until their
   metadata changed, not just the one wrong pair, and a wrong `proposed` match to a confirmed paper
   could not be dismissed (fixed by #88: Unmatch and "Not this one" reject only that pair).
4. Numbering is assumed to agree (Section B restarting at 1, answers numbered `3a`/`3b`).
5. No undo after confirm. **Not addressed:** a confirmed paper is assumed not to change much, so
   detaching answers after confirm is [not planned](#not-planned).

## Agreed: the "Match this paper" popup

### Where it opens

- **Review page:** a Pairing block on every paper that needs a partner, replacing today's Match
  panel and the question-side banner.
- **Review queue:** a **Match** button on each such paper line of a card, so pairing does not need
  the job opened.

A paper **needs a partner** when it is pending and either an answer-only paper, or a question paper
whose own booklet had no answers at all (see [Answers are all or none](#answers-are-all-or-none)).
Its Pairing block shows one of:

| State | Shown | Actions |
|---|---|---|
| No partner (no match found, or several) | "No match found" / "N possible matches" | **Match this paper…** |
| Linked to a pending paper (auto or by an admin) | Partner's filename, key and details, and "matched automatically" or "matched by an admin" | **Check answers…**, **Change match…**, **Unmatch** |
| Answer-only paper with a proposed bank paper | "Answers match <paper>" | **Attach…**, **Change match…**, **Not this one** |

**Check answers…** and **Attach…** open the [answer mapping table](#the-answer-mapping-table).

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
  - for an answer-only paper only, papers already in the bank **that have no answers**.

  A question paper never matches a bank paper, because that pair would be a duplicate. A bank paper
  that already has answers is listed greyed out, marked "Already has answers", with no action, so
  the admin can see why an expected match cannot be used.
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
  - whether it is already paired with something else;
  - for a bank paper with answers on only some questions, a warning (see below).
- **Action:** **Pair**, which links a pending paper, or **Attach**, which attaches to a bank paper.
  Either one moves on to step 3, the mapping table, before anything is saved. Pairing with a pending booklet that is already paired elsewhere is allowed, with the warning
  "This will unpair it from <file>", as the Link route does today. The old pair is unlinked without
  recording a rejection, so automatic matching may still propose it later.
  Attach asks append/replace only for a partly answered bank paper — the one case where a question
  can already have answer pages.

### Answers are all or none

A paper has answers on **every** question or on **none**. Anything in between breaks the rule and
raises a **warning**, never a hard stop: the admin can always go ahead.

- **"Has answers"** means at least one answer page: `question_image.page_type = 'answer'` on a
  bank paper, an answer box on a pending one.
- **Pairing or attaching** checks the pair in the mapping table before the admin commits. If some
  questions would get no answers, or some answers have no question, the table says so ("Q11, Q12
  would get no answers"; "Answer 13 has no question").
- **A partly answered bank paper** (from before this rule, or from a manual import) is a normal
  candidate, with "Only 8 of 12 questions have answers". Attaching to it asks append/replace.
- **A question paper whose own booklet answered only some questions** counts as having answers: it
  gets no Match button. The review page and Confirm warn "Q5–Q7 have no answers"; the admin fixes
  it with the answer-box editor or confirms anyway. Adding the missing answers from a second
  booklet is not supported: automatic matching never links it, pairing by hand refuses it, and the
  popup greys it out as "Already has answers", like a fully answered bank paper.
- **Confirm** of a pending paper, or a linked pair, shows the same warning when the confirmed
  paper(s) would end up partly answered.

**3. Mapping table, then save.** The popup shows the
[answer mapping table](#the-answer-mapping-table) for the chosen booklet; its **Pair** / **Attach**
button saves the pair and the mapping together. After that it works as today: a linked pair settles
when the question paper is confirmed, and an attach settles the answer paper at once.

### The answer mapping table

Shown between choosing a booklet and saving, and again from **Check answers…** on a linked pair. It
covers answers coming from **another** booklet; answers inside the same booklet are still fixed
with the answer-box editor.

- **Each question is shown beside the answers that will go onto it,** pre-filled by number, with
  thumbnails of both.
- **The admin can change any row,** or shift all answers by ±N (for a Section B that restarts
  at 1).
- **Warnings** for questions left without answers, and answers left without a question, update as
  rows change (see [Answers are all or none](#answers-are-all-or-none)).
- **What the admin confirms is what gets attached.** For a linked pair the mapping is stored and
  used when the question paper is confirmed; a pair linked automatically uses the by-number mapping
  until someone edits it.
- **Changing the match** discards the stored mapping.

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
   - `ingest_paper.answer_map` (nullable JSON, on the answer paper's row: answer label → question
     label; NULL means by number);
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
     fields that agree and those that differ, its current partner, a preview, its question numbers
     and answer numbers, and its answer coverage (`none` / `partial` / `all`).
   - Bank papers with coverage `all` are returned flagged, not dropped, so the popup can grey them
     out.
   - This replaces `GET /papers/pending` and the Match panel's browser-side paper-number filter.
6. **Match route:**
   - callable from either role;
   - same job allowed;
   - optional `metadata` saved in the same transaction (the tick box);
   - optional `mapping` saved as `answer_map`; a new match clears any old one;
   - `DELETE` records a rejection;
   - refuses (409) an attach to a bank paper with coverage `all`.
7. **"Not this one" for a proposed bank paper:** records a rejection and re-runs matching.
   **Attach** takes an optional `mapping` and uses it instead of matching by number.
   **`PUT .../papers/{key}/answer-map`** saves an edited mapping on an existing link.
8. **Linked confirm:**
   - places answers by the stored `answer_map`, falling back to question number;
   - handles a pair from the same job (one lock, one `source.pdf`);
   - creates the new school and back-fills the id to other pending papers, as above.
9. **Job list summary:** gains answer coverage (`none` / `partial` / `all`) and `new_school_name`,
   so queue cards know which papers need a partner, can flag a partly answered one, and can name a
   new school.
10. **Automatic matching** never proposes a bank paper with coverage `all`.

**Frontend**

1. **`SchoolCombobox`:** type-to-search, closest-name suggestions for an unresolved extracted
   name, and "Use as a new school". It is used in the review page sidebar and in the popup.
2. **`MatchDialog`:**
   - fields and the tick box;
   - found booklets with exact and best lists, differing fields highlighted, and previews;
   - bank papers with answers greyed out, and the partly-answered warning;
   - the mapping table step, then Pair or Attach.
3. **`AnswerMappingTable`:** rows pre-filled by number, per-row change, shift ±N, and the
   unanswered/unplaced warnings. Used in the popup and from **Check answers…**.
4. **Pairing block on the review page,** for both roles. It replaces `MatchPanel.jsx` and the
   question-side banner.
5. **Queue cards:** a **Match** button on each paper line that needs a partner. A new school is
   named as "School: Raffles Instn (new)".
6. **Confirm:** disabled when a paper still has an unresolved school, with the reason shown; warns,
   without blocking, when a paper would be confirmed partly answered.

**Order:** backend 1–4 with the combobox, then 5–8 with the popup, mapping table and Pairing block,
then the queue button. Each step updates [qa-pairing.md](../features/qa-pairing.md) and
[ai-labelling.md](../features/ai-labelling.md) and adds tests.

## Not planned

- **Detaching answers after confirm** (the earlier point E). A confirmed paper is assumed not to
  change much; a wrong attach is rare enough to fix by hand in Manage Papers.

The earlier points **A** (per-pair rejection), **B** (mapping table), **C** (pair from either side or
from the queue) and **D** (rank instead of filter) are all folded into the sections above.
