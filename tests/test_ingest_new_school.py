"""A school typed during review that is not in the reference list (#87): held on the pending paper as
``new_school_name`` and only created when a question paper is confirmed."""

from app.models.orm import School
from app.services.ingest_papers import sync_job_papers
from tests.test_ingest_confirm import env, paper, proposal, q, r  # noqa: F401
from tests.test_ingest_review import make_job
from tests.test_ingest_papers import rows


def _job(db, admin):
    job = make_job(db, admin)
    job.report = {"paper_metadata": {"q1": {"year": 2024}}}
    sync_job_papers(db, job)
    db.commit()
    return job


def test_metadata_holds_a_new_school_name_without_creating_it(admin_client, db_session, admin_user):
    job = _job(db_session, admin_user)
    url = f"/api/import/jobs/{job.id}/papers/q1/metadata"
    resp = admin_client.put(url, json={"year": 2024, "new_school_name": "  Raffles Instn "})
    assert resp.status_code == 200 and resp.json()["metadata_source"] == "admin"
    row = rows(db_session, job)["q1"]
    assert (row.school_id, row.new_school_name) == (None, "Raffles Instn")
    assert db_session.query(School).filter_by(name="Raffles Instn").count() == 0


def test_a_new_name_equal_to_an_existing_school_resolves_to_it(admin_client, db_session, admin_user, reference_data):
    job = _job(db_session, admin_user)
    url = f"/api/import/jobs/{job.id}/papers/q1/metadata"
    admin_client.put(url, json={"new_school_name": "raffles INSTITUTION"})
    row = rows(db_session, job)["q1"]
    assert (row.school_id, row.new_school_name) == (reference_data["school"].id, None)


def test_choosing_a_school_drops_the_new_name(admin_client, db_session, admin_user, reference_data):
    job = _job(db_session, admin_user)
    url = f"/api/import/jobs/{job.id}/papers/q1/metadata"
    admin_client.put(url, json={"new_school_name": "Raffles Instn"})
    admin_client.put(url, json={"school_id": reference_data["school"].id, "new_school_name": "Raffles Instn"})
    row = rows(db_session, job)["q1"]
    assert (row.school_id, row.new_school_name) == (reference_data["school"].id, None)


# --- matching by the typed name -------------------------------------------------------------


def _pending(db, admin, kind, meta, name, filename):
    from tests.test_ingest_match import job_with, row

    job, key = job_with(db, admin, kind, {**meta, "school_id": None}, filename=filename)
    got = row(db, job, key)
    got.new_school_name = name
    db.flush()
    return got


def test_papers_with_the_same_new_school_name_are_matched(db_session, admin_user, reference_data):
    from app.services.ingest_matching import match_row
    from tests.test_ingest_match import ANSWERS, QUESTION
    from tests.test_ingest_matching import add_paper

    meta = _meta(reference_data)
    add_paper(db_session, admin_user, meta)  # a bank paper of a known school never matches a new one
    other = _pending(db_session, admin_user, QUESTION, meta, "Other New School", "other.pdf")
    question = _pending(db_session, admin_user, QUESTION, meta, "Raffles Instn", "q.pdf")
    answers = _pending(db_session, admin_user, ANSWERS, meta, " raffles INSTN", "a.pdf")
    match_row(db_session, answers)
    assert answers.matched_ingest_paper_id == question.id and answers.match_status == "auto"
    assert other.matched_ingest_paper_id is None


def test_a_new_school_never_matches_a_paper_with_an_id(db_session, admin_user, reference_data):
    from app.services.ingest_matching import match_row
    from tests.test_ingest_match import ANSWERS, QUESTION, job_with

    meta = _meta(reference_data)
    job_with(db_session, admin_user, QUESTION, meta, filename="q.pdf")  # same key, but a known school
    answers = _pending(db_session, admin_user, ANSWERS, meta, "Raffles Instn", "a.pdf")
    match_row(db_session, answers)
    assert (answers.matched_ingest_paper_id, answers.match_status) == (None, None)


def _meta(rd):
    return {
        "school_id": rd["school"].id, "year": 2024, "level_id": rd["level"].id, "subject_id": rd["subject"].id,
        "exam_type_id": rd["exam_type"].id, "stream_id": rd["stream"].id, "paper_number": "1",
    }


# --- confirm creates (or finds) the school ----------------------------------------------------


def _confirm_new(admin_client, db, env, name):  # noqa: F811
    setup, meta = env
    job = setup()
    sync_job_papers(db, job)
    db.commit()
    body = {**{k: v for k, v in meta.items() if k != "school_id"}, "new_school_name": name, "paper_label": "q1"}
    return job, admin_client.post(f"/api/import/jobs/{job.id}/confirm", json=body)


def test_confirm_creates_the_new_school_and_back_fills_other_pending_papers(
    admin_client, db_session, admin_user, env, reference_data  # noqa: F811
):
    from app.models.orm import Paper
    from tests.test_ingest_match import ANSWERS

    waiting = _pending(db_session, admin_user, ANSWERS, _meta(reference_data), "raffles instn ", "a.pdf")
    different = _pending(db_session, admin_user, ANSWERS, _meta(reference_data), "Another School", "b.pdf")
    db_session.commit()
    job, resp = _confirm_new(admin_client, db_session, env, " Raffles Instn")
    assert resp.status_code == 201, resp.text
    school = db_session.query(School).filter_by(name="Raffles Instn").one()
    assert db_session.get(Paper, resp.json()["paper_id"]).school_id == school.id
    db_session.expire_all()
    assert (rows(db_session, job)["q1"].school_id, rows(db_session, job)["q1"].new_school_name) == (school.id, None)
    assert (waiting.school_id, waiting.new_school_name) == (school.id, None)
    assert (different.school_id, different.new_school_name) == (None, "Another School")


def test_confirm_uses_a_school_created_meanwhile(admin_client, db_session, env, reference_data):  # noqa: F811
    from app.models.orm import Paper

    _, resp = _confirm_new(admin_client, db_session, env, "RAFFLES institution")
    assert resp.status_code == 201, resp.text
    assert db_session.get(Paper, resp.json()["paper_id"]).school_id == reference_data["school"].id
    assert db_session.query(School).count() == 1


def test_confirm_needs_a_school(admin_client, db_session, env):  # noqa: F811
    _, resp = _confirm_new(admin_client, db_session, env, "  ")
    assert resp.status_code == 422
    assert db_session.query(School).filter(School.name == "").count() == 0


def test_the_job_list_carries_the_new_school_name(admin_client, db_session, admin_user, reference_data):
    from tests.test_answer_coverage import summary
    from tests.test_ingest_match import QUESTION

    _pending(db_session, admin_user, QUESTION, _meta(reference_data), "Raffles Instn", "q.pdf")
    db_session.commit()
    p = summary(admin_client, "q.pdf")
    assert (p["school_id"], p["new_school_name"]) == (None, "Raffles Instn")
