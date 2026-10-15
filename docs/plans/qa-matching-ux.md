# Fixing and forcing question/answer matches (proposal)

**Status: proposed, awaiting confirmation.** Nothing here is built yet. What exists today is in
[features/qa-pairing.md](../features/qa-pairing.md).

## What exists

- **Same booklet:** answers are matched to questions by the pipeline. On the review page the admin
  can now move any answer box to another question, make it an orphan, give an orphan to a question,
  or draw a missing answer box ([auto-import.md](../features/auto-import.md#editing)).
- **Answer-only paper → confirmed paper:** automatic `proposed` match on the seven-field key
  (one-click Attach), or the Match panel's search + Attach.
- **Answer-only paper → pending question paper of another job:** automatic link on the seven-field
  key, or the Match panel's Link. Unlink exists on both sides.
- Answers always go onto questions **by question number**.

## The gaps

1. **A wrong automatic match is only half visible.** The question side shows a one-line banner. Its
   Unlink sets both rows `unlinked`, which stops *all* automatic linking for them until their
   metadata changes, not just that one wrong pair. A wrong `proposed` match to a confirmed paper
   cannot be dismissed; it stays on the panel.
2. **Numbering is assumed to agree.** An answer booklet whose Section B restarts at 1, or whose
   answers are numbered `3a`/`3b`, attaches to the wrong questions or not at all. The admin only sees
   the result afterwards ("not attached: …").
3. **Matches can only be started from the answer side.** A question paper with no answers cannot go
   looking for them, and two jobs sitting side by side in the review queue cannot just be paired.
4. **Candidates are hidden by exact filters.** A paper whose number reads `2A` on one cover and `2`
   on the other never shows up unless the admin clears that filter.
5. **No undo after confirm.** Answers attached to the wrong bank paper can only be fixed page by page
   in Manage Papers.

## Proposal

### A. One "Pairing" panel, the same from both sides

On the review page of either paper (question or answer-only), a Pairing panel shows:

- the partner (filename, key, metadata in words) and **how** it was paired: automatic (with the key
  that matched) or by an admin;
- **Change…** (search for another partner) and **Not this one**.

**Not this one** unlinks and records the rejected pair, so automatic matching never proposes *that
pair* again but stays free to find another. This replaces today's blanket `unlinked` block. The same
button dismisses a `proposed` match to a confirmed paper.

*Backend:* an `ingest_match_rejection (ingest_paper_id, rejected_ingest_paper_id | rejected_paper_id)`
table, consulted by `ingest_matching`; Unlink becomes "reject".

### B. A question ↔ answer table before anything is attached

Linking or attaching opens a two-column table: each question of the question paper (thumbnail of its
first box) beside the answer boxes that will go onto it. It is pre-filled by number, and the admin
can:

- change which answer goes to a question (a menu per row), or leave a question without answers;
- **shift all answers by ±N** (the Section B case);
- see the answers that will not be attached, listed below the table.

The admin confirms the table, and that mapping is what gets attached, never a guess made later.

*Backend:* `attach` and the link route take an optional `mapping: {answer_number: question_number}`,
stored on the answer paper's `ingest_paper` row (`answer_map`) and used by the linked confirm. With
no mapping, attaching stays by number as today.

### C. Pair from either side, or from the queue

- **Question side:** a question paper with no answers gets **Find answers…**, which lists pending
  answer-only papers from any job plus a typed paper id. It is the Match panel from the other
  direction.
- **Review queue:** a checkbox on each paper line; with one question paper and one answer paper
  ticked, **Pair selected** opens table B. This is the quick path when a batch of uploads plainly
  belong together ("EOY P1.pdf" + "EOY P1 answers.pdf").

### D. Rank candidates instead of filtering them out

Search candidates are sorted by how many of the seven fields agree, with the differing fields
highlighted ("paper no. 2A ≠ 2"). Filters stay available to narrow the list, but they start empty
apart from subject, so a near-miss is not hidden.

### E. Detach after confirm

In Manage Papers, answer pages that came from an import job (known from provenance) are grouped as
"Answers from <file>", with **Detach**, which removes those pages. Because a settled job's files are
deleted, re-attaching means uploading the answer PDF again. Keeping settled answer jobs around
instead would cost storage, so the proposal is to accept the re-upload.

## To confirm

1. A: per-pair rejection instead of the blanket `unlinked` state?
2. B: an explicit mapping table (a small backend change) before attach/link?
3. C: **Find answers…** on question papers, and **Pair selected** in the review queue?
4. D: ranked candidates instead of pre-filled filters?
5. E: Detach in Manage Papers, with re-upload as the way back?

Suggested order once agreed: A + B together (they share the panel), then C, D, E.
