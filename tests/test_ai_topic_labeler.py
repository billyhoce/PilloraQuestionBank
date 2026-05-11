"""Tests for the Claude topic-labeling AI module."""
from unittest.mock import MagicMock, patch

import pytest

from app.ai.topic_labeler import (
    build_system_prompt,
    label_question,
    parse_label_response,
)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_build_system_prompt_includes_subject_and_stream():
    prompt = build_system_prompt(subject="Math", stream="G3", topics=[])
    assert "Math" in prompt
    assert "G3" in prompt


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


def test_build_system_prompt_has_json_schema_instructions():
    prompt = build_system_prompt(subject="Math", stream="G3", topics=[])
    # The prompt must instruct the model to return JSON with a "topics" key
    assert "topics" in prompt
    assert "JSON" in prompt or "json" in prompt


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_label_response_valid_json():
    raw = '{"topics": [{"topic_id": 1, "subtopic_id": 11}]}'
    result = parse_label_response(raw, valid_topic_ids={1})
    assert result == [{"topic_id": 1, "subtopic_id": 11}]


def test_parse_label_response_multiple_topics():
    raw = '{"topics": [{"topic_id": 1, "subtopic_id": 11}, {"topic_id": 2, "subtopic_id": null}]}'
    result = parse_label_response(raw, valid_topic_ids={1, 2})
    assert len(result) == 2


def test_parse_label_response_null_subtopic():
    raw = '{"topics": [{"topic_id": 1, "subtopic_id": null}]}'
    result = parse_label_response(raw, valid_topic_ids={1})
    assert result[0]["subtopic_id"] is None


def test_parse_label_response_invalid_json_returns_empty():
    result = parse_label_response("Not JSON at all", valid_topic_ids={1})
    assert result == []


def test_parse_label_response_missing_topics_key_returns_empty():
    raw = '{"result": []}'
    result = parse_label_response(raw, valid_topic_ids={1})
    assert result == []


def test_parse_label_response_strips_markdown_code_fences():
    raw = "```json\n{\"topics\": [{\"topic_id\": 1, \"subtopic_id\": null}]}\n```"
    result = parse_label_response(raw, valid_topic_ids={1})
    assert len(result) == 1
    assert result[0]["topic_id"] == 1


def test_parse_label_response_filters_hallucinated_topic_ids():
    raw = '{"topics": [{"topic_id": 999, "subtopic_id": null}]}'
    result = parse_label_response(raw, valid_topic_ids={1, 2})
    assert result == []


# ---------------------------------------------------------------------------
# API call (mocked Anthropic client)
# ---------------------------------------------------------------------------


def _make_mock_response(content_text: str):
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock()]
    mock_resp.content[0].text = content_text
    return mock_resp


_VALID_RESPONSE = '{"topics": [{"topic_id": 1, "subtopic_id": 11}]}'


def _make_paper_and_question(db_session, reference_data, admin_user):
    from app.models.orm import Question, Paper
    from datetime import datetime

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
    mock_client.messages.create.return_value = _make_mock_response(_VALID_RESPONSE)

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": [{"id": rd["subtopic"].id, "name": "Linear Equations"}]}]

    label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
        db=db_session,
    )

    mock_client.messages.create.assert_called_once()


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_uses_sonnet_model(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(_VALID_RESPONSE)

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": []}]
    label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
        db=db_session,
    )

    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs.get("model") == "claude-sonnet-4-6" or (
        call_kwargs.args and call_kwargs.args[0] == "claude-sonnet-4-6"
    )


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_sends_image_in_user_message(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(_VALID_RESPONSE)

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": []}]
    label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
        db=db_session,
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
    mock_client.messages.create.return_value = _make_mock_response(_VALID_RESPONSE)

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": []}]
    label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
        db=db_session,
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
def test_label_question_filters_out_hallucinated_topic_ids(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    # Claude returns a topic_id not in the valid set
    mock_client.messages.create.return_value = _make_mock_response(
        '{"topics": [{"topic_id": 999, "subtopic_id": null}]}'
    )

    from app.models.orm import QuestionTopic

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = [{"id": rd["topic"].id, "name": "Algebra", "subtopics": []}]
    label_question(
        question=question,
        topics=topics,
        image_bytes_list=[b"fake-image-bytes"],
        db=db_session,
    )

    count = db_session.query(QuestionTopic).filter_by(question_id=question.id).count()
    assert count == 0, "Hallucinated topic_id 999 should not be persisted"
