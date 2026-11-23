"""Evidence scoring of pending question/answer pairs (``app.services.match_evidence``)."""

from datetime import datetime, timedelta

import pytest

from app.services.match_evidence import DEFAULT, Evidence, Side, filename_stem, normalise_paper_number, pick, score

T0 = datetime(2026, 10, 29, 10, 0)
FIELDS = {"school_id": 1, "year": 2020, "level_id": 4, "subject_id": 2, "exam_type_id": 3, "stream_id": 5, "paper_number": "1"}


def side(filename="", numbers=(), when=T0, by=1, new_school=None, cover_school=None, **fields):
    return Side(
        fields={f: None for f in FIELDS} | fields, new_school=new_school, cover_school=cover_school,
        filename=filename, numbers=frozenset(numbers), created_by=by, created_at=when,
    )


@pytest.mark.parametrize("spelling", ["1", " P1", "p 1", "Paper 1", "paper1", "I", "01", "P.1"])
def test_paper_number_spellings_mean_the_same(spelling):
    assert normalise_paper_number(spelling) == "1"


def test_paper_number_letters_are_kept():
    assert normalise_paper_number("2A") == normalise_paper_number("P02a") == "2a"
    assert normalise_paper_number("2A") != normalise_paper_number("2")


# The four booklets of the review-queue screenshot that started this.
P1_QNS = "BPGHS 2020 Prelim 4E 5NA EM P1 Qns Paper.pdf"
P1_SOLN = "BPGHS 2020 Prelim 4E 5NA EM P1 Soln.pdf"
P2_QNS = "BPGHS 2020 Prelim EM P2 questions.pdf"
P2_SOLN = "BPGHS 2020 Prelim EM P2 solutions.pdf"


def test_role_words_are_dropped_from_filenames():
    assert filename_stem(P1_QNS) == filename_stem(P1_SOLN) == (("bpghs", "2020", "prelim", "4e", "5na", "em", "p1"), "1")
    assert filename_stem(P2_QNS) == filename_stem(P2_SOLN)
    assert filename_stem("RI 2024 Paper II marking scheme.pdf") == (("ri", "2024", "p2"), "2")


def test_the_screenshot_pairs_link_and_never_cross():
    # what the covers gave: no school on either; level and subject unread on the P2 questions
    p1q = side(P1_QNS, range(1, 26), year=2020, level_id=4, subject_id=2, exam_type_id=3, paper_number="1")
    p1a = side(P1_SOLN, range(1, 26), year=2020, level_id=4, subject_id=2, exam_type_id=3, paper_number="1")
    p2q = side(P2_QNS, range(1, 12), year=2020, exam_type_id=3, paper_number="2")
    p2a = side(P2_SOLN, range(1, 12), year=2020, level_id=4, subject_id=2, exam_type_id=3, paper_number="2")
    assert pick([(p1q, score(p1a, p1q)), (p2q, score(p1a, p2q))])[:2] == ("link", p1q)
    assert pick([(p1q, score(p2a, p1q)), (p2q, score(p2a, p2q))])[:2] == ("link", p2q)
    assert score(p2a, p1q).veto and score(p1a, p2q).veto


def test_a_field_known_on_both_sides_that_differs_is_a_veto():
    assert score(side(year=2020), side(year=2021)).veto == "year differs"
    assert score(side(paper_number="P1"), side(paper_number="1")).veto is None


def test_filenames_naming_different_papers_are_a_veto_even_without_the_field():
    assert score(side("X 2020 P1 ans.pdf"), side("X 2020 P2.pdf")).veto


def test_school_typed_as_new_is_known_cover_text_is_a_hint():
    assert score(side(new_school="Raffles Instn"), side(new_school=" raffles INSTN")).reasons[0].startswith("same school")
    assert score(side(new_school="A School"), side(new_school="B School")).veto == "school differs"
    assert score(side(new_school="A School"), side(school_id=1)).veto == "school differs"
    agree = score(side(cover_school="BPGHS"), side(cover_school="bpghs"))
    assert agree.veto is None and agree.score == 1 + 1  # school, uploaded together
    assert score(side(cover_school="BPGHS"), side(cover_school="Nan Hua")).veto is None  # a misread is no proof
    assert score(side(cover_school="BPGHS"), side(school_id=1)).veto is None


def test_answer_numbers_that_hit_no_question_are_a_veto():
    assert score(side(numbers=[30, 31]), side(numbers=[1, 2])).veto
    fits = score(side(numbers=[1, 2, 3, 4, 13]), side(numbers=[1, 2, 3, 4]), DEFAULT)
    assert "the answer numbers fit its questions" in fits.reasons


def test_uploaded_together_needs_the_same_admin_within_the_window():
    assert "uploaded together" in score(side(), side(when=T0 + timedelta(minutes=50))).reasons
    assert "uploaded together" not in score(side(), side(when=T0 + timedelta(hours=2))).reasons
    assert "uploaded together" not in score(side(by=1), side(by=2)).reasons


def test_a_full_key_alone_still_links():
    ev = score(side(**FIELDS, when=None), side(**FIELDS, when=None))
    assert ev.score == 7 and pick([("q", ev)])[0] == "link"


def test_pick():
    strong, weak, faint = Evidence(None, 8), Evidence(None, 5), Evidence(None, 3)
    assert pick([("a", strong), ("b", faint)])[:2] == ("link", "a")
    assert pick([("a", weak)])[:2] == ("suggest", "a")
    assert pick([("a", faint)])[0] == "none"
    kind, _, _, close = pick([("a", strong), ("b", Evidence(None, 7)), ("c", weak)])
    assert (kind, close) == ("several", ["a", "b"])
    assert pick([("a", Evidence("year differs", 9))])[0] == "none"
