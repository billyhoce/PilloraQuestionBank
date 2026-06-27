"""Tests for the Claude topic-labeling AI module."""
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.ai.topic_labeler import (
    _build_options,
    build_system_prompt,
    label_question,
)


# ---------------------------------------------------------------------------
# Prompt / options construction
# ---------------------------------------------------------------------------


def _make_topics(topic_id, subtopic_id, topic_number=1):
    return [
        {
            "id": topic_id,
            "name": "Algebra",
            "topic_number": topic_number,
            "subtopics": [{"id": subtopic_id, "name": "Linear equations"}],
        }
    ]


def test_build_options_topic_with_subtopics_shows_only_subtopics():
    topics = [
        {
            "id": 1,
            "name": "Algebra",
            "topic_number": 1,
            "subtopics": [
                {"id": 11, "name": "Linear equations"},
                {"id": 12, "name": "Quadratic equations"},
            ],
        }
    ]
    options_str, code_map = _build_options(topics)
    assert "Algebra" in options_str
    assert "Linear equations" in options_str
    assert "Quadratic equations" in options_str
    # With subtopics, no bare "1" entry — only "1.1" and "1.2"
    assert "1" not in code_map
    assert "1.1" in code_map
    assert "1.2" in code_map
    assert code_map["1.1"] == (1, 11)
    assert code_map["1.2"] == (1, 12)


def test_build_options_topic_without_subtopics_shows_bare_line():
    topics = [
        {"id": 2, "name": "Differentiation", "topic_number": 2, "subtopics": []},
    ]
    options_str, code_map = _build_options(topics)
    assert "Differentiation" in options_str
    assert "2" in code_map
    assert code_map["2"] == (2, None)


def test_build_system_prompt_includes_all_topic_names():
    topics = [
        {"id": 1, "name": "Algebra", "topic_number": 1, "subtopics": []},
        {"id": 2, "name": "Geometry", "topic_number": 2, "subtopics": []},
    ]
    options_str, _ = _build_options(topics)
    prompt = build_system_prompt(subject="Math", stream="G3", options_str=options_str)
    assert "Algebra" in prompt
    assert "Geometry" in prompt


def test_build_system_prompt_includes_subtopics():
    topics = [
        {
            "id": 1,
            "name": "Algebra",
            "topic_number": 1,
            "subtopics": [
                {"id": 11, "name": "Linear equations"},
                {"id": 12, "name": "Quadratic equations"},
            ],
        }
    ]
    options_str, _ = _build_options(topics)
    prompt = build_system_prompt(subject="Math", stream="G3", options_str=options_str)
    assert "Linear equations" in prompt
    assert "Quadratic equations" in prompt


def test_build_system_prompt_includes_positional_codes():
    topics = [
        {
            "id": 1,
            "name": "Algebra",
            "topic_number": 1,
            "subtopics": [{"id": 42, "name": "Linear equations"}],
        }
    ]
    options_str, _ = _build_options(topics)
    # The code "1.1" (not the subtopic DB id) should appear in the options
    assert "1.1" in options_str
    prompt = build_system_prompt(subject="Math", stream="G3", options_str=options_str)
    assert "1.1" in prompt


# ---------------------------------------------------------------------------
# API call (mocked Anthropic client)
# ---------------------------------------------------------------------------


def _make_mock_response(selected_codes: list):
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock()]
    mock_resp.content[0].input = {"selected_codes": selected_codes}
    mock_resp.usage.input_tokens = 100
    mock_resp.usage.output_tokens = 20
    mock_resp.usage.cache_creation_input_tokens = 0
    mock_resp.usage.cache_read_input_tokens = 0
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

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    mock_client.messages.create.assert_called_once()


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_uses_haiku_model(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs.get("model") == "claude-haiku-4-5-20251001"


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_sends_image_in_user_message(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

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

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

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

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    call_kwargs = mock_client.messages.create.call_args.kwargs
    tool_choice = call_kwargs.get("tool_choice", {})
    assert tool_choice.get("type") == "tool"
    assert tool_choice.get("name") == "label_topics"
    tools = call_kwargs.get("tools", [])
    assert any(t.get("name") == "label_topics" for t in tools)


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_filters_out_hallucinated_codes(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(["99.99"])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    result = label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    assert result == [], "Hallucinated code '99.99' should be filtered out"


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_returns_valid_selection(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    # topic_number=1, one subtopic → code is "1.1"
    mock_client.messages.create.return_value = _make_mock_response(["1.1"])

    result = label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    assert result == [{"topic_id": rd["topic"].id, "subtopic_id": rd["subtopic"].id}]


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_dedupes_repeated_codes(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    mock_client.messages.create.return_value = _make_mock_response(["1.1", "1.1"])

    result = label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    assert result == [{"topic_id": rd["topic"].id, "subtopic_id": rd["subtopic"].id}]
