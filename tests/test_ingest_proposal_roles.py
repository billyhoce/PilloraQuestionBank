"""The pipeline's ``report`` stage over committed sample booklets (offline: their
``*.segments.json`` fixtures stand in for the model call): paper roles, answer-only papers that
keep their question numbers, and the question-only warning. Also the app's review/confirm rules
for an ``answer_only`` paper."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parent.parent / "ingestion" / "samples"


def run_pipeline(tmp_path: Path, pdf: Path) -> dict:
    src = tmp_path / "in"
    src.mkdir()
    for f in pdf.parent.glob(pdf.stem + ".*"):
        shutil.copy(f, src / f.name)
    out = tmp_path / "out"
    subprocess.run(
        [sys.executable, "-m", "pipeline", "ingest", str(src), "--output-dir", str(out)],
        cwd=SAMPLES.parent, check=True, capture_output=True, timeout=300,
    )
    return json.loads((out / pdf.stem / "proposal.json").read_text())


@pytest.fixture(scope="module")
def answer_only(tmp_path_factory):
    return run_pipeline(tmp_path_factory.mktemp("answer_only"), SAMPLES / "answer_tables" / "two_pairs_column_break.pdf")


@pytest.fixture(scope="module")
def question_only(tmp_path_factory):
    return run_pipeline(tmp_path_factory.mktemp("question_only"), SAMPLES / "s4_a_math" / "standard.pdf")


@pytest.fixture(scope="module")
def paired(tmp_path_factory):
    return run_pipeline(tmp_path_factory.mktemp("paired"), SAMPLES / "s4_a_math" / "2024 S2 M WA1 Nan Hua.pdf")


def test_answer_only_paper_keeps_question_numbers(answer_only):
    (paper,) = answer_only["papers"]
    assert paper["role"] == "answer_only" and paper["label"] is None and paper["answer_label"] == "a1"
    assert paper["orphan_answers"] == []
    numbers = [q["number"] for q in paper["questions"]]
    assert numbers == sorted(set(numbers)) and len(numbers) > 1
    assert all(q["question_rects"] == [] and q["answer_rects"] for q in paper["questions"])


def test_question_only_booklet_is_flagged(question_only):
    (paper,) = question_only["papers"]
    assert paper["role"] == "question"
    assert any("no answer section" in w for w in paper["warnings"])
    assert any("no answer section" in w for w in question_only["warnings"])


def test_paired_paper_is_a_question_paper_without_the_warning(paired):
    (paper,) = paired["papers"]
    assert paper["role"] == "question"
    assert not any("no answer section" in w for w in paper["warnings"] + paired["warnings"])
    assert all(q["question_rects"] for q in paper["questions"])
