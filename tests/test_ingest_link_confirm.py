"""Pending question job <-> pending answer job (#84): auto-linking and the combined confirm."""

import pytest

from app.models.orm import IngestJob, IngestPaper, IngestEvent, Paper
from app.services.ingest_matching import match_job, match_row
from app.services.ingest_papers import sync_job_papers
from tests.test_ingest_confirm import env, paper as qpaper, proposal, q, r, source_pdf, W, H  # noqa: F401
from tests.test_ingest_review import make_job, page


@pytest.fixture
def meta(reference_data):
    rd = reference_data
    return {
        "school_id": rd["school"].id, "year": 2024, "level_id": rd["level"].id, "subject_id": rd["subject"].id,
        "exam_type_id": rd["exam_type"].id, "stream_id": rd["stream"].id, "paper_number": "1",
    }


def answers_paper():
    return {
        "label": None, "answer_label": "a1", "role": "answer_only", "answer_template": "table",
        "pages": [page(1, W, H), page(2, W, H), page(3, W, H)],
        "questions": [
            q(1, [], [r(1, 10, 10, 200, 60)]), q(2, [], [r(2, 10, 10, 200, 60)]), q(9, [], [r(3, 10, 10, 200, 60)]),
        ],
        "orphan_answers": [], "warnings": [],
    }


def mk(db, admin, store, paper, key, meta, filename, status="review_ready"):
    job = make_job(db, admin, proposal=proposal(paper), pages=3, filename=filename, status=status)
    store.objects[job.source_key] = source_pdf()
    job.report = {"paper_metadata": {key: meta}}
    sync_job_papers(db, job)
    db.commit()
    return job


def prow(db, job, key):
    db.expire_all()
    return db.query(IngestPaper).filter_by(job_id=job.id, paper_key=key).one()


def test_answer_job_links_to_the_single_pending_question_paper(db_session, admin_user, fake_object_store, meta):
    qj = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "a.pdf")
    match_job(db_session, aj)
    db_session.commit()
    a, qq = prow(db_session, aj, "a1"), prow(db_session, qj, "q1")
    assert a.matched_ingest_paper_id == qq.id and qq.matched_ingest_paper_id == a.id
    assert (a.match_status, a.match_note) == ("auto", "auto-linked")


def test_question_job_finishing_later_links_an_older_answer_job(db_session, admin_user, fake_object_store, meta):
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "a.pdf")
    qj = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q.pdf")
    match_job(db_session, qj)
    db_session.commit()
    assert prow(db_session, aj, "a1").matched_ingest_paper_id == prow(db_session, qj, "q1").id


def test_ambiguous_matches_are_not_linked(db_session, admin_user, fake_object_store, meta):
    q1 = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q1.pdf")
    q2 = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q2.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "a.pdf")
    match_job(db_session, aj)
    db_session.commit()
    a = prow(db_session, aj, "a1")
    assert a.matched_ingest_paper_id is None and a.match_status == "manual"
    assert "2 pending question papers" in a.match_note
    assert prow(db_session, q1, "q1").matched_ingest_paper_id is None
    # two answer jobs for one question paper: neither is linked either
    a2 = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "a2.pdf")
    db_session.delete(q2)
    db_session.commit()
    match_job(db_session, q1)
    db_session.commit()
    assert prow(db_session, aj, "a1").matched_ingest_paper_id is None
    assert prow(db_session, a2, "a1").matched_ingest_paper_id is None


def test_partial_key_is_not_linked(db_session, admin_user, fake_object_store, meta):
    mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", {**meta, "paper_number": None}, "a.pdf")
    match_job(db_session, aj)
    db_session.commit()
    assert prow(db_session, aj, "a1").matched_ingest_paper_id is None


def test_confirmed_paper_proposal_wins_over_auto_link(db_session, admin_user, fake_object_store, meta):
    from datetime import UTC, datetime
    db_session.add(Paper(**meta, created_by=admin_user.id, created_at=datetime.now(UTC)))
    db_session.flush()
    mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "a.pdf")
    match_job(db_session, aj)
    db_session.commit()
    a = prow(db_session, aj, "a1")
    assert a.match_status == "proposed" and a.matched_ingest_paper_id is None


def test_metadata_edit_drops_an_auto_link_and_unmatch_rejects_the_pair(admin_client, db_session, admin_user, fake_object_store, meta):
    qj = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "a.pdf")
    match_job(db_session, aj)
    db_session.commit()
    url = f"/api/import/jobs/{aj.id}/papers/a1/metadata"
    assert admin_client.put(url, json={**meta, "year": 2020}).status_code == 200
    assert prow(db_session, aj, "a1").matched_ingest_paper_id is None
    assert prow(db_session, qj, "q1").match_status is None
    admin_client.put(url, json=meta)  # back to the same key: linked again
    assert prow(db_session, aj, "a1").matched_ingest_paper_id == prow(db_session, qj, "q1").id
    resp = admin_client.delete(f"/api/import/jobs/{aj.id}/papers/a1/match")
    assert resp.status_code == 200 and resp.json() == {"matches": None, "proposal": None}
    assert prow(db_session, aj, "a1").matched_ingest_paper_id is None  # not re-made at once
    match_job(db_session, qj)  # nor from the question side
    db_session.commit()
    assert prow(db_session, aj, "a1").matched_ingest_paper_id is None
    admin_client.put(url, json={**meta, "year": 2020})
    admin_client.put(url, json=meta)  # nor after a metadata edit: the pair itself was rejected
    assert prow(db_session, aj, "a1").matched_ingest_paper_id is None
    assert prow(db_session, aj, "a1").match_status is None and prow(db_session, qj, "q1").match_status is None


def test_unmatch_frees_both_papers_to_find_another_partner(admin_client, db_session, admin_user, fake_object_store, meta):
    q1 = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q1.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "a.pdf")
    match_job(db_session, aj)
    db_session.commit()
    q2 = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q2.pdf")  # a linked answer is left alone
    match_job(db_session, q2)
    db_session.commit()
    assert prow(db_session, aj, "a1").matched_ingest_paper_id == prow(db_session, q1, "q1").id
    resp = admin_client.delete(f"/api/import/jobs/{aj.id}/papers/a1/match")
    assert resp.status_code == 200
    a = prow(db_session, aj, "a1")
    assert a.matched_ingest_paper_id == prow(db_session, q2, "q1").id and a.match_status == "auto"
    assert resp.json()["matches"]["filename"] == "q2.pdf"
    # and the freed question paper takes another answer paper with its key
    a2 = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "a2.pdf")
    match_job(db_session, a2)
    db_session.commit()
    assert prow(db_session, a2, "a1").matched_ingest_paper_id == prow(db_session, q1, "q1").id


def test_unmatch_from_the_question_side_rejects_the_pair(admin_client, db_session, admin_user, fake_object_store, meta):
    qj = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "a.pdf")
    match_job(db_session, aj)
    db_session.commit()
    assert admin_client.delete(f"/api/import/jobs/{qj.id}/papers/q1/match").status_code == 200
    match_job(db_session, aj)
    match_job(db_session, qj)
    db_session.commit()
    assert prow(db_session, aj, "a1").matched_ingest_paper_id is None


def test_review_of_question_paper_shows_the_link(admin_client, db_session, admin_user, fake_object_store, meta):
    qj = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "answers.pdf")
    match_job(db_session, aj)
    db_session.commit()
    link = admin_client.get(f"/api/import/jobs/{qj.id}/review").json()["matches"]["q1"]
    assert (link["filename"], link["paper_key"], link["job_id"]) == ("answers.pdf", "a1", str(aj.id))


def test_confirm_brings_in_the_other_jobs_answers_and_settles_both(
    admin_client, db_session, admin_user, fake_object_store, mock_s3, meta, env  # noqa: F811
):
    _, cmeta = env
    qj = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "answers.pdf")
    match_job(db_session, aj)
    db_session.commit()
    resp = admin_client.post(f"/api/import/jobs/{qj.id}/confirm", json={**cmeta, "paper_label": "q1"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["job_status"] == "confirmed"
    assert body["unmatched"] == [9]
    assert body["answers_from"] == {"job_id": str(aj.id), "filename": "answers.pdf", "paper_key": "a1", "attached": [1, 2]}
    qs = {x["question_number"]: x for x in body["questions"]}
    # q1: its own answer (page 3) first, then the other job's answer
    assert sorted((p["page_type"], p["page_order"]) for p in qs[1]["pages"] if p["page_type"] == "answer") == [
        ("answer", 1), ("answer", 2),
    ]
    paper = db_session.get(Paper, body["paper_id"])
    pages = {p.page_order: p for p in next(x for x in paper.questions if x.question_number == 1).pages if p.page_type == "answer"}
    assert pages[1].source_page == 3 and pages[2].source_page == 1
    assert [p.page_type for p in next(x for x in paper.questions if x.question_number == 2).pages].count("answer") == 1
    db_session.expire_all()
    for job, key, outcome in ((qj, "q1", "confirmed"), (aj, "a1", "attached")):
        j = db_session.get(IngestJob, job.id)
        assert j.status == "confirmed" and j.report["review_outcome"][key] == outcome
        assert paper.id in j.confirmed_paper_ids
        row = prow(db_session, j, key)
        assert row.status == outcome and row.paper_id == paper.id
    kinds = {(e.job_id, e.kind) for e in db_session.query(IngestEvent)}
    assert (aj.id, "paper_attached") in kinds and (qj.id, "paper_confirmed") in kinds
    assert not any(k.startswith(f"tmp/ingest/{aj.id}/") for k in fake_object_store.objects)
    assert not any(k.startswith(f"tmp/ingest/{qj.id}/") for k in fake_object_store.objects)


def test_confirm_proceeds_without_answers_when_the_answer_job_is_gone(
    admin_client, db_session, admin_user, fake_object_store, mock_s3, meta, env  # noqa: F811
):
    _, cmeta = env
    qj = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "answers.pdf")
    match_job(db_session, aj)
    aj.status = "cancelled"
    db_session.commit()
    resp = admin_client.post(f"/api/import/jobs/{qj.id}/confirm", json={**cmeta, "paper_label": "q1"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["answers_from"] is None
    db_session.expire_all()
    assert db_session.get(IngestJob, aj.id).status == "cancelled"
    assert prow(db_session, aj, "a1").status == "pending"


def test_skipping_a_linked_question_paper_releases_the_answer_paper(
    admin_client, db_session, admin_user, fake_object_store, meta
):
    qj = mk(db_session, admin_user, fake_object_store, qpaper(), "q1", meta, "q.pdf")
    aj = mk(db_session, admin_user, fake_object_store, answers_paper(), "a1", meta, "answers.pdf")
    match_job(db_session, aj)
    db_session.commit()
    assert admin_client.post(f"/api/import/jobs/{qj.id}/skip", json={"paper_label": "q1"}).status_code == 200
    a = prow(db_session, aj, "a1")
    assert a.matched_ingest_paper_id is None and a.match_status is None


# --- the same booklet (#90): a question paper and an answer-only paper the pipeline did not pair ---

def booklet(db, admin, store, meta, *, answers_meta=None, status="running", filename="booklet.pdf"):
    """One job holding question paper ``q1`` (no answers of its own) and answer-only paper ``a1``, as
    ``report`` leaves it: matching runs before the job turns ``review_ready``."""
    question = qpaper(answer_label=None, questions=[q(1, [r(1)]), q(2, [r(2, 50, 400, 300, 600)])])
    job = make_job(db, admin, proposal=proposal(question, answers_paper()), pages=3, filename=filename, status=status)
    store.objects[job.source_key] = source_pdf()
    job.report = {"paper_metadata": {"q1": meta, "a1": answers_meta or meta}}
    sync_job_papers(db, job)
    db.commit()
    return job


def test_a_booklets_own_answer_paper_is_auto_linked(db_session, admin_user, fake_object_store, meta):
    job = booklet(db_session, admin_user, fake_object_store, meta)
    match_job(db_session, job)
    db_session.commit()
    a, qq = prow(db_session, job, "a1"), prow(db_session, job, "q1")
    assert a.matched_ingest_paper_id == qq.id and qq.matched_ingest_paper_id == a.id
    assert (a.match_status, a.match_note) == ("auto", "auto-linked")


def test_editing_the_question_paper_links_it_to_its_booklets_answer_paper(
    admin_client, db_session, admin_user, fake_object_store, meta
):
    job = booklet(db_session, admin_user, fake_object_store, {**meta, "year": 2020}, answers_meta=meta, status="review_ready")
    match_job(db_session, job)
    db_session.commit()
    assert prow(db_session, job, "a1").matched_ingest_paper_id is None  # the key differs
    assert admin_client.put(f"/api/import/jobs/{job.id}/papers/q1/metadata", json=meta).status_code == 200
    a, qq = prow(db_session, job, "a1"), prow(db_session, job, "q1")
    assert a.matched_ingest_paper_id == qq.id and qq.match_status == "auto"
    link = admin_client.get(f"/api/import/jobs/{job.id}/review").json()["matches"]
    assert (link["q1"]["paper_key"], link["a1"]["paper_key"]) == ("a1", "q1")
    assert link["q1"]["job_id"] == str(job.id) and link["q1"]["answer_numbers"] == [1, 2, 9]


def test_unmatching_a_same_booklet_pair_rejects_it(admin_client, db_session, admin_user, fake_object_store, meta):
    job = booklet(db_session, admin_user, fake_object_store, meta, status="review_ready")
    match_job(db_session, job)
    db_session.commit()
    assert admin_client.delete(f"/api/import/jobs/{job.id}/papers/q1/match").status_code == 200
    match_job(db_session, job)
    db_session.commit()
    assert prow(db_session, job, "a1").matched_ingest_paper_id is None
    assert prow(db_session, job, "q1").matched_ingest_paper_id is None


def test_confirming_a_same_booklet_pair_settles_the_job_once(
    admin_client, db_session, admin_user, fake_object_store, mock_s3, meta, env  # noqa: F811
):
    _, cmeta = env
    job = booklet(db_session, admin_user, fake_object_store, meta, status="review_ready", filename="b.pdf")
    match_job(db_session, job)
    db_session.commit()
    reads = []
    get = fake_object_store.get
    fake_object_store.get = lambda key: reads.append(key) or get(key)
    resp = admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**cmeta, "paper_label": "q1"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert reads == [job.source_key]  # one source.pdf for both papers
    assert body["job_status"] == "confirmed"
    assert body["answers_from"] == {"job_id": str(job.id), "filename": "b.pdf", "paper_key": "a1", "attached": [1, 2]}
    assert body["unmatched"] == [9]
    paper = db_session.get(Paper, body["paper_id"])
    answers = {x.question_number: [p.source_page for p in x.pages if p.page_type == "answer"] for x in paper.questions}
    assert answers == {1: [1], 2: [2]}
    db_session.expire_all()
    j = db_session.get(IngestJob, job.id)
    assert j.status == "confirmed" and j.report["review_outcome"] == {"q1": "confirmed", "a1": "attached"}
    assert j.confirmed_paper_ids == [paper.id]
    assert (prow(db_session, j, "q1").status, prow(db_session, j, "a1").status) == ("confirmed", "attached")
    assert {e.kind for e in db_session.query(IngestEvent).filter_by(job_id=job.id)} >= {"paper_confirmed", "paper_attached"}
    assert not any(k.startswith(f"tmp/ingest/{job.id}/") for k in fake_object_store.objects)
