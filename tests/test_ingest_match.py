"""Manual matching of an answer-only paper and a question paper (#82, #91): link from either side,
unlink, the review's ``matches`` and the job list's ``unmatched_answers`` filter. The search for a
partner is in test_match_candidates.py."""

import pytest

from app.models.orm import IngestPaper
from app.services.ingest_papers import sync_job_papers
from tests.test_ingest_review import make_job, page, rect

QUESTION = {
    "label": "q1", "answer_label": None, "answer_template": "table",
    "pages": [page(2), page(3)],
    "questions": [{"number": 1, "question_rects": [rect(3)], "answer_rects": [], "flags": []}],
    "orphan_answers": [], "warnings": [],
}
ANSWERS = {
    "label": None, "answer_label": "a1", "role": "answer_only", "answer_template": "table",
    "pages": [page(2)],
    "questions": [{"number": 1, "question_rects": [], "answer_rects": [rect(2)], "flags": []}],
    "orphan_answers": [], "warnings": [],
}


def proposal(*papers):
    return {"papers": list(papers), "unrouted": [], "warnings": []}


def job_with(db, admin, paper, meta=None, filename="x.pdf", status="review_ready"):
    job = make_job(db, admin, proposal=proposal(paper), filename=filename, status=status)
    key = paper["label"] or paper["answer_label"]
    job.report = {"paper_metadata": {key: meta or {}}}
    sync_job_papers(db, job)
    db.commit()
    return job, key


def row(db, job, key):
    db.expire_all()
    return db.query(IngestPaper).filter_by(job_id=job.id, paper_key=key).one()


def test_link_sets_both_sides_review_shows_it_and_unlink_clears(
    admin_client, db_session, admin_user, fake_object_store
):
    qjob, qkey = job_with(db_session, admin_user, QUESTION, filename="q.pdf")
    ajob, akey = job_with(db_session, admin_user, ANSWERS, filename="a.pdf")
    qrow = row(db_session, qjob, qkey)
    url = f"/api/import/jobs/{ajob.id}/papers/{akey}/match"
    resp = admin_client.post(url, json={"ingest_paper_id": qrow.id})
    assert resp.status_code == 200
    assert resp.json()["matches"]["filename"] == "q.pdf"
    assert resp.json()["matches"]["matched_by"] == "admin"
    arow = row(db_session, ajob, akey)
    assert arow.matched_ingest_paper_id == row(db_session, qjob, qkey).id
    assert row(db_session, qjob, qkey).matched_ingest_paper_id == arow.id
    assert admin_client.get(f"/api/import/jobs/{ajob.id}/review").json()["matches"][akey]["paper_key"] == "q1"
    assert admin_client.get(f"/api/import/jobs/{qjob.id}/review").json()["matches"][qkey]["filename"] == "a.pdf"
    assert admin_client.delete(url).json() == {"matches": None, "proposal": None}
    assert row(db_session, ajob, akey).matched_ingest_paper_id is None
    assert row(db_session, qjob, qkey).matched_ingest_paper_id is None
    assert admin_client.get(f"/api/import/jobs/{ajob.id}/review").json()["matches"] == {}


def test_relinking_releases_the_previous_partner(admin_client, db_session, admin_user, fake_object_store):
    q1, k = job_with(db_session, admin_user, QUESTION, filename="q1.pdf")
    q2, _ = job_with(db_session, admin_user, QUESTION, filename="q2.pdf")
    ajob, akey = job_with(db_session, admin_user, ANSWERS)
    url = f"/api/import/jobs/{ajob.id}/papers/{akey}/match"
    admin_client.post(url, json={"ingest_paper_id": row(db_session, q1, k).id})
    admin_client.post(url, json={"ingest_paper_id": row(db_session, q2, k).id})
    assert row(db_session, q1, k).matched_ingest_paper_id is None
    assert row(db_session, ajob, akey).matched_ingest_paper_id == row(db_session, q2, k).id


def test_link_refuses_bad_targets(admin_client, db_session, admin_user, fake_object_store):
    qjob, qkey = job_with(db_session, admin_user, QUESTION)
    ajob, akey = job_with(db_session, admin_user, ANSWERS)
    other_answers, ok = job_with(db_session, admin_user, ANSWERS)
    other_question, oq = job_with(db_session, admin_user, QUESTION)
    done, dk = job_with(db_session, admin_user, QUESTION, status="confirmed")
    url = f"/api/import/jobs/{ajob.id}/papers/{akey}/match"
    link = lambda u, target: admin_client.post(u, json={"ingest_paper_id": target}).status_code  # noqa: E731
    assert link(url, 999999) == 404
    assert link(url, row(db_session, other_answers, ok).id) == 422  # two answer papers
    assert link(url, row(db_session, ajob, akey).id) == 422  # itself
    assert link(url, row(db_session, done, dk).id) == 422  # a job no longer under review
    assert link(f"/api/import/jobs/{qjob.id}/papers/{qkey}/match", row(db_session, other_question, oq).id) == 422
    assert link(f"/api/import/jobs/{ajob.id}/papers/nope/match", row(db_session, qjob, qkey).id) == 404


def test_link_from_the_question_side(admin_client, db_session, admin_user, fake_object_store):
    qjob, qkey = job_with(db_session, admin_user, QUESTION, filename="q.pdf")
    ajob, akey = job_with(db_session, admin_user, ANSWERS, filename="a.pdf")
    resp = admin_client.post(
        f"/api/import/jobs/{qjob.id}/papers/{qkey}/match", json={"ingest_paper_id": row(db_session, ajob, akey).id}
    )
    assert resp.status_code == 200
    assert resp.json()["matches"]["filename"] == "a.pdf"
    assert row(db_session, ajob, akey).matched_ingest_paper_id == row(db_session, qjob, qkey).id


def test_link_within_one_booklet(admin_client, db_session, admin_user, fake_object_store):
    job = make_job(db_session, admin_user, proposal=proposal(QUESTION, ANSWERS), filename="both.pdf")
    sync_job_papers(db_session, job)
    db_session.commit()
    resp = admin_client.post(
        f"/api/import/jobs/{job.id}/papers/a1/match", json={"ingest_paper_id": row(db_session, job, "q1").id}
    )
    assert resp.status_code == 200
    assert (resp.json()["matches"]["job_id"], resp.json()["matches"]["paper_key"]) == (str(job.id), "q1")
    assert row(db_session, job, "q1").matched_ingest_paper_id == row(db_session, job, "a1").id


def test_link_saves_the_papers_details_in_the_same_request(admin_client, db_session, admin_user, fake_object_store):
    qjob, qkey = job_with(db_session, admin_user, QUESTION, {"year": 2023, "paper_number": "2A"})
    ajob, akey = job_with(db_session, admin_user, ANSWERS, {"year": 2023})
    resp = admin_client.post(f"/api/import/jobs/{ajob.id}/papers/{akey}/match", json={
        "ingest_paper_id": row(db_session, qjob, qkey).id,
        "metadata": {"year": 2024, "paper_number": "2A", "new_school_name": "Raffles Instn"},
    })
    assert resp.status_code == 200
    a = row(db_session, ajob, akey)
    assert (a.year, a.paper_number, a.new_school_name, a.metadata_source) == (2024, "2A", "Raffles Instn", "admin")
    assert a.matched_ingest_paper_id == row(db_session, qjob, qkey).id


def test_a_refused_link_saves_no_details(admin_client, db_session, admin_user, fake_object_store):
    ajob, akey = job_with(db_session, admin_user, ANSWERS, {"year": 2023})
    resp = admin_client.post(
        f"/api/import/jobs/{ajob.id}/papers/{akey}/match", json={"ingest_paper_id": 999999, "metadata": {"year": 2024}}
    )
    assert resp.status_code == 404
    assert row(db_session, ajob, akey).year == 2023


def test_unmatched_answers_filter(admin_client, db_session, admin_user, fake_object_store):
    qjob, qkey = job_with(db_session, admin_user, QUESTION)
    loose, lk = job_with(db_session, admin_user, ANSWERS)
    linked, ak = job_with(db_session, admin_user, ANSWERS)
    done, dk = job_with(db_session, admin_user, ANSWERS)
    done_row = row(db_session, done, dk)
    done_row.status = "skipped"
    db_session.commit()
    admin_client.post(
        f"/api/import/jobs/{linked.id}/papers/{ak}/match", json={"ingest_paper_id": row(db_session, qjob, qkey).id}
    )
    ids = lambda path: {j["id"] for j in admin_client.get(path).json()["data"]}  # noqa: E731
    assert ids("/api/import/jobs?unmatched_answers=true") == {str(loose.id)}
    assert ids("/api/import/jobs?unmatched_answers=true&job_id=" + str(linked.id)) == set()
    assert ids("/api/import/jobs?unmatched_answers=true&status=failed") == set()
    assert str(qjob.id) in ids("/api/import/jobs")


def test_job_list_summarises_each_jobs_papers(admin_client, db_session, admin_user, fake_object_store):
    qjob, qkey = job_with(db_session, admin_user, QUESTION, {"year": 2024, "paper_number": "1"}, filename="q.pdf")
    ajob, akey = job_with(db_session, admin_user, ANSWERS, filename="a.pdf")
    admin_client.post(
        f"/api/import/jobs/{ajob.id}/papers/{akey}/match", json={"ingest_paper_id": row(db_session, qjob, qkey).id}
    )
    jobs = {j["filename"]: j for j in admin_client.get("/api/import/jobs").json()["data"]}
    [q] = jobs["q.pdf"]["papers"]
    assert (q["key"], q["role"], q["status"], q["year"], q["paper_number"], q["linked"]) == (
        "q1", "question", "pending", 2024, "1", True,
    )
    [a] = jobs["a.pdf"]["papers"]
    assert (a["key"], a["role"], a["linked"]) == ("a1", "answer_only", True)
