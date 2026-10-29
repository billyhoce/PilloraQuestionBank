"""The "Match this paper" search (#91): ranking candidates by how many of the filled fields agree
exactly, and ``GET .../papers/{key}/candidates``."""

import uuid

from app.models.orm import Question, QuestionPage
from app.services.ingest_papers import sync_job_papers
from app.services.match_candidates import rank
from tests.test_ingest_match import ANSWERED_QUESTION, ANSWERS, QUESTION, job_with, proposal, row
from tests.test_ingest_matching import add_paper, meta  # noqa: F401
from tests.test_ingest_review import make_job, rect


def item(name, **fields):
    return {"name": name, "details": fields}


def names(items):
    return [i["name"] for i in items]


def test_blank_fields_mean_any_and_exact_matches_come_first():
    items = [item("a", year=2024, paper_number="1"), item("b", year=2023, paper_number="1")]
    got = rank({"year": 2024, "paper_number": None}, items)
    assert names(got["exact"]) == ["a"] and got["best"] == []
    assert (got["exact"][0]["agree"], got["exact"][0]["differ"]) == (["year"], [])


def test_without_an_exact_match_the_best_are_ranked_by_agreeing_fields():
    items = [
        item("one", year=2024, subject_id=9, paper_number="9"),
        item("two", year=2024, subject_id=1, paper_number="9"),
        item("none", year=2020, subject_id=9, paper_number="9"),
    ]
    got = rank({"year": 2024, "subject_id": 1, "paper_number": "2"}, items)
    assert got["exact"] == []
    assert names(got["best"]) == ["two", "one"]  # nothing agreeing is no evidence: left out
    assert (got["best"][0]["agree"], got["best"][0]["differ"]) == (["year", "subject_id"], ["paper_number"])


def test_best_matches_stop_at_ten():
    items = [item(str(n), year=2024, paper_number="9") for n in range(12)]
    assert len(rank({"year": 2024, "paper_number": "1"}, items)["best"]) == 10


def test_paper_number_is_normalised():
    items = [item("x", paper_number="2A"), item("y", paper_number="P02a"), item("z", paper_number="2")]
    got = rank({"paper_number": " 2a "}, items)
    assert names(got["exact"]) == ["x", "y"]


def test_a_new_school_matches_the_same_new_name_and_never_an_id():
    items = [
        item("named", school_id=None, new_school_name=" raffles instn"),
        item("other", school_id=None, new_school_name="Elsewhere"),
        item("bank", school_id=3, new_school_name=None),
    ]
    got = rank({"school_id": None, "new_school_name": "Raffles Instn", "year": 2024}, [
        {**i, "details": {**i["details"], "year": 2024}} for i in items
    ])
    assert names(got["exact"]) == ["named"]
    assert rank({"school_id": 3}, items)["exact"][0]["name"] == "bank"


# --- GET /api/import/jobs/{id}/papers/{key}/candidates ---------------------------------------


def candidates(client, job, key, **query):
    resp = client.get(f"/api/import/jobs/{job.id}/papers/{key}/candidates", params=query)
    assert resp.status_code == 200, resp.text
    return resp.json()


def add_question(db, paper, number, answered=False):
    q = Question(paper_id=paper.id, question_number=number)
    db.add(q)
    db.flush()
    db.add(QuestionPage(question_id=q.id, page_order=1, page_type="question", image_key=f"img/{paper.id}/{number}.webp", width_px=10, height_px=10))
    if answered:
        db.add(QuestionPage(question_id=q.id, page_order=1, page_type="answer", image_key=f"img/{paper.id}/{number}a.webp", width_px=10, height_px=10))
    db.flush()
    return q


def test_an_answer_only_paper_finds_pending_question_papers_and_bank_papers(
    admin_client, db_session, admin_user, fake_object_store, meta
):
    ajob, akey = job_with(db_session, admin_user, ANSWERS, meta, filename="ans.pdf")
    qjob, _ = job_with(db_session, admin_user, QUESTION, meta, filename="q.pdf")
    job_with(db_session, admin_user, ANSWERS, meta, filename="other-answers.pdf")  # same role: never
    job_with(db_session, admin_user, QUESTION, meta, filename="done.pdf", status="confirmed")
    bank = add_paper(db_session, admin_user, meta)
    add_question(db_session, bank, 1)
    db_session.commit()

    got = candidates(admin_client, ajob, akey, year=2024, paper_number="1")
    assert got["best"] == []
    pending, banked = got["exact"]
    assert (pending["kind"], pending["filename"], pending["paper_key"], pending["job_id"]) == ("pending", "q.pdf", "q1", str(qjob.id))
    assert pending["ingest_paper_id"] == row(db_session, qjob, "q1").id and pending["same_job"] is False
    assert pending["details"]["year"] == 2024 and pending["agree"] == ["year", "paper_number"]
    assert (pending["question_numbers"], pending["answer_numbers"], pending["answer_coverage"]) == ([1], [], "none")
    assert pending["partner"] is None
    assert pending["preview"]["url"] == f"https://fake.url/tmp/ingest/{qjob.id}/pages/p03.webp"
    assert pending["preview"]["rect"] == rect(3)
    assert (banked["kind"], banked["paper_id"], banked["answer_coverage"]) == ("bank", bank.id, "none")
    assert (banked["question_numbers"], banked["answer_numbers"]) == ([1], [])
    assert banked["preview"] == {"number": 1, "url": f"https://fake.url/img/{bank.id}/1.webp"}


def booklet(db, admin, meta, filename="both.pdf"):
    """One job holding a question paper and an answer-only paper the pipeline did not pair."""
    job = make_job(db, admin, proposal=proposal(QUESTION, ANSWERS), filename=filename)
    job.report = {"paper_metadata": {"q1": meta, "a1": meta}}
    sync_job_papers(db, job)
    db.commit()
    return job


def test_a_question_paper_finds_pending_answer_papers_including_its_own_booklets_but_never_bank_papers(
    admin_client, db_session, admin_user, fake_object_store, meta
):
    job = booklet(db_session, admin_user, meta)
    ajob, _ = job_with(db_session, admin_user, ANSWERS, meta, filename="ans.pdf")
    add_paper(db_session, admin_user, meta)
    db_session.commit()
    got = candidates(admin_client, job, "q1", year=2024)["exact"]
    assert [(c["kind"], c["filename"], c["same_job"]) for c in got] == [  # its own booklet first
        ("pending", "both.pdf", True), ("pending", "ans.pdf", False),
    ]
    own = got[0]
    assert (own["role"], own["question_numbers"], own["answer_numbers"], own["answer_coverage"]) == ("answer_only", [], [1], "all")
    assert own["preview"]["rect"] == rect(2)  # an answer-only booklet shows its first answer


def test_a_candidate_names_its_current_partner_and_the_papers_own_partner_is_left_out(
    admin_client, db_session, admin_user, fake_object_store, meta
):
    ajob, akey = job_with(db_session, admin_user, ANSWERS, meta, filename="ans.pdf")
    q1, _ = job_with(db_session, admin_user, QUESTION, meta, filename="q1.pdf")
    q2, _ = job_with(db_session, admin_user, QUESTION, meta, filename="q2.pdf")
    other, okey = job_with(db_session, admin_user, ANSWERS, meta, filename="other.pdf")
    a, b, o = row(db_session, ajob, akey), row(db_session, q1, "q1"), row(db_session, other, okey)
    c = row(db_session, q2, "q1")
    a.matched_ingest_paper_id, b.matched_ingest_paper_id = b.id, a.id
    o.matched_ingest_paper_id, c.matched_ingest_paper_id = c.id, o.id
    db_session.commit()
    [got] = candidates(admin_client, ajob, akey)["exact"]
    assert got["filename"] == "q2.pdf"
    assert got["partner"] == {"ingest_paper_id": o.id, "job_id": str(other.id), "filename": "other.pdf", "paper_key": "a1"}


def test_bank_papers_already_answered_are_flagged_not_dropped(
    admin_client, db_session, admin_user, fake_object_store, meta
):
    ajob, akey = job_with(db_session, admin_user, ANSWERS, meta)
    full = add_paper(db_session, admin_user, meta)
    add_question(db_session, full, 1, answered=True)
    partly = add_paper(db_session, admin_user, meta)
    add_question(db_session, partly, 1, answered=True)
    add_question(db_session, partly, 2)
    db_session.commit()
    got = {c["paper_id"]: c for c in candidates(admin_client, ajob, akey, year=2024)["exact"]}
    assert got[full.id]["answer_coverage"] == "all"
    assert (got[partly.id]["answer_coverage"], got[partly.id]["question_numbers"], got[partly.id]["answer_numbers"]) == (
        "partial", [1, 2], [1],
    )


def test_pending_question_papers_with_answers_of_their_own_are_flagged_not_dropped(
    admin_client, db_session, admin_user, fake_object_store, meta
):
    # answers are all or none: a partly answered question paper cannot take these answers
    ajob, akey = job_with(db_session, admin_user, ANSWERS, meta)
    job_with(db_session, admin_user, ANSWERED_QUESTION, meta, filename="answered.pdf")
    [got] = candidates(admin_client, ajob, akey, year=2024)["exact"]
    assert (got["filename"], got["answer_coverage"], got["answer_numbers"]) == ("answered.pdf", "partial", [1])


def test_a_candidates_preview_and_mapping_table_follow_the_admins_edit(
    admin_client, db_session, admin_user, fake_object_store, meta
):
    ajob, akey = job_with(db_session, admin_user, ANSWERS, meta)
    qjob, _ = job_with(db_session, admin_user, QUESTION, meta)
    edited = {**QUESTION, "questions": [{"number": 5, "question_rects": [rect(2)], "answer_rects": [], "flags": []}]}
    qjob.proposal_edited = proposal(edited)  # the admin renumbered the question and moved its box
    db_session.commit()
    [got] = candidates(admin_client, ajob, akey, year=2024)["exact"]
    assert got["question_numbers"] == [5] and got["preview"]["rect"] == rect(2)
    resp = admin_client.get(f"/api/import/jobs/{ajob.id}/papers/{akey}/answer-map", params={"ingest_paper_id": got["ingest_paper_id"]})
    assert [(x["label"], x["preview"]["rect"]) for x in resp.json()["questions"]] == [("5", rect(2))]


def test_without_an_exact_match_the_best_matches_say_which_fields_differ(
    admin_client, db_session, admin_user, fake_object_store, meta
):
    ajob, akey = job_with(db_session, admin_user, ANSWERS, meta)
    add_paper(db_session, admin_user, meta, paper_number="2A")
    add_paper(db_session, admin_user, meta, year=2019, paper_number="2A")
    db_session.commit()
    got = candidates(admin_client, ajob, akey, **{**meta, "paper_number": "2"})
    assert got["exact"] == []
    first, second = got["best"]
    assert first["differ"] == ["paper_number"] and first["details"]["paper_number"] == "2A"
    assert second["differ"] == ["year", "paper_number"]


def test_a_new_school_finds_only_pending_papers_with_that_name(
    admin_client, db_session, admin_user, fake_object_store, meta
):
    new = {**meta, "school_id": None}
    ajob, akey = job_with(db_session, admin_user, ANSWERS, new)
    qjob, _ = job_with(db_session, admin_user, QUESTION, new, filename="q.pdf")
    q = row(db_session, qjob, "q1")
    q.new_school_name = "Raffles Instn"
    add_paper(db_session, admin_user, meta)
    db_session.commit()
    got = candidates(admin_client, ajob, akey, new_school_name="raffles instn ")
    assert [c["filename"] for c in got["exact"]] == ["q.pdf"]


def test_candidates_of_an_unknown_paper(admin_client, db_session, admin_user, fake_object_store):
    ajob, _ = job_with(db_session, admin_user, ANSWERS)
    assert admin_client.get(f"/api/import/jobs/{ajob.id}/papers/nope/candidates").status_code == 404


def test_candidates_non_admin_forbidden(public_client):
    assert public_client.get(f"/api/import/jobs/{uuid.uuid4()}/papers/a1/candidates").status_code == 403
