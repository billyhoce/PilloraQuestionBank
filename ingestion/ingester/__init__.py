"""Split an exam-paper booklet PDF into its question and answer papers.

See ingester/README.md.
"""

from __future__ import annotations

from .config import IngestConfig
from .request import ModelAnswer
from .router import IngestResult, Route, SectionReport, choose_route, ingest_paper
from .segmenter import find_plan, fixture_path, segment_into, segment_paper, too_large_to_ask
from .segments import (
    SEGMENTS_NAME,
    TEMPLATES,
    Attempt,
    Segment,
    SegmentPlan,
    format_label,
    parse_label,
    read_plan,
    write_plan,
)
from .splitter import Section, SplitResult, split_into, split_paper
from .validation import anomalies, validate

__all__ = [
    "SEGMENTS_NAME",
    "TEMPLATES",
    "Attempt",
    "IngestConfig",
    "IngestResult",
    "ModelAnswer",
    "Route",
    "Segment",
    "SegmentPlan",
    "Section",
    "SectionReport",
    "SplitResult",
    "anomalies",
    "choose_route",
    "find_plan",
    "fixture_path",
    "format_label",
    "ingest_paper",
    "parse_label",
    "read_plan",
    "segment_into",
    "segment_paper",
    "split_into",
    "split_paper",
    "too_large_to_ask",
    "validate",
    "write_plan",
]

__version__ = "0.1.0"
