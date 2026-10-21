"""Answers are all or none (#89): answer coverage of pending and bank papers, and where it is used
(the job list summary, automatic matching, attach, the review's linked-pair numbers)."""

from datetime import UTC, datetime

import pytest

from app.models.orm import Paper, Question, QuestionPage
from app.services.ingest_matching import match_row
from tests.test_ingest_confirm import attach_env, env, q, r  # noqa: F401
from tests.test_ingest_match import ANSWERS, job_with, row
from tests.test_ingest_review import rect


def question(number, answered):
    return {"number": number, "question_rects": [rect(3)], "answer_rects": [rect(3)] if answered else [], "flags": []}


def question_paper(*answered):
    """A question paper whose question n+1 has an answer box iff ``answered[n]``."""
    return {
        "label": "q1", "answer_label": None, "answer_template": "table",
        "pages": [], "questions": [question(n + 1, a) for n, a in enumerate(answered)],
        "orphan_answers": [], "warnings": [],
    }


def summary(admin_client, filename):
    jobs = {j["filename"]: j for j in admin_client.get("/api/import/jobs").json()["data"]}
    [p] = jobs[filename]["papers"]
    return p


@pytest.mark.parametrize("answered, coverage, unanswered", [
    ((False, False), "none", [1, 2]),
    ((True, False, False, True), "partial", [2, 3]),
    ((True, True), "all", []),
    ((), "none", []),
])
def test_job_list_gives_each_pending_papers_answer_coverage(
    admin_client, db_session, admin_user, answered, coverage, unanswered
):
    job_with(db_session, admin_user, question_paper(*answered), filename="q.pdf")
    p = summary(admin_client, "q.pdf")
    assert (p["answer_coverage"], p["unanswered"]) == (coverage, unanswered)


def test_job_list_coverage_follows_the_admins_edits(admin_client, db_session, admin_user):
    job, _ = job_with(db_session, admin_user, question_paper(False, False), filename="q.pdf")
    job.proposal_edited = {**job.proposal, "papers": [question_paper(True, False)]}
    db_session.commit()
    assert summary(admin_client, "q.pdf")["answer_coverage"] == "partial"


def test_an_answer_only_paper_covers_its_own_answers(admin_client, db_session, admin_user):
    job_with(db_session, admin_user, ANSWERS, filename="a.pdf")
    assert summary(admin_client, "a.pdf")["answer_coverage"] == "all"


# --- bank papers ----------------------------------------------------------------------------

@pytest.fixture
def meta(reference_data):
    rd = reference_data
    return {
        "school_id": rd["school"].id, "year": 2024, "level_id": rd["level"].id, "subject_id": rd["subject"].id,
        "exam_type_id": rd["exam_type"].id, "stream_id": rd["stream"].id, "paper_number": "1",
    }


def bank_paper(db, admin, meta, *answered, **over):
    """A confirmed paper whose question n+1 has an answer page iff ``answered[n]``."""
    p = Paper(**{**meta, **over}, created_by=admin.id, created_at=datetime.now(UTC))
    db.add(p)
    db.flush()
    for n, a in enumerate(answered):
        qn = Question(paper_id=p.id, question_number=n + 1)
        db.add(qn)
        db.flush()
        types = ("question", "answer") if a else ("question",)
        for t in types:
            db.add(QuestionPage(
                question_id=qn.id, page_type=t, page_order=1, image_key=f"k/{p.id}/{n}/{t}", width_px=10, height_px=10,
            ))
    db.flush()
    return p


def answers_row(db, admin, meta):
    job, key = job_with(db, admin, ANSWERS, meta)
    return job, row(db, job, key)


def test_matching_never_proposes_a_fully_answered_bank_paper(db_session, admin_user, meta):
    bank_paper(db_session, admin_user, meta, True, True)
    _, r = answers_row(db_session, admin_user, meta)
    match_row(db_session, r)
    assert (r.match_status, r.proposed_paper_id) == (None, None)


def test_matching_still_proposes_a_partly_answered_bank_paper(db_session, admin_user, meta):
    bank_paper(db_session, admin_user, meta, True, True)
    partly = bank_paper(db_session, admin_user, meta, True, False)
    _, r = answers_row(db_session, admin_user, meta)
    match_row(db_session, r)
    assert (r.match_status, r.proposed_paper_id) == ("proposed", partly.id)


def test_partial_hints_skip_fully_answered_bank_papers(db_session, admin_user, meta):
    bank_paper(db_session, admin_user, meta, True, paper_number="2")
    _, r = answers_row(db_session, admin_user, meta)
    match_row(db_session, r)
    assert r.match_status is None


def test_attach_to_a_fully_answered_bank_paper_is_refused(attach_env, db_session):
    attach, paper_id = attach_env  # question 1 answered, question 2 not
    job, resp = attach(q(2, [], [r(3)]))
    assert resp.status_code == 200, resp.text  # partly answered: allowed, and now every question has answers
    job, resp = attach(q(1, [], [r(3)]), mode="append", label="a2")
    assert resp.status_code == 409 and "already has answers" in resp.json()["detail"]
    db_session.refresh(job)
    assert not (job.report or {}).get("review_outcome")


def test_review_of_a_linked_question_paper_lists_the_partners_answer_numbers(
    admin_client, db_session, admin_user, fake_object_store
):
    qjob, qkey = job_with(db_session, admin_user, question_paper(False, False, False), filename="q.pdf")
    two = {**ANSWERS, "questions": [question(1, True), question(3, True), {**question(4, False), "question_rects": []}]}
    ajob, akey = job_with(db_session, admin_user, two, filename="a.pdf")
    resp = admin_client.post(
        f"/api/import/jobs/{ajob.id}/papers/{akey}/match", json={"ingest_paper_id": row(db_session, qjob, qkey).id}
    )
    assert resp.status_code == 200, resp.text
    link = admin_client.get(f"/api/import/jobs/{qjob.id}/review").json()["matches"][qkey]
    assert link["answer_numbers"] == [1, 3]  # what confirm will bring in, by number


def test_job_list_names_the_school_read_from_the_cover(admin_client, db_session, admin_user):
    # The queue's Match button pre-fills the popup from the summary, so it needs the raw name (#93).
    meta = {"school_id": None, "extracted": {"school": "Raffles Instn", "subject": None}}
    job_with(db_session, admin_user, question_paper(False), meta, filename="q.pdf")
    job_with(db_session, admin_user, question_paper(False), filename="r.pdf")
    assert summary(admin_client, "q.pdf")["extracted_school"] == "Raffles Instn"
    assert summary(admin_client, "r.pdf")["extracted_school"] is None
