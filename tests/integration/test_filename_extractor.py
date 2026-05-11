"""Integration tests — real Anthropic API calls."""
import pytest

from app.ai.filename_extractor import extract_metadata


def test_informative_filename_resolves_ids(db_session, reference_data):
    """Explicit filename: all fields should resolve to the correct DB IDs."""
    rd = reference_data
    result = extract_metadata("Raffles Institution 2024 Math Sec 3 EOY P1.pdf", db=db_session)

    assert set(result.keys()) == {"school_id", "subject_id", "level_id", "exam_type_id", "year", "paper_number"}
    assert result["school_id"] == rd["school"].id
    assert result["subject_id"] == rd["subject"].id
    assert result["level_id"] == rd["level"].id
    assert result["exam_type_id"] == rd["exam_type"].id
    assert result["year"] == 2024
    assert result["paper_number"] == "1"


def test_generic_filename_returns_all_none(db_session, reference_data):
    """Generic filename: all fields should be null."""
    result = extract_metadata("scan001.pdf", db=db_session)

    assert result["school_id"] is None
    assert result["subject_id"] is None
    assert result["level_id"] is None
    assert result["exam_type_id"] is None
    assert result["year"] is None
    assert result["paper_number"] is None


def test_partial_filename_extracts_year_and_paper(db_session, reference_data):
    """Partial filename: only year and paper number should be extracted."""
    result = extract_metadata("2024_P2.pdf", db=db_session)

    assert result["year"] == 2024
    assert result["paper_number"] == "2"
    assert result["school_id"] is None
