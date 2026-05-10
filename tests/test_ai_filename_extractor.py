"""Tests for the Claude filename-metadata extraction AI module."""
from unittest.mock import MagicMock, patch

import pytest

from app.ai.filename_extractor import (
    build_filename_prompt,
    extract_metadata,
    parse_filename_response,
    resolve_metadata,
)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_build_filename_prompt_includes_filename():
    prompt = build_filename_prompt("RI_2024_Math_Sec3_EOY_P1.pdf")
    assert "RI_2024_Math_Sec3_EOY_P1.pdf" in prompt


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_filename_response_full_fields():
    raw = (
        '{"school": "Raffles Institution", "year": 2024, "subject": "Math",'
        ' "level": "Sec 3", "exam_type": "EOY", "paper_number": "1"}'
    )
    result = parse_filename_response(raw)
    assert result["school"] == "Raffles Institution"
    assert result["year"] == 2024
    assert result["subject"] == "Math"
    assert result["level"] == "Sec 3"
    assert result["exam_type"] == "EOY"
    assert result["paper_number"] == "1"


def test_parse_filename_response_partial_fields_nulls():
    raw = '{"school": "Raffles", "year": null, "subject": null, "level": "Sec 3", "exam_type": "EOY", "paper_number": "1"}'
    result = parse_filename_response(raw)
    assert result["year"] is None
    assert result["subject"] is None
    assert result["school"] == "Raffles"


def test_parse_filename_response_invalid_json():
    result = parse_filename_response("INVALID JSON")
    assert all(v is None for v in result.values())


# ---------------------------------------------------------------------------
# Fuzzy matching — resolve_metadata maps names to DB IDs
# ---------------------------------------------------------------------------


def test_fuzzy_match_school_exact_name(db_session, reference_data):
    extracted = {"school": "Raffles Institution", "year": 2024, "subject": None,
                 "level": None, "exam_type": None, "paper_number": "1"}
    resolved = resolve_metadata(extracted, db=db_session)
    assert resolved["school_id"] == reference_data["school"].id


def test_fuzzy_match_school_partial_name(db_session, reference_data):
    extracted = {"school": "Raffles", "year": 2024, "subject": None,
                 "level": None, "exam_type": None, "paper_number": "1"}
    resolved = resolve_metadata(extracted, db=db_session)
    assert resolved["school_id"] == reference_data["school"].id


def test_fuzzy_match_school_no_match_returns_none(db_session, reference_data):
    extracted = {"school": "Unknown XYZ Academy", "year": 2024, "subject": None,
                 "level": None, "exam_type": None, "paper_number": "1"}
    resolved = resolve_metadata(extracted, db=db_session)
    assert resolved["school_id"] is None


def test_fuzzy_match_subject_case_insensitive(db_session, reference_data):
    extracted = {"school": None, "year": 2024, "subject": "math",
                 "level": None, "exam_type": None, "paper_number": "1"}
    resolved = resolve_metadata(extracted, db=db_session)
    assert resolved["subject_id"] == reference_data["subject"].id


def test_fuzzy_match_exam_type_abbreviation(db_session, reference_data):
    # "EOY" should match "EOY" exactly (or "End-of-Year" depending on DB seeding)
    extracted = {"school": None, "year": 2024, "subject": None,
                 "level": None, "exam_type": "EOY", "paper_number": "1"}
    resolved = resolve_metadata(extracted, db=db_session)
    assert resolved["exam_type_id"] == reference_data["exam_type"].id


def test_resolve_metadata_returns_ids_dict(db_session, reference_data):
    rd = reference_data
    extracted = {
        "school": "Raffles Institution",
        "year": 2024,
        "subject": "Math",
        "level": "Sec 3",
        "exam_type": "EOY",
        "paper_number": "1",
    }
    resolved = resolve_metadata(extracted, db=db_session)
    assert "school_id" in resolved
    assert "subject_id" in resolved
    assert "level_id" in resolved
    assert "exam_type_id" in resolved
    assert "year" in resolved
    assert "paper_number" in resolved


# ---------------------------------------------------------------------------
# API call (mocked Anthropic client)
# ---------------------------------------------------------------------------


def _make_mock_response(text: str):
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock()]
    mock_resp.content[0].text = text
    return mock_resp


_VALID_FILENAME_RESPONSE = (
    '{"school": "Raffles Institution", "year": 2024, "subject": "Math",'
    ' "level": "Sec 3", "exam_type": "EOY", "paper_number": "1"}'
)


@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_extract_filename_calls_haiku_model(mock_anthropic_cls, db_session):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(_VALID_FILENAME_RESPONSE)

    extract_metadata("RI_2024_Math_Sec3_EOY_P1.pdf", db=db_session)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs.get("model") == "claude-haiku-4-5-20251001"


@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_extract_filename_text_only_no_image_blocks(mock_anthropic_cls, db_session):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(_VALID_FILENAME_RESPONSE)

    extract_metadata("RI_2024_Math_Sec3_EOY_P1.pdf", db=db_session)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    messages = call_kwargs.get("messages", [])
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                assert block.get("type") != "image", "Filename extractor must not send image blocks"


@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_extract_filename_returns_parsed_metadata_dict(mock_anthropic_cls, db_session):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response(_VALID_FILENAME_RESPONSE)

    result = extract_metadata("RI_2024_Math_Sec3_EOY_P1.pdf", db=db_session)

    assert isinstance(result, dict)
    assert "school_id" in result or "school" in result


@patch("app.ai.filename_extractor.anthropic.Anthropic")
def test_extract_filename_api_error_returns_empty_dict(mock_anthropic_cls, db_session):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("API error")

    result = extract_metadata("RI_2024_Math_Sec3_EOY_P1.pdf", db=db_session)

    assert isinstance(result, dict)
    # All resolved IDs should be None on failure
    assert all(v is None for v in result.values())
