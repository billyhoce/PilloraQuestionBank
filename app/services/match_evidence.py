"""How strongly two pending booklets look like one paper's questions and its answers.

Pure: no database. ``ingest_matching`` builds a ``Side`` for each paper and asks ``score`` whether
the pair is ruled out (a *veto*) and, if not, how much evidence it has. Pending pairs are scored
rather than keyed on all seven fields, because a cover often leaves a field blank (an answer key has
no cover; a school is printed as "BPGHS") and one blank field used to stop every match. Bank papers
keep the exact seven-field key (``ingest_matching.exact_candidates``): attaching writes to the bank.
See docs/features/qa-pairing.md ("Automatic matching") and docs/adr/0004-scored-pending-matching.md.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

FIELDS = ("school_id", "year", "level_id", "subject_id", "exam_type_id", "stream_id", "paper_number")
LABELS = {
    "school_id": "school", "year": "year", "level_id": "level", "subject_id": "subject",
    "exam_type_id": "exam type", "stream_id": "stream", "paper_number": "paper number",
}


@dataclass(frozen=True)
class MatchConfig:
    # A full seven-field key alone (7 points) must still auto-link, as it did before scoring. Without
    # it: a filename that matches once Qns/Soln are dropped (3), answer numbers that fit the
    # questions (1) and an upload by the same admin (1) still need one agreeing field (1) on top.
    auto_score: int = 6
    # The best partner must lead the runner-up by this much to be linked or suggested; a closer race
    # is a coin toss and is left to the admin ("several could fit").
    auto_margin: int = 2
    # Below this the evidence is a couple of coincidences (same year and exam type, uploaded
    # together), true of any two booklets in a bulk upload: nothing is shown.
    suggest_score: int = 4
    # Filenames whose word sets overlap this much (Jaccard, after dropping role words) are
    # "similar": one stray word ("final", "v2") out of the usual five to eight still passes.
    filename_jaccard: float = 0.75
    # Booklets one admin uploads within this window were most likely dropped together.
    upload_window: timedelta = timedelta(minutes=60)
    # Share of the answer numbers that must be question numbers for the numbers to count as fitting.
    # Not 1.0: a stray answer label ("13" in a 12-question paper) is common and harmless.
    number_fit: float = 0.8


DEFAULT = MatchConfig()


@dataclass(frozen=True)
class Side:
    """What one paper of a candidate pair offers as evidence."""

    fields: Mapping[str, Any]  # the seven key fields; None = unknown
    new_school: str | None = None  # a school the admin typed as new: known, like a school id
    cover_school: str | None = None  # the school the cover printed when it matched none: a hint
    filename: str = ""
    numbers: frozenset = frozenset()  # question numbers (question paper) / answered numbers (answers)
    created_by: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class Evidence:
    veto: str | None  # why the pair is ruled out, or None
    score: int = 0
    reasons: tuple[str, ...] = field(default_factory=tuple)


# Words that name a booklet's role, not its paper: dropped before filenames are compared.
_ROLE_WORDS = frozenset({
    "q", "qn", "qns", "qs", "qp", "question", "questions", "ques",
    "a", "ans", "answer", "answers", "anskey", "key", "keys",
    "soln", "solns", "sol", "sols", "solution", "solutions", "worked",
    "marking", "scheme", "ms", "with", "and", "w", "paper", "booklet", "copy",
})
_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}


def normalise_paper_number(value: Any) -> str:
    """A paper number as compared: ``P1`` = ``Paper 1`` = ``1`` = ``I`` = ``01``; a letter is kept
    (``2A`` = ``02a``, ≠ ``2``)."""
    s = re.sub(r"\s+", " ", str(value).strip().lower())
    s = re.sub(r"^(paper|p)\s*\.?\s*", "", s)
    if s in _ROMAN:
        return _ROMAN[s]
    m = re.fullmatch(r"0*(\d+)\s*([a-z]?)", s)
    if m:
        return m.group(1) + m.group(2)
    return s


def _tokens(name: str) -> list[str]:
    stem = re.sub(r"\.pdf$", "", name.strip().lower())
    return [t for t in re.split(r"[^a-z0-9]+", stem) if t]


def filename_stem(name: str) -> tuple[tuple[str, ...], str | None]:
    """``(tokens, paper)``: the filename's words without role words (Qns, Soln, Answers, …), and
    the paper number it names (``P1``, ``Paper 2``, ``Paper II``), normalised, or None."""
    raw = _tokens(name)
    out, paper = [], None
    i = 0
    while i < len(raw):
        t = raw[i]
        nxt = raw[i + 1] if i + 1 < len(raw) else None
        if t == "paper" and nxt is not None and (nxt.isdigit() or nxt in _ROMAN):
            paper = normalise_paper_number(nxt)
            out.append("p" + paper)
            i += 2
            continue
        if re.fullmatch(r"p\d+[a-z]?", t):
            paper = normalise_paper_number(t)
            out.append("p" + paper)
        elif t not in _ROLE_WORDS:
            out.append(t)
        i += 1
    return tuple(out), paper


def _norm_text(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _same_field(f: str, a: Any, b: Any) -> bool:
    if f == "paper_number":
        return normalise_paper_number(a) == normalise_paper_number(b)
    return a == b


def _school(a: Side, q: Side) -> str | bool | None:
    """``False`` when both sides know their school (an id, or a name typed as new) and they differ;
    the agreeing label when they are the same, or when neither knows it but both covers printed the
    same unresolved name; None when nothing can be said."""
    a_id, q_id = a.fields.get("school_id"), q.fields.get("school_id")
    a_new, q_new = _norm_text(a.new_school), _norm_text(q.new_school)
    if (a_id is not None or a_new) and (q_id is not None or q_new):
        if a_id is not None or q_id is not None:
            return "school" if a_id == q_id else False
        return "school" if a_new == q_new else False
    a_txt, q_txt = a_new or _norm_text(a.cover_school), q_new or _norm_text(q.cover_school)
    if a_id is None and q_id is None and a_txt and a_txt == q_txt:
        return f"school (“{(a.new_school or a.cover_school).strip()}”)"
    return None


def score(answers: Side, questions: Side, cfg: MatchConfig = DEFAULT) -> Evidence:
    """The evidence that ``answers`` (an answer-only paper) holds the answers to ``questions``."""
    points, reasons, agree = 0, [], []
    school = _school(answers, questions)
    if school is False:
        return Evidence(veto="school differs")
    if school:
        agree.append(school)
    for f in FIELDS[1:]:
        a, q = answers.fields.get(f), questions.fields.get(f)
        if a is None or q is None:
            continue
        if not _same_field(f, a, q):
            return Evidence(veto=f"{LABELS[f]} differs")
        agree.append(LABELS[f])
    if agree:
        points += len(agree)
        reasons.append("same " + ", ".join(agree))

    (a_tok, a_paper), (q_tok, q_paper) = filename_stem(answers.filename), filename_stem(questions.filename)
    if a_paper is not None and q_paper is not None and a_paper != q_paper:
        return Evidence(veto="the filenames name different papers")
    if len(a_tok) >= 2 and a_tok == q_tok:
        points += 3
        reasons.append("same filename apart from words like Qns / Soln")
    elif a_tok and q_tok:
        a_set, q_set = set(a_tok), set(q_tok)
        if len(a_set & q_set) / len(a_set | q_set) >= cfg.filename_jaccard:
            points += 2
            reasons.append("similar filenames")

    if answers.numbers and questions.numbers:
        fit = len(answers.numbers & questions.numbers) / len(answers.numbers)
        if fit == 0:
            return Evidence(veto="no answer number is one of its questions")
        if fit >= cfg.number_fit:
            points += 1
            reasons.append("the answer numbers fit its questions")

    if (
        answers.created_by is not None and answers.created_by == questions.created_by
        and answers.created_at is not None and questions.created_at is not None
        and abs(answers.created_at - questions.created_at) <= cfg.upload_window
    ):
        points += 1
        reasons.append("uploaded together")
    return Evidence(veto=None, score=points, reasons=tuple(reasons))


def pick(scored: list[tuple[Any, Evidence]], cfg: MatchConfig = DEFAULT) -> tuple[str, Any, Evidence | None, list]:
    """The outcome for one paper given its scored candidates: ``(kind, best, evidence, close)``
    where ``kind`` is ``link`` (a clear, strong winner), ``suggest`` (a clear winner on weaker
    evidence), ``several`` (the candidates in ``close`` are too close to call) or ``none``."""
    live = sorted(((c, e) for c, e in scored if e.veto is None and e.score >= cfg.suggest_score), key=lambda ce: -ce[1].score)
    if not live:
        return "none", None, None, []
    best, ev = live[0]
    if len(live) > 1 and ev.score - live[1][1].score < cfg.auto_margin:
        return "several", None, None, [c for c, e in live if ev.score - e.score < cfg.auto_margin]
    return ("link" if ev.score >= cfg.auto_score else "suggest"), best, ev, [best]
