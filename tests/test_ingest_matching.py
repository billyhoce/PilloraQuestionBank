"""Automatic matching of an answer-only paper to a confirmed paper (#83), and "Not this one" (#88)."""

from datetime import UTC, datetime

import pytest

from app.models.orm import IngestPaper, Paper
from app.services.ingest_matching import match_for_new_paper, match_info, match_row
from app.services.ingest_papers import link_papers, unlink_paper
from tests.test_ingest_confirm import env, paper as confirm_paper, proposal as confirm_proposal  # noqa: F401
from tests.test_ingest_match import ANSWERS, QUESTION, job_with, row


@pytest.fixture
def meta(reference_data):
    rd = reference_data
    return {
        "school_id": rd["school"].id, "year": 2024, "level_id": rd["level"].id, "subject_id": rd["subject"].id,
        "exam_type_id": rd["exam_type"].id, "stream_id": rd["stream"].id, "paper_number": "1",
    }


def add_paper(db, admin, meta, **over):
    p = Paper(**{**meta, **over}, created_by=admin.id, created_at=datetime.now(UTC))
    db.add(p)
    db.flush()
    return p


def answers_job(db, admin, meta, **kw):
    job, key = job_with(db, admin, ANSWERS, meta, **kw)
    return job, row(db, job, key)


def state(r):
    return (r.match_status, r.proposed_paper_id, r.match_note)


def test_single_exact_match_is_proposed(db_session, admin_user, meta):
    target = add_paper(db_session, admin_user, meta)
    add_paper(db_session, admin_user, meta, year=2023)
    _, r = answers_job(db_session, admin_user, meta)
    match_row(db_session, r)
    assert state(r) == ("proposed", target.id, None)


def test_paper_number_is_trimmed_and_casefolded_only(db_session, admin_user, meta):
    target = add_paper(db_session, admin_user, {**meta, "paper_number": " 2a "})
    _, r = answers_job(db_session, admin_user, {**meta, "paper_number": "2A"})
    match_row(db_session, r)
    assert r.proposed_paper_id == target.id
    r.paper_number = "02A"  # not normalised any further
    match_row(db_session, r)
    assert r.match_status == "manual" and "paper number" in r.match_note


def test_several_exact_candidates_go_manual(db_session, admin_user, meta):
    add_paper(db_session, admin_user, meta)
    add_paper(db_session, admin_user, meta)
    _, r = answers_job(db_session, admin_user, meta)
    match_row(db_session, r)
    assert state(r) == ("manual", None, "2 papers have this key")


def test_partial_match_goes_manual_and_names_the_differences(db_session, admin_user, meta, reference_data):
    add_paper(db_session, admin_user, meta, paper_number="2")
    _, r = answers_job(db_session, admin_user, meta)
    match_row(db_session, r)
    assert state(r) == ("manual", None, "partial: paper number differ")


def test_unknown_field_with_partial_candidates_goes_manual(db_session, admin_user, meta):
    add_paper(db_session, admin_user, meta)
    _, r = answers_job(db_session, admin_user, {**meta, "paper_number": None, "stream_id": None})
    match_row(db_session, r)
    assert r.match_status == "manual" and r.proposed_paper_id is None
    assert r.match_note == "partial: unknown stream, paper number"


def test_no_candidates_leaves_nothing(db_session, admin_user, meta):
    add_paper(db_session, admin_user, meta, year=2020)
    _, r = answers_job(db_session, admin_user, meta)
    match_row(db_session, r)
    assert state(r) == (None, None, None)
    _, r2 = answers_job(db_session, admin_user, {**meta, "year": None})
    match_row(db_session, r2)
    assert state(r2) == (None, None, None)


def test_question_papers_are_not_matched(db_session, admin_user, meta):
    add_paper(db_session, admin_user, meta)
    job, key = job_with(db_session, admin_user, QUESTION, meta)
    r = row(db_session, job, key)
    match_row(db_session, r)
    assert state(r) == (None, None, None)


def test_a_pending_link_takes_precedence(db_session, admin_user, meta):
    add_paper(db_session, admin_user, meta)
    qjob, qkey = job_with(db_session, admin_user, QUESTION, meta)
    ajob, r = answers_job(db_session, admin_user, meta)
    link_papers(db_session, ajob, r.paper_key, row(db_session, qjob, qkey).id)
    match_row(db_session, r)
    assert state(r) == (None, None, None) and match_info(db_session, ajob) == {}
    unlink_paper(db_session, ajob, r.paper_key)  # back to what the bank offers
    assert r.match_status == "proposed"


def test_new_paper_surfaces_on_pending_answer_job(db_session, admin_user, meta):
    ajob, r = answers_job(db_session, admin_user, meta)
    match_row(db_session, r)
    assert r.match_status is None
    target = add_paper(db_session, admin_user, meta)
    match_for_new_paper(db_session, target)
    assert state(r) == ("proposed", target.id, None)
    info = match_info(db_session, ajob)[r.paper_key]
    assert info["status"] == "proposed" and info["paper"]["id"] == target.id
    assert info["paper"]["answer_coverage"] == "none"  # Attach asks append/replace only for "partial"
    other = add_paper(db_session, admin_user, meta)  # a duplicate arrives: now ambiguous
    match_for_new_paper(db_session, other)
    assert r.match_status == "manual" and match_info(db_session, ajob)[r.paper_key]["paper"] is None


def test_new_paper_skips_settled_and_other_papers(db_session, admin_user, meta):
    _, settled = answers_job(db_session, admin_user, meta)
    settled.status = "skipped"
    _, other = answers_job(db_session, admin_user, {**meta, "year": 2020})
    db_session.flush()
    target = add_paper(db_session, admin_user, meta)
    match_for_new_paper(db_session, target)
    assert state(settled) == (None, None, None) and state(other) == (None, None, None)


def test_match_for_new_paper_never_raises(db_session, admin_user, meta):
    class Broken:
        school_id = year = subject_id = id = None

        def __getattr__(self, name):
            raise RuntimeError("boom")

    match_for_new_paper(db_session, Broken())  # swallowed


def test_review_shows_proposal_and_attach_clears_it(admin_client, db_session, admin_user, meta, fake_object_store):
    target = add_paper(db_session, admin_user, meta)
    ajob, r = answers_job(db_session, admin_user, meta)
    match_row(db_session, r)
    db_session.commit()
    body = admin_client.get(f"/api/import/jobs/{ajob.id}/review").json()
    prop = body["proposals"][r.paper_key]
    assert prop["status"] == "proposed" and prop["paper"]["id"] == target.id and prop["paper"]["year"] == 2024
    from app.services.ingest_papers import set_status
    set_status(db_session, ajob, r.paper_key, "attached", target.id)
    db_session.commit()
    assert state(row(db_session, ajob, r.paper_key)) == (None, None, None)


def test_metadata_edit_rematches(admin_client, db_session, admin_user, meta):
    add_paper(db_session, admin_user, meta)
    ajob, r = answers_job(db_session, admin_user, {**meta, "year": 2020})
    db_session.commit()
    resp = admin_client.put(f"/api/import/jobs/{ajob.id}/papers/{r.paper_key}/metadata", json=meta)
    assert resp.status_code == 200
    assert resp.json()["proposal"]["status"] == "proposed"
    assert row(db_session, ajob, r.paper_key).match_status == "proposed"
    resp = admin_client.put(f"/api/import/jobs/{ajob.id}/papers/{r.paper_key}/metadata", json={**meta, "year": 2020})
    assert resp.json()["proposal"] is None


def test_confirming_a_paper_proposes_it_to_pending_answers(admin_client, db_session, admin_user, env, meta):  # noqa: F811
    setup, cmeta = env
    ajob, r = answers_job(db_session, admin_user, meta)
    db_session.commit()
    job = setup()
    resp = admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**cmeta, "paper_label": "q1"})
    assert resp.status_code == 201, resp.text
    got = row(db_session, ajob, r.paper_key)
    assert state(got) == ("proposed", resp.json()["paper_id"], None)


def test_not_this_one_rejects_the_proposed_paper_and_rematches(admin_client, db_session, admin_user, meta):
    wrong = add_paper(db_session, admin_user, meta)
    ajob, r = answers_job(db_session, admin_user, meta)
    match_row(db_session, r)
    db_session.commit()
    url = f"/api/import/jobs/{ajob.id}/papers/{r.paper_key}/proposed-paper"
    resp = admin_client.delete(url)
    assert resp.status_code == 200, resp.text
    # the only candidate was the rejected one: nothing left, not even a partial hint
    assert resp.json() == {"matches": None, "proposal": None}
    assert state(row(db_session, ajob, r.paper_key)) == (None, None, None)
    match_for_new_paper(db_session, wrong)  # re-running matching never proposes it again
    assert state(row(db_session, ajob, r.paper_key)) == (None, None, None)
    right = add_paper(db_session, admin_user, meta)  # but another paper with the key is proposed
    match_for_new_paper(db_session, right)
    assert state(row(db_session, ajob, r.paper_key)) == ("proposed", right.id, None)


def test_not_this_one_can_fall_through_to_a_pending_question_paper(admin_client, db_session, admin_user, meta):
    add_paper(db_session, admin_user, meta)
    qjob, qkey = job_with(db_session, admin_user, QUESTION, meta, filename="q.pdf")
    ajob, r = answers_job(db_session, admin_user, meta)
    match_row(db_session, r)
    db_session.commit()
    assert r.match_status == "proposed"  # a confirmed paper wins over the pending one
    resp = admin_client.delete(f"/api/import/jobs/{ajob.id}/papers/{r.paper_key}/proposed-paper")
    assert resp.json()["matches"]["filename"] == "q.pdf" and resp.json()["proposal"] is None
    assert row(db_session, ajob, r.paper_key).matched_ingest_paper_id == row(db_session, qjob, qkey).id


def test_not_this_one_needs_a_pending_proposal(admin_client, db_session, admin_user, meta):
    ajob, r = answers_job(db_session, admin_user, meta)
    db_session.commit()
    url = f"/api/import/jobs/{ajob.id}/papers/{r.paper_key}/proposed-paper"
    assert admin_client.delete(url).status_code == 409  # nothing proposed
    assert admin_client.delete(f"/api/import/jobs/{ajob.id}/papers/nope/proposed-paper").status_code == 404
