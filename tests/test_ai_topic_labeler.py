"""Tests for the Claude topic-labeling AI module."""
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.ai.topic_labeler import (
    build_system_prompt,
    label_question,
)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_build_system_prompt_includes_all_topic_names():
    topics = [
        {"id": 1, "name": "Algebra", "subtopics": []},
        {"id": 2, "name": "Geometry", "subtopics": []},
    ]
    prompt = build_system_prompt(subject="Math", stream="G3", topics=topics)
    assert "Algebra" in prompt
    assert "Geometry" in prompt


def test_build_system_prompt_includes_subtopics():
    topics = [
        {
            "id": 1,
            "name": "Algebra",
            "subtopics": [
                {"id": 11, "name": "Linear equations"},
                {"id": 12, "name": "Quadratic equations"},
            ],
        }
    ]
    prompt = build_system_prompt(subject="Math", stream="G3", topics=topics)
    assert "Linear equations" in prompt
    assert "Quadratic equations" in prompt


def test_build_system_prompt_includes_subtopic_ids():
    topics = [
        {
            "id": 1,
            "name": "Algebra",
            "subtopics": [{"id": 42, "name": "Linear equations"}],
        }
    ]
    prompt = build_system_prompt(subject="Math", stream="G3", topics=topics)
    assert "42" in prompt


# ---------------------------------------------------------------------------
# API call (mocked Anthropic client)
# ---------------------------------------------------------------------------


def _make_mock_response(subtopic_ids: list):
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock()]
    mock_resp.content[0].input = {"subtopic_ids": subtopic_ids}
    return mock_resp


def _make_paper_and_question(db_session, reference_data, admin_user):
    from app.models.orm import Question, Paper

    rd = reference_data
    paper = Paper(
        subject_id=rd["subject"].id,
        stream_id=rd["stream"].id,
        level_id=rd["level"].id,
        school_id=rd["school"].id,
        exam_type_id=rd["exam_type"].id,
        year=2024,
        paper_number="1",
        created_by=admin_user.id,
        created_at=datetime.utcnow(),
    )
    db_session.add(paper)
    db_session.flush()
    question = Question(paper_id=paper.id, question_number=1, marks=5, created_at=datetime.utcnow())
    db_session.add(question)
    db_session.flush()
    return paper, question


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_calls_messages_create_once(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": [{"id": rd["subtopic"].id, "name": "Linear Equations"}]}]

    label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
    )

    mock_client.messages.create.assert_called_once()


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_uses_sonnet_model(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": [{"id": rd["subtopic"].id, "name": "Linear"}]}]
    label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
    )

    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs.get("model") == "claude-sonnet-4-6" or (
        call_kwargs.args and call_kwargs.args[0] == "claude-sonnet-4-6"
    )


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_sends_image_in_user_message(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": [{"id": rd["subtopic"].id, "name": "Linear"}]}]
    label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
    )

    call_kwargs = mock_client.messages.create.call_args.kwargs
    messages = call_kwargs.get("messages", [])
    user_content = next(
        (m["content"] for m in messages if m.get("role") == "user"),
        None,
    )
    assert user_content is not None
    types = [block.get("type") for block in user_content if isinstance(block, dict)]
    assert "image" in types


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_system_has_cache_control_ephemeral(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": [{"id": rd["subtopic"].id, "name": "Linear"}]}]
    label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
    )

    call_kwargs = mock_client.messages.create.call_args.kwargs
    system = call_kwargs.get("system", [])
    has_ephemeral = any(
        (block.get("cache_control", {}) or {}).get("type") == "ephemeral"
        for block in system
        if isinstance(block, dict)
    )
    assert has_ephemeral, "System prompt must include cache_control: {type: ephemeral}"


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_uses_tool_choice(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": [{"id": rd["subtopic"].id, "name": "Linear"}]}]
    label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
    )

    call_kwargs = mock_client.messages.create.call_args.kwargs
    tool_choice = call_kwargs.get("tool_choice", {})
    assert tool_choice.get("type") == "tool"
    assert tool_choice.get("name") == "label_subtopics"
    tools = call_kwargs.get("tools", [])
    assert any(t.get("name") == "label_subtopics" for t in tools)


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_filters_out_hallucinated_subtopic_ids(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([99999])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": [{"id": rd["subtopic"].id, "name": "Linear"}]}]
    result = label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
    )

    assert result == [], "Hallucinated subtopic_id 99999 should be filtered out"


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_returns_valid_subtopic(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": [{"id": rd["subtopic"].id, "name": "Linear Equations"}]}]
    mock_client.messages.create.return_value = _make_mock_response([rd["subtopic"].id])

    result = label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
    )

    assert result == [{"subtopic_id": rd["subtopic"].id}]


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_dedupes_repeated_subtopic_ids(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": [{"id": rd["subtopic"].id, "name": "Linear Equations"}]}]
    mock_client.messages.create.return_value = _make_mock_response([rd["subtopic"].id, rd["subtopic"].id])

    result = label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
    )

    assert result == [{"subtopic_id": rd["subtopic"].id}]
