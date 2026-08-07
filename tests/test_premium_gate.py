"""Unit tests for the per-school-level premium gate (`app/services/premium.py`).

The route tests cover what a viewer actually sees; these pin the policy itself,
including the cases the HTTP tests can't easily reach (anonymous viewers, an
admin's unrestricted `None`, and the SQL form agreeing with the in-memory one).
"""

import pytest

from app.models.orm import Paper, Question
from app.services.premium import (
    can_view_paper,
    entitled_school_level_ids,
    premium_gate,
    restrict_premium_pool,
)


@pytest.fixture
def primary_paper(db_session, reference_data, admin_user):
    """A premium paper in the *other* school level (Primary)."""
    paper = Paper(
        subject_id=reference_data["subject"].id,
        stream_id=reference_data["other_stream"].id,
        level_id=reference_data["other_level"].id,
        school_id=reference_data["school"].id,
        exam_type_id=reference_data["exam_type"].id,
        year=2024,
        paper_number="9",
        is_premium=True,
        created_by=admin_user.id,
    )
    db_session.add(paper)
    db_session.flush()
    db_session.add(Question(paper_id=paper.id, question_number=1))
    db_session.flush()
    return paper


# ---------------------------------------------------------------------------
# entitled_school_level_ids
# ---------------------------------------------------------------------------


def test_anonymous_holds_nothing():
    assert entitled_school_level_ids(None) == set()


def test_admin_is_unrestricted(admin_user):
    assert entitled_school_level_ids(admin_user) is None


def test_public_user_holds_nothing(public_user):
    assert entitled_school_level_ids(public_user) == set()


def test_premium_user_holds_their_school_level(premium_user, reference_data):
    assert entitled_school_level_ids(premium_user) == {
        reference_data["school_level"].id
    }


# ---------------------------------------------------------------------------
# can_view_paper
# ---------------------------------------------------------------------------


def test_free_paper_is_open_to_anonymous(sample_paper):
    assert can_view_paper(None, sample_paper) is True


def test_premium_paper_closed_to_anonymous(db_session, sample_paper):
    sample_paper.is_premium = True
    db_session.flush()
    assert can_view_paper(None, sample_paper) is False


def test_premium_paper_open_to_matching_school_level(
    db_session, sample_paper, premium_user
):
    sample_paper.is_premium = True
    db_session.flush()
    assert can_view_paper(premium_user, sample_paper) is True


def test_premium_paper_closed_to_other_school_level(
    db_session, sample_paper, other_premium_user
):
    sample_paper.is_premium = True
    db_session.flush()
    assert can_view_paper(other_premium_user, sample_paper) is False


def test_free_paper_open_to_user_holding_a_different_school_level(
    sample_paper, other_premium_user
):
    assert can_view_paper(other_premium_user, sample_paper) is True


def test_admin_opens_any_premium_paper(db_session, sample_paper, admin_user):
    sample_paper.is_premium = True
    db_session.flush()
    assert can_view_paper(admin_user, sample_paper) is True


def test_gate_matches_can_view_paper(db_session, sample_paper, other_premium_user):
    sample_paper.is_premium = True
    db_session.flush()
    gate = premium_gate(other_premium_user)
    assert gate(sample_paper) == can_view_paper(other_premium_user, sample_paper)


# ---------------------------------------------------------------------------
# restrict_premium_pool — the SQL form must agree with the in-memory one
# ---------------------------------------------------------------------------


def _pool(db_session, user):
    query = db_session.query(Question).join(Question.paper).join(Paper.level)
    return {q.paper_id for q in restrict_premium_pool(query, user).all()}


def test_pool_keeps_only_held_school_levels(
    db_session, sample_paper, primary_paper, premium_user
):
    """Secondary premium sees the Secondary paper, not the Primary one."""
    sample_paper.is_premium = True
    db_session.flush()
    assert _pool(db_session, premium_user) == {sample_paper.id}


def test_pool_for_user_holding_the_other_level(
    db_session, sample_paper, primary_paper, other_premium_user
):
    sample_paper.is_premium = True
    db_session.flush()
    assert _pool(db_session, other_premium_user) == {primary_paper.id}


def test_pool_keeps_free_papers_for_a_user_with_no_premium(
    db_session, sample_paper, primary_paper, public_user
):
    assert _pool(db_session, public_user) == {sample_paper.id}


def test_pool_unrestricted_for_admin(
    db_session, sample_paper, primary_paper, admin_user
):
    sample_paper.is_premium = True
    db_session.flush()
    assert _pool(db_session, admin_user) == {sample_paper.id, primary_paper.id}


def test_pool_and_gate_agree(db_session, sample_paper, primary_paper, premium_user):
    sample_paper.is_premium = True
    db_session.flush()
    gate = premium_gate(premium_user)
    in_memory = {
        p.id for p in db_session.query(Paper).all() if gate(p)
    }
    assert _pool(db_session, premium_user) == in_memory
