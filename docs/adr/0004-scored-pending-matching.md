# 0004. Score pending question/answer pairs; review a linked pair as one

Status: accepted. Amends the matching key in [0002](./0002-qa-booklet-pairing.md) for pairs of
pending booklets; matching against the bank is unchanged.

## Context

Dropping four PDFs (P1 questions, P1 solutions, P2 questions, P2 solutions) gave four review cards
and four review pages, and automatic matching paired almost nothing:

- **All seven fields or nothing.** A pending pair was linked only when both papers knew all seven
  key fields and they were equal. Covers routinely leave one blank: an answer key has no cover, the
  stream is rarely printed, a school is printed as "BPGHS". One blank field turned pending matching
  off, and the partial fallback only searched the bank.
- **An unresolved school was thrown away.** A cover school that matched no school kept no trace on
  the paper, so two booklets both printed "BPGHS" could not even be compared on it.
- **Level names collide.** Levels are named "1"–"6" (Primary) and "1"–"4" (Secondary); the metadata
  reader keyed them by bare name, so "Sec 4" resolved to nothing and "4" to whichever loaded last.
- **"P1" ≠ "1".** Paper numbers were compared trimmed and case-folded only.
- **A solutions booklet read as questions could never pair.** A solutions PDF is often the question
  paper reprinted with worked answers. The pipeline may label it a question paper, and pairing only
  joins opposite roles, with no way to change a role.
- **Review was per booklet.** Even a linked pair was reviewed on two pages, although confirming the
  question paper already brings the answers in and settles both.

## Decision

- **Score pending pairs instead of requiring the full key.** A field known on both sides that differs
  rules a pair out; a blank field does not. Agreeing fields, the filename with role words (Qns,
  Soln, Answers, …) dropped, the same unresolved cover school, answer numbers that fit the questions,
  and an upload by the same admin within an hour add evidence (`app/services/match_evidence.py`,
  thresholds with their reasons in `MatchConfig`). A clear, strong winner is auto-linked (as before,
  cheap to undo); a clear winner on weaker evidence is **suggested** for one-click Pair / Not a pair;
  a close race is left to the admin. A full seven-field key scores enough on its own, so every pair
  the old rule linked is still linked.
- **The bank keeps the exact key.** Attaching writes to the bank and is not undone by a later
  re-match, so bank proposals stay as strict as 0002 decided.
- **Keep what the cover said.** An unresolved cover school is stored on the paper and compared
  between pending papers; when such a paper is confirmed with a school, the name is learned as a
  **school alias** so later covers resolve it.
- **Read levels qualified by school level** ("Secondary 4"), and normalise paper numbers
  (`P1` = `Paper 1` = `1` = `I`).
- **The admin can switch a paper's role** ("This is an answer booklet"): its boxes change sides and
  it is matched afresh. Detecting it automatically was not chosen, to keep `ingestion/` unchanged
  and the decision with a person.
- **A linked pair is one review.** The queue shows one card per pair; the review page shows the
  question paper with each question's answers from the other booklet, a toggle to edit either
  booklet (each saves to its own job), and one Confirm.

## Consequences

- Filenames now matter for matching. A bulk upload of differently named booklets still matches on
  fields and numbers; a misleading filename can only add evidence, and a field that disagrees still
  rules a pair out.
- "Uploaded together" makes every booklet of a bulk upload slightly closer; the suggest threshold is
  set so that this plus two coincidental fields shows nothing.
- A Retry that regenerates the proposal brings back the pipeline's role, undoing a role switch.
- Grouping is by link, not by upload batch: answers that arrive later join their question paper's
  card once linked.
