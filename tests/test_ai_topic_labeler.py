"""Tests for the Claude topic-labeling AI module."""
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

import pytest

from app.ai.topic_labeler import (
    LABEL_PARTS_TOOL,
    TruncatedResponseError,
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


def test_label_parts_tool_schema_is_per_part():
    schema = LABEL_PARTS_TOOL["input_schema"]
    assert schema["required"] == ["parts"]
    part = schema["properties"]["parts"]["items"]
    assert set(part["required"]) == {"label", "selected_codes", "marks"}
    assert part["properties"]["marks"]["type"] == ["integer", "null"]


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


def _part(label="", selected_codes=(), marks=None):
    return {"label": label, "selected_codes": list(selected_codes), "marks": marks}


def _make_mock_response(parts, stop_reason="tool_use"):
    mock_resp = MagicMock()
    mock_resp.stop_reason = stop_reason
    mock_resp.content = [MagicMock()]
    mock_resp.content[0].input = {"parts": parts}
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
        created_at=datetime.now(UTC),
    )
    db_session.add(paper)
    db_session.flush()
    question = Question(paper_id=paper.id, question_number=1, created_at=datetime.now(UTC))
    db_session.add(question)
    db_session.flush()
    return paper, question


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_calls_messages_create_once(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([_part()])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    mock_client.messages.create.assert_called_once()


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_uses_haiku_model(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([_part()])

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
    mock_client.messages.create.return_value = _make_mock_response([_part()])

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
    mock_client.messages.create.return_value = _make_mock_response([_part()])

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
    mock_client.messages.create.return_value = _make_mock_response([_part()])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    call_kwargs = mock_client.messages.create.call_args.kwargs
    tool_choice = call_kwargs.get("tool_choice", {})
    assert tool_choice.get("type") == "tool"
    assert tool_choice.get("name") == "label_parts"
    tools = call_kwargs.get("tools", [])
    assert any(t.get("name") == "label_parts" for t in tools)


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_filters_out_hallucinated_codes(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([_part(selected_codes=["99.99"])])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    result = label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    assert result["parts"][0]["selections"] == [], "Hallucinated code '99.99' should be filtered out"
    assert result["parts"][0]["marks"] is None


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_returns_a_part_per_printed_part(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    # topic_number=1, one subtopic -> code is "1.1"
    mock_client.messages.create.return_value = _make_mock_response([
        _part(label="(a)(i)", selected_codes=["1.1"], marks=2),
        _part(label="(b)", selected_codes=[], marks=5),
    ])

    result = label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    assert result["parts"] == [
        {
            "label": "(a)(i)",
            "marks": 2,
            "selections": [{"topic_id": rd["topic"].id, "subtopic_id": rd["subtopic"].id}],
        },
        {"label": "(b)", "marks": 5, "selections": []},
    ]


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_dedupes_repeated_codes_within_a_part(mock_anthropic_cls, db_session, reference_data, admin_user):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    mock_client.messages.create.return_value = _make_mock_response([
        _part(label="(a)", selected_codes=["1.1", "1.1"]),
    ])

    result = label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    assert result["parts"][0]["selections"] == [
        {"topic_id": rd["topic"].id, "subtopic_id": rd["subtopic"].id}
    ]


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_keeps_the_same_subtopic_on_two_parts(mock_anthropic_cls, db_session, reference_data, admin_user):
    """Dedupe is per part — two parts may legitimately test the same subtopic."""
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    mock_client.messages.create.return_value = _make_mock_response([
        _part(label="(a)", selected_codes=["1.1"], marks=2),
        _part(label="(b)", selected_codes=["1.1"], marks=3),
    ])

    result = label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    expected = [{"topic_id": rd["topic"].id, "subtopic_id": rd["subtopic"].id}]
    assert result["parts"][0]["selections"] == expected
    assert result["parts"][1]["selections"] == expected


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_raises_when_the_response_is_truncated(mock_anthropic_cls, db_session, reference_data, admin_user):
    """A partial tool call must not pass for a complete split — a question cut
    off after two of its four parts would otherwise be saved as a two-part one."""
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    mock_client.messages.create.return_value = _make_mock_response(
        [_part(label="(a)", selected_codes=["1.1"], marks=2)], stop_reason="max_tokens"
    )

    with pytest.raises(TruncatedResponseError):
        label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])


@patch("app.ai.topic_labeler.anthropic.Anthropic")
def test_label_question_falls_back_to_one_blank_part(mock_anthropic_cls, db_session, reference_data, admin_user):
    """Every question has at least one part, even if the model returns none."""
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response([])

    rd = reference_data
    _, question = _make_paper_and_question(db_session, reference_data, admin_user)

    topics = _make_topics(rd["topic"].id, rd["subtopic"].id)
    result = label_question(question=question, topics=topics, image_bytes_list=[b"fake-image-bytes"])

    assert result["parts"] == [{"label": "", "marks": None, "selections": []}]


def test_system_prompt_spells_out_the_roman_numeral_split():
    """(a)(i)/(a)(ii)/(b) must be three parts, not two — this is the rule the
    model gets wrong without an explicit instruction."""
    options_str, _ = _build_options(
        [{"id": 1, "name": "Algebra", "topic_number": 1, "subtopics": []}]
    )
    prompt = build_system_prompt(subject="Math", stream="G3", options_str=options_str)
    assert "(a)(i)" in prompt and "(a)(ii)" in prompt
    assert "exactly three parts" in prompt


def test_system_prompt_forbids_summing_marks():
    options_str, _ = _build_options(
        [{"id": 1, "name": "Algebra", "topic_number": 1, "subtopics": []}]
    )
    prompt = build_system_prompt(subject="Math", stream="G3", options_str=options_str)
    assert "Do NOT sum marks" in prompt
    assert "first part" in prompt
