"""Tests for the Claude filename-metadata extraction AI module."""
from unittest.mock import MagicMock, patch

import pytest

from app.ai.filename_extractor import (
    _EXTRACTION_TOOL,
    build_system_prompt,
    extract_metadata,
    extract_paper_metadata,
    resolve_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ref_data():
    school = MagicMock(); school.name = "Raffles Institution"; school.id = 1
    subject = MagicMock(); subject.name = "Math"; subject.id = 2
    level = MagicMock(); level.name = "Sec 3"; level.id = 3
    exam_type = MagicMock(); exam_type.name = "EOY"; exam_type.id = 4
    stream = MagicMock(); stream.name = "Express"; stream.id = 5
    return {
        "streams": [stream],
        "schools": [school],
        "subjects": [subject],
        "levels": [level],
        "exam_types": [exam_type],
    }


def _make_mock_response(input_dict: dict):
    block = MagicMock()
    block.input = input_dict
    resp = MagicMock()
    resp.content = [block]
    # Real usage fields are ints; log_claude_call multiplies them out to a dollar
    # cost, so a bare MagicMock here would raise inside the logging call.
    resp.usage.input_tokens = 100
    resp.usage.output_tokens = 20
    resp.usage.cache_creation_input_tokens = 0
    resp.usage.cache_read_input_tokens = 0
    return resp


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------


def test_build_system_prompt_contains_school_names():
    prompt = build_system_prompt(_make_ref_data())
    assert "Raffles Institution" in prompt


def test_build_system_prompt_contains_subject_names():
    prompt = build_system_prompt(_make_ref_data())
    assert "Math" in prompt


def test_build_system_prompt_contains_level_names():
    prompt = build_system_prompt(_make_ref_data())
    assert "Sec 3" in prompt


def test_build_system_prompt_contains_exam_type_names():
    prompt = build_system_prompt(_make_ref_data())
    assert "EOY" in prompt


def test_build_system_prompt_empty_ref_data_shows_none():
    ref_data = {"schools": [], "subjects": [], "levels": [], "streams": [], "exam_types": []}
    prompt = build_system_prompt(ref_data)
    assert "(none)" in prompt


# ---------------------------------------------------------------------------
# resolve_metadata — exact case-insensitive lookup
# ---------------------------------------------------------------------------


def test_resolve_exact_match_all_fields():
    extracted = {
        "school": "Raffles Institution",
        "year": 2024,
        "subject": "Math",
        "level": "Sec 3",
        "exam_type": "EOY",
        "paper_number": "1",
    }
    result = resolve_metadata(extracted, _make_ref_data())
    assert result["school_id"] == 1
    assert result["subject_id"] == 2
    assert result["level_id"] == 3
    assert result["exam_type_id"] == 4
    assert result["year"] == 2024
    assert result["paper_number"] == "1"


def test_resolve_case_insensitive_match():
    extracted = {
        "school": "raffles institution",
        "year": 2024,
        "subject": "MATH",
        "level": "sec 3",
        "exam_type": "eoy",
        "paper_number": "1",
    }
    result = resolve_metadata(extracted, _make_ref_data())
    assert result["school_id"] == 1
    assert result["subject_id"] == 2
    assert result["level_id"] == 3
    assert result["exam_type_id"] == 4


def test_resolve_partial_name_returns_none():
    extracted = {
        "school": "Raffles",  # partial — no longer fuzzy-matched
        "year": None,
        "subject": None,
        "level": None,
        "exam_type": None,
        "paper_number": None,
    }
    result = resolve_metadata(extracted, _make_ref_data())
    assert result["school_id"] is None


def test_resolve_unknown_name_returns_none():
    extracted = {
        "school": "Unknown XYZ Academy",
        "year": 2024,
        "subject": None,
        "level": None,
        "exam_type": None,
        "paper_number": "1",
    }
    result = resolve_metadata(extracted, _make_ref_data())
    assert result["school_id"] is None


def test_resolve_null_fields_pass_through():
    extracted = {
        "school": None,
        "year": None,
        "subject": None,
        "level": None,
        "exam_type": None,
        "paper_number": None,
    }
    result = resolve_metadata(extracted, _make_ref_data())
    assert all(v is None for v in result.values())


def test_resolve_returns_required_keys():
    result = resolve_metadata(
        {"school": None, "year": None, "subject": None, "level": None,
         "exam_type": None, "paper_number": None},
        _make_ref_data(),
    )
    assert set(result.keys()) == {
        "school_id", "subject_id", "level_id", "stream_id", "exam_type_id", "year", "paper_number"
    }


def test_resolve_stream_case_insensitive_and_unknown():
    base = {"school": None, "year": None, "subject": None, "level": None, "exam_type": None, "paper_number": None}
    assert resolve_metadata({**base, "stream": "express"}, _make_ref_data())["stream_id"] == 5
    assert resolve_metadata({**base, "stream": "Normal (Tech)"}, _make_ref_data())["stream_id"] is None
    assert resolve_metadata(base, _make_ref_data())["stream_id"] is None


def test_system_prompt_lists_streams():
    assert "Express" in build_system_prompt(_make_ref_data())


def test_tool_schema_requires_stream():
    assert "stream" in _EXTRACTION_TOOL["input_schema"]["required"]


# ---------------------------------------------------------------------------
# extract_metadata — mocked Anthropic client
# ---------------------------------------------------------------------------


@patch("app.ai.filename_extractor._fetch_reference_data")
@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_extract_metadata_uses_haiku_model(mock_cls, mock_fetch):
    mock_fetch.return_value = _make_ref_data()
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(
        {"school": "Raffles Institution", "year": 2024, "subject": "Math",
         "level": "Sec 3", "exam_type": "EOY", "paper_number": "1"}
    )

    extract_metadata("RI_2024_Math_Sec3_EOY_P1.pdf", db=MagicMock())

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5-20251001"


@patch("app.ai.filename_extractor._fetch_reference_data")
@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_extract_metadata_uses_tool_choice(mock_cls, mock_fetch):
    mock_fetch.return_value = _make_ref_data()
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(
        {"school": None, "year": None, "subject": None,
         "level": None, "exam_type": None, "paper_number": None}
    )

    extract_metadata("scan001.pdf", db=MagicMock())

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "extract_paper_metadata"}
    assert kwargs["tools"] == [_EXTRACTION_TOOL]


@patch("app.ai.filename_extractor._fetch_reference_data")
@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_extract_metadata_no_image_blocks(mock_cls, mock_fetch):
    mock_fetch.return_value = _make_ref_data()
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(
        {"school": None, "year": None, "subject": None,
         "level": None, "exam_type": None, "paper_number": None}
    )

    extract_metadata("RI_2024_Math_Sec3_EOY_P1.pdf", db=MagicMock())

    kwargs = mock_client.messages.create.call_args.kwargs
    for msg in kwargs.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                assert block.get("type") != "image"


@patch("app.ai.filename_extractor._fetch_reference_data")
@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_extract_metadata_resolves_ids(mock_cls, mock_fetch):
    mock_fetch.return_value = _make_ref_data()
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(
        {"school": "Raffles Institution", "year": 2024, "subject": "Math",
         "level": "Sec 3", "exam_type": "EOY", "paper_number": "1"}
    )

    result = extract_metadata("RI_2024_Math_Sec3_EOY_P1.pdf", db=MagicMock())

    assert result["school_id"] == 1
    assert result["subject_id"] == 2
    assert result["year"] == 2024
    assert result["paper_number"] == "1"


@patch("app.ai.filename_extractor._fetch_reference_data")
@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_extract_metadata_api_error_returns_empty(mock_cls, mock_fetch):
    mock_fetch.return_value = _make_ref_data()
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("API error")

    result = extract_metadata("RI_2024_Math_Sec3_EOY_P1.pdf", db=MagicMock())

    assert isinstance(result, dict)
    assert all(v is None for v in result.values())


# ---------------------------------------------------------------------------
# extract_paper_metadata — the cover as a document block
# ---------------------------------------------------------------------------

_ALL_NULL = {"school": None, "year": None, "subject": None, "level": None,
             "stream": None, "exam_type": None, "paper_number": None}


@patch("app.ai.filename_extractor._fetch_reference_data")
@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_cover_is_sent_as_a_pdf_document_block_with_the_filename_hint(mock_cls, mock_fetch):
    mock_fetch.return_value = _make_ref_data()
    client = mock_cls.return_value
    client.messages.create.return_value = _make_mock_response(
        {**_ALL_NULL, "school": "Raffles Institution", "stream": "Express", "year": 2024}
    )

    result = extract_paper_metadata("RI_2024.pdf", db=MagicMock(), cover=b"%PDF-cover")

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] > 256
    doc, text = kwargs["messages"][0]["content"]
    assert doc["type"] == "document" and doc["source"]["media_type"] == "application/pdf"
    import base64
    assert base64.b64decode(doc["source"]["data"]) == b"%PDF-cover"
    assert "RI_2024.pdf" in text["text"]
    assert (result["school_id"], result["stream_id"], result["year"]) == (1, 5, 2024)


@patch("app.ai.filename_extractor._fetch_reference_data")
@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_without_a_cover_only_the_filename_is_sent(mock_cls, mock_fetch):
    mock_fetch.return_value = _make_ref_data()
    client = mock_cls.return_value
    client.messages.create.return_value = _make_mock_response(_ALL_NULL)
    extract_paper_metadata("scan.pdf", db=MagicMock())
    assert isinstance(client.messages.create.call_args.kwargs["messages"][0]["content"], str)


@patch("app.ai.filename_extractor._fetch_reference_data")
@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_a_failed_cover_call_is_retried_on_the_filename_alone(mock_cls, mock_fetch):
    mock_fetch.return_value = _make_ref_data()
    client = mock_cls.return_value
    client.messages.create.side_effect = [
        Exception("bad pdf"), _make_mock_response({**_ALL_NULL, "year": 2021}),
    ]
    result = extract_paper_metadata("RI_2021.pdf", db=MagicMock(), cover=b"%PDF")
    assert result["year"] == 2021
    assert isinstance(client.messages.create.call_args.kwargs["messages"][0]["content"], str)


# ---------------------------------------------------------------------------
# The raw names read are kept alongside the ids (#86)
# ---------------------------------------------------------------------------


@patch("app.ai.filename_extractor._fetch_reference_data")
@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_the_names_read_are_kept_even_when_they_do_not_resolve(mock_cls, mock_fetch):
    mock_fetch.return_value = _make_ref_data()
    mock_cls.return_value.messages.create.return_value = _make_mock_response(
        {**_ALL_NULL, "school": "Raffles Instn", "subject": "Math", "year": 2024}
    )

    result = extract_paper_metadata("RI_2024.pdf", db=MagicMock(), cover=b"%PDF")

    assert result["school_id"] is None and result["subject_id"] == 2
    assert result["extracted"] == {
        "school": "Raffles Instn", "subject": "Math", "level": None, "stream": None, "exam_type": None,
    }


@patch("app.ai.filename_extractor._fetch_reference_data")
@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_a_failed_extraction_keeps_no_names(mock_cls, mock_fetch):
    mock_fetch.return_value = _make_ref_data()
    mock_cls.return_value.messages.create.side_effect = Exception("API error")
    assert "extracted" not in extract_paper_metadata("x.pdf", db=MagicMock())


def test_the_school_may_be_read_as_printed_when_it_is_not_listed():
    assert "as printed" in _EXTRACTION_TOOL["input_schema"]["properties"]["school"]["description"]
