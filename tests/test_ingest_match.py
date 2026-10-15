"""Manual matching of an answer-only paper to a question paper (#82): the pending-papers search,
link / unlink, the review's ``matches`` and the job list's ``unmatched_answers`` filter."""

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


def test_pending_lists_question_papers_of_other_jobs_filtered_by_metadata(
    admin_client, db_session, admin_user, fake_object_store
):
    a, _ = job_with(db_session, admin_user, QUESTION, {"year": 2024, "paper_number": "1"}, filename="a.pdf")
    job_with(db_session, admin_user, QUESTION, {"year": 2023, "paper_number": "1"}, filename="b.pdf")
    job_with(db_session, admin_user, ANSWERS, {"year": 2024, "paper_number": "1"}, filename="ans.pdf")
    job_with(db_session, admin_user, QUESTION, {"year": 2024}, filename="done.pdf", status="confirmed")
    got = admin_client.get("/api/import/papers/pending").json()["data"]
    assert sorted(x["filename"] for x in got) == ["a.pdf", "b.pdf"]  # not the answers, not a confirmed job
    got = admin_client.get("/api/import/papers/pending?year=2024&paper_number=1").json()["data"]
    assert [x["filename"] for x in got] == ["a.pdf"]
    item = got[0]
    assert (item["job_id"], item["paper_key"]) == (str(a.id), "q1")
    assert item["metadata"]["year"] == 2024
    prev = item["preview"]
    assert prev["url"] == f"https://fake.url/tmp/ingest/{a.id}/pages/p03.webp"
    assert prev["rect"] == rect(3) and prev["page"]["page"] == 3 and prev["page"]["width_px"] > 0
    assert admin_client.get(f"/api/import/papers/pending?exclude_job_id={a.id}").json()["data"][0]["filename"] == "b.pdf"


def test_pending_non_admin_forbidden(public_client):
    assert public_client.get("/api/import/papers/pending").status_code == 403


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
    arow = row(db_session, ajob, akey)
    assert arow.matched_ingest_paper_id == row(db_session, qjob, qkey).id
    assert row(db_session, qjob, qkey).matched_ingest_paper_id == arow.id
    assert admin_client.get(f"/api/import/jobs/{ajob.id}/review").json()["matches"][akey]["paper_key"] == "q1"
    assert admin_client.get(f"/api/import/jobs/{qjob.id}/review").json()["matches"][qkey]["filename"] == "a.pdf"
    assert admin_client.delete(url).status_code == 204
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
    url = f"/api/import/jobs/{ajob.id}/papers/{akey}/match"
    assert admin_client.post(url, json={"ingest_paper_id": 999999}).status_code == 404
    assert admin_client.post(url, json={"ingest_paper_id": row(db_session, other_answers, ok).id}).status_code == 422
    assert admin_client.post(url, json={"ingest_paper_id": row(db_session, ajob, akey).id}).status_code == 422
    # only an answer-only paper is linked from this side
    assert admin_client.post(
        f"/api/import/jobs/{qjob.id}/papers/{qkey}/match", json={"ingest_paper_id": row(db_session, ajob, akey).id}
    ).status_code == 422
    assert admin_client.post(
        f"/api/import/jobs/{ajob.id}/papers/nope/match", json={"ingest_paper_id": row(db_session, qjob, qkey).id}
    ).status_code == 404


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
