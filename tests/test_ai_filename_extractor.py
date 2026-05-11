"""Tests for the Claude filename-metadata extraction AI module."""
from unittest.mock import MagicMock, patch

import pytest

from app.ai.filename_extractor import (
    _EXTRACTION_TOOL,
    build_system_prompt,
    extract_metadata,
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
    return {
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
    ref_data = {"schools": [], "subjects": [], "levels": [], "exam_types": []}
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
    assert set(result.keys()) == {"school_id", "subject_id", "level_id", "exam_type_id", "year", "paper_number"}


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
