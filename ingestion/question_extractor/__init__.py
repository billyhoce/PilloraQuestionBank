"""Locate exam questions in digital-text PDF papers.

Public surface:

>>> from pathlib import Path
>>> from question_extractor import ExtractConfig, extract_paper
>>> result = extract_paper(Path("paper.pdf"), Path("output"), ExtractConfig())
>>> [(q.number, q.pages) for q in result.questions]        # doctest: +SKIP
[(1, [3]), (2, [3]), (3, [3])]

When the PDF handed in was itself carved out of a larger document, name that
document and the pages it came from, and every page number in the manifest is
addressable there as well as in the PDF processed:

>>> from question_extractor import SourceProvenance
>>> source = SourceProvenance(Path("whole_booklet.pdf"), {1: 7, 2: 8, 3: 9})
>>> extract_paper(                                         # doctest: +SKIP
...     Path("paper.pdf"), Path("output"), ExtractConfig(), provenance=source
... )

A table-format answer PDF is read into rows and grouped into questions instead,
digital or scanned, optionally told which columns hold the question numbers and
which way the answers read:

>>> from question_extractor import TableLayout, extract_table_paper
>>> tables = extract_table_paper(                          # doctest: +SKIP
...     Path("answers.pdf"), Path("output"), ExtractConfig(),
...     layout=TableLayout(question_columns=(0, 2), reading_order="across"),
... )
>>> [(q.number, q.pages) for q in tables.questions]        # doctest: +SKIP
[(1, [1, 1]), (2, [1]), (3, [1])]
"""

from __future__ import annotations

from .boundaries import Band, PageResult, Question
from .calibration import Calibration
from .config import ExtractConfig
from .pipeline import ExtractionError, PaperResult, extract_paper
from .provenance import SourceProvenance
from .tablepipeline import TablePaperResult, extract_table_paper
from .tables import ColumnPair, RowBand, TableLayout, TablePage

__all__ = [
    "Band",
    "Calibration",
    "ColumnPair",
    "ExtractConfig",
    "ExtractionError",
    "PageResult",
    "PaperResult",
    "Question",
    "RowBand",
    "SourceProvenance",
    "TableLayout",
    "TablePage",
    "TablePaperResult",
    "extract_paper",
    "extract_table_paper",
]

__version__ = "0.1.0"
