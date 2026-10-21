"""The answer mapping table (#92): which answers of an answer-only paper go onto which questions
when it is attached to a bank paper or confirmed with a linked question paper. A mapping is
``{answer label: question label | null}``; an answer it leaves out goes on by number."""

from app.models.orm import Paper, Question
from app.services.ingest_matching import match_job
from tests.test_ingest_confirm import attach_env, env, q, r  # noqa: F401
from tests.test_ingest_link_confirm import answers_paper, meta, mk, prow, question_paper  # noqa: F401
from tests.test_ingest_matching import add_paper
from tests.test_match_candidates import add_question


def answer_pages(db, paper_id, number):
    qn = db.query(Question).filter_by(paper_id=paper_id, question_number=number).one()
    db.refresh(qn)
    return [p for p in qn.pages if p.page_type == "answer"]


def test_attach_places_answers_by_the_mapping(attach_env, db_session):  # noqa: F811
    attach, paper_id = attach_env
    # A Section B numbered from 1: answer 1 belongs to question 2; "3a" is left off on purpose
    job, resp = attach(
        q(1, [], [r(3, 10, 70, 200, 120)]), q("3a", [], [r(3)]), q(2, [], [r(3)]),
        mapping={"1": "2", "3a": None},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attached"] == [2] and body["unmatched"] == ["3a"]  # answer 2 by number, onto Q2 too
    assert len(answer_pages(db_session, paper_id, 2)) == 2
    assert len(answer_pages(db_session, paper_id, 1)) == 1  # its own page only


def test_attach_without_a_mapping_still_goes_by_number(attach_env, db_session):  # noqa: F811
    attach, paper_id = attach_env
    _, resp = attach(q(2, [], [r(3)]))
    assert resp.status_code == 200 and resp.json()["attached"] == [2]


# --- a linked pair keeps its mapping on the answer paper's row ------------------------------------


def linked(db, admin, store, meta, filename="answers.pdf"):  # noqa: F811
    qj = mk(db, admin, store, question_paper(), "q1", meta, "q.pdf")
    aj = mk(db, admin, store, answers_paper(), "a1", meta, filename)
    return qj, aj


def test_pairing_saves_the_mapping_and_confirm_places_answers_by_it(
    admin_client, db_session, admin_user, fake_object_store, mock_s3, meta, env  # noqa: F811
):
    _, cmeta = env
    qj, aj = linked(db_session, admin_user, fake_object_store, {**meta, "year": 2020})  # no auto link
    resp = admin_client.post(
        f"/api/import/jobs/{qj.id}/papers/q1/match",
        json={"ingest_paper_id": prow(db_session, aj, "a1").id, "mapping": {"1": "2", "2": None, "9": "1"}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["matches"]["answer_map"] == {"1": "2", "2": None, "9": "1"}
    assert prow(db_session, aj, "a1").answer_map == {"1": "2", "2": None, "9": "1"}  # on the answer paper
    assert prow(db_session, qj, "q1").answer_map is None
    resp = admin_client.post(f"/api/import/jobs/{qj.id}/confirm", json={**cmeta, "paper_label": "q1"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["answers_from"]["attached"] == [1, 2] and body["unmatched"] == [2]
    paper = db_session.get(Paper, body["paper_id"])
    answers = {x.question_number: [p.source_page for p in x.pages if p.page_type == "answer"] for x in paper.questions}
    # q1: answer 9 (page 3); q2: answer 1 (page 1)
    assert answers == {1: [3], 2: [1]}


def test_a_linked_pair_with_no_mapping_goes_by_number(db_session, admin_user, fake_object_store, meta):  # noqa: F811
    _, aj = linked(db_session, admin_user, fake_object_store, meta)
    match_job(db_session, aj)
    db_session.commit()
    a = prow(db_session, aj, "a1")
    assert a.match_status == "auto" and a.answer_map is None


def test_changing_the_match_discards_the_mapping(admin_client, db_session, admin_user, fake_object_store, meta):  # noqa: F811
    q1, aj = linked(db_session, admin_user, fake_object_store, {**meta, "year": 2020})
    q2 = mk(db_session, admin_user, fake_object_store, question_paper(), "q1", {**meta, "year": 2020}, "q2.pdf")
    url = f"/api/import/jobs/{aj.id}/papers/a1/match"
    admin_client.post(url, json={"ingest_paper_id": prow(db_session, q1, "q1").id, "mapping": {"1": "2"}})
    admin_client.post(url, json={"ingest_paper_id": prow(db_session, q2, "q1").id})  # a new match
    assert prow(db_session, aj, "a1").answer_map is None
    admin_client.post(url, json={"ingest_paper_id": prow(db_session, q1, "q1").id, "mapping": {"1": "2"}})
    admin_client.delete(url)  # Unmatch
    assert prow(db_session, aj, "a1").answer_map is None


def test_check_answers_saves_an_edited_mapping_on_an_auto_link_which_keeps_it(
    admin_client, db_session, admin_user, fake_object_store, meta  # noqa: F811
):
    qj, aj = linked(db_session, admin_user, fake_object_store, meta)
    match_job(db_session, aj)
    db_session.commit()
    # from the question side: stored on the answer paper
    resp = admin_client.put(f"/api/import/jobs/{qj.id}/papers/q1/answer-map", json={"mapping": {"9": None, "1": "2"}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["matches"]["answer_map"] == {"9": None, "1": "2"}
    assert resp.json()["matches"]["answer_numbers"] == ["2", 2]  # where the answers land
    assert prow(db_session, aj, "a1").answer_map == {"9": None, "1": "2"}
    # re-matching re-makes the same auto link and keeps the mapping
    admin_client.put(f"/api/import/jobs/{aj.id}/papers/a1/metadata", json=meta)
    a = prow(db_session, aj, "a1")
    assert a.match_status == "auto" and a.answer_map == {"9": None, "1": "2"}
    # a metadata edit that breaks the auto link drops it
    admin_client.put(f"/api/import/jobs/{aj.id}/papers/a1/metadata", json={**meta, "year": 2020})
    admin_client.put(f"/api/import/jobs/{aj.id}/papers/a1/metadata", json=meta)
    assert prow(db_session, aj, "a1").answer_map is None


def test_answer_map_needs_a_pending_linked_paper(admin_client, db_session, admin_user, fake_object_store, meta):  # noqa: F811
    qj, aj = linked(db_session, admin_user, fake_object_store, {**meta, "year": 2020})
    url = f"/api/import/jobs/{aj.id}/papers/a1/answer-map"
    assert admin_client.put(url, json={"mapping": {"1": "2"}}).status_code == 409
    assert admin_client.put(f"/api/import/jobs/{aj.id}/papers/zz/answer-map", json={"mapping": {}}).status_code == 404


# --- GET .../papers/{key}/answer-map: what the mapping table shows ---------------------------------


def table(client, job, key, **target):
    resp = client.get(f"/api/import/jobs/{job.id}/papers/{key}/answer-map", params=target)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_table_for_a_pending_pair_from_either_side(admin_client, db_session, admin_user, fake_object_store, meta):  # noqa: F811
    qj, aj = linked(db_session, admin_user, fake_object_store, {**meta, "year": 2020})
    got = table(admin_client, aj, "a1", ingest_paper_id=prow(db_session, qj, "q1").id)
    assert [(x["label"], x["answered"]) for x in got["questions"]] == [("1", False), ("2", False)]
    assert [a["label"] for a in got["answers"]] == ["1", "2", "9"]
    assert got["answers"][1]["preview"]["url"] == f"https://fake.url/tmp/ingest/{aj.id}/pages/p02.webp"
    assert got["questions"][0]["preview"]["rect"]["page"] == 1
    assert got["mapping"] is None  # not paired yet: by number
    admin_client.post(
        f"/api/import/jobs/{aj.id}/papers/a1/match",
        json={"ingest_paper_id": prow(db_session, qj, "q1").id, "mapping": {"9": None}},
    )
    mine = table(admin_client, qj, "q1")  # no target: the current partner
    assert [a["label"] for a in mine["answers"]] == ["1", "2", "9"] and mine["mapping"] == {"9": None}


def test_the_table_for_a_bank_paper(admin_client, db_session, admin_user, fake_object_store, meta):  # noqa: F811
    _, aj = linked(db_session, admin_user, fake_object_store, meta)
    bank = add_paper(db_session, admin_user, meta)
    add_question(db_session, bank, 2, answered=True)
    add_question(db_session, bank, 1)
    db_session.commit()
    got = table(admin_client, aj, "a1", paper_id=bank.id)
    assert [(x["label"], x["answered"]) for x in got["questions"]] == [("1", False), ("2", True)]
    assert got["questions"][0]["preview"] == {"number": 1, "url": f"https://fake.url/img/{bank.id}/1.webp"}
    assert got["mapping"] is None


def test_the_table_needs_a_partner(admin_client, db_session, admin_user, fake_object_store, meta):  # noqa: F811
    qj, aj = linked(db_session, admin_user, fake_object_store, {**meta, "year": 2020})
    url = f"/api/import/jobs/{qj.id}/papers/q1/answer-map"
    assert admin_client.get(url).status_code == 409  # not paired
    bank = add_paper(db_session, admin_user, meta)
    db_session.commit()
    assert admin_client.get(url, params={"paper_id": bank.id}).status_code == 422  # a question paper: never a bank paper
    assert admin_client.get(url, params={"ingest_paper_id": 99999}).status_code == 404
