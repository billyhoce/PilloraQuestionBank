"""The only module that talks to the Messages API."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import IngestConfig
from .segments import READING_ORDERS, TEMPLATES, Segment

log = logging.getLogger(__name__)

SEGMENT_SYSTEM = """\
You are reading an exam paper PDF and reporting its structure, nothing else.

A PDF like this is a booklet. It holds one or more question papers, and often
each paper's answer paper behind them -- a marking scheme, worked solutions or a
bare answer key. Report each of those as one page range.

How to label a range:

- A question paper is `q1`, `q2`, ... and an answer paper is `a1`, `a2`, ...,
  numbering each kind from 1 in the order they appear in the PDF.
- An answer paper takes the index of the question paper it answers, so the
  marking scheme for `q2` is `a2`.

What a range covers:

- From the section's first page of content to its last page of content.
- Leave out the pages a section opens with that are not its content: the cover
  sheet, the instructions page, the formula sheet. Leave out blank padding
  printed after a section ends.
- Ranges must not overlap, and need not cover the whole PDF. Pages belonging to
  no section are simply left out.
- A blank page *inside* a section stays inside its range. So does a page
  carrying only an "End of Paper" marker, a page that is an empty graph grid,
  and a page left blank as working space -- all of these are part of the paper
  they are bound into.
- Report the ranges in the order they appear in the PDF.

Page numbers are 1-based positions in the PDF file. They are not the page
numbers printed on the pages: a booklet restarts its own numbering at each paper
and does not number its front matter.

Each answer paper takes one of two templates. Tell them apart by whether the
question text is present on its pages:

- `table`: the answers are tabulated -- question numbers and answers only, with
  no question text at all.
- `annotated_booklet`: a copy of the question booklet with the answers written
  into its blank space, so each page carries the question and its answer.

Give every answer paper `table` or `annotated_booklet`, or `unsure` if you cannot
tell confidently -- never guess. Give every question paper `none`.

For a `table` answer paper, also describe its columns:

- `question_columns`: the 0-based index of each printed column that holds the
  question numbers (`1`, `2(a)`, `5(iii)`), counting the table's columns from the
  left. Most tables have one such column, first: `[0]`. A sheet printing two
  question-and-answer column groups side by side has two, such as `[0, 2]`; a
  table whose columns are `No. | Part | Working | Marks` is `[0]`.
- `reading_order`: `down` when the answers run down one column group and then
  down the next, `across` when they run row by row across the groups. A table
  with a single column group reads `down`.

If you cannot tell, give `[]` and `none` -- never guess. For any section that is
not a `table` answer paper, give `[]` and `none`.

If the PDF holds no question or answer paper at all, report no ranges.
"""

TEMPLATE_UNSURE = "unsure"
TEMPLATE_NONE = "none"
READING_ORDER_NONE = "none"

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "q1, q2, a1, a2, ...",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["question", "answer"],
                    },
                    "index": {
                        "type": "integer",
                        "description": "1-based index within the kind",
                    },
                    "first_page": {
                        "type": "integer",
                        "description": "1-based first page of the range, inclusive",
                    },
                    "last_page": {
                        "type": "integer",
                        "description": "1-based last page of the range, inclusive",
                    },
                    "note": {
                        "type": "string",
                        "description": "one short line naming what this section is",
                    },
                    "template": {
                        "type": "string",
                        "enum": [*TEMPLATES, TEMPLATE_UNSURE, TEMPLATE_NONE],
                        "description": "answer papers only; `none` for a question paper",
                    },
                    "question_columns": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "table answer papers only: 0-based indices of the "
                            "columns holding question numbers; [] otherwise"
                        ),
                    },
                    "reading_order": {
                        "type": "string",
                        "enum": [*READING_ORDERS, READING_ORDER_NONE],
                        "description": "table answer papers only; `none` otherwise",
                    },
                },
                "required": [
                    "label",
                    "kind",
                    "index",
                    "first_page",
                    "last_page",
                    "note",
                    "template",
                    "question_columns",
                    "reading_order",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}
# `label` is a free string, not an enum, so validation can catch a label that
# disagrees with `kind`/`index` instead of the API hiding it. `question_columns`
# carries no length or range limits: structured outputs do not enforce them, so
# validation checks both.

_SEGMENT_KEYS = ("label", "kind", "index", "first_page", "last_page")


@dataclass(frozen=True)
class ModelAnswer:
    """A model's reply. ``error`` is set when the request itself failed."""

    model: str
    segments: tuple[Segment, ...] = ()
    error: str | None = None


def encode_pdf(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode("ascii")


def encoded_size(pdf_bytes: int) -> int:
    return 4 * ((pdf_bytes + 2) // 3)


def takes_budget_thinking(model: str, config: IngestConfig) -> bool:
    return model.startswith(config.legacy_thinking_prefixes)


def user_text(page_count: int) -> str:
    return (
        f"This PDF has {page_count} pages, numbered 1 to {page_count}.\n\n"
        "Report its question papers and answer papers as page ranges."
    )


def build_request(
    model: str, pdf_b64: str, page_count: int, config: IngestConfig
) -> dict:
    output_config: dict = {
        "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}
    }
    request: dict = {
        "model": model,
        "max_tokens": config.max_tokens,
        "system": SEGMENT_SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": user_text(page_count)},
                ],
            }
        ],
        "output_config": output_config,
    }

    if takes_budget_thinking(model, config):
        budget = config.thinking_budget_tokens
        if budget and budget >= config.max_tokens:
            # The API requires budget < max_tokens; drop thinking rather than 400.
            log.warning(
                "%s: thinking_budget_tokens (%d) is not below max_tokens (%d); "
                "sending no thinking block",
                model,
                budget,
                config.max_tokens,
            )
        elif budget:
            request["thinking"] = {"type": "enabled", "budget_tokens": budget}
    else:
        request["thinking"] = {"type": "adaptive"}
        output_config["effort"] = config.effort

    return request


def ask(model: str, pdf_b64: str, page_count: int, config: IngestConfig) -> ModelAnswer:
    try:
        import anthropic
    except ImportError:
        return ModelAnswer(
            model=model,
            error=(
                "the anthropic SDK is not installed, so no model can be asked "
                "(pip install anthropic)"
            ),
        )

    request = build_request(model, pdf_b64, page_count, config)
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(**request)
    except Exception as exc:  # the SDK's whole error tree, plus a missing key
        return ModelAnswer(model=model, error=f"{type(exc).__name__}: {exc}")

    if response.stop_reason == "refusal":
        return ModelAnswer(model=model, error="the request was refused by the model")
    if response.stop_reason == "max_tokens":
        return ModelAnswer(
            model=model,
            error=(
                f"the reply hit max_tokens ({config.max_tokens}) and its JSON is "
                f"truncated"
            ),
        )

    body = next((block.text for block in response.content if block.type == "text"), None)
    if body is None:
        return ModelAnswer(model=model, error="the reply carried no text block")
    return parse_answer(model, body)


def parse_answer(model: str, body: str) -> ModelAnswer:
    """Tolerates a body that breaks the schema: a failed answer, not a crash."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return ModelAnswer(model=model, error=f"the reply is not valid JSON: {exc}")

    if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
        return ModelAnswer(
            model=model, error="the reply has no 'segments' array at its top level"
        )

    segments: list[Segment] = []
    for position, item in enumerate(payload["segments"], 1):
        if not isinstance(item, dict):
            return ModelAnswer(
                model=model, error=f"segment {position} in the reply is not an object"
            )
        missing = [key for key in _SEGMENT_KEYS if key not in item]
        if missing:
            return ModelAnswer(
                model=model,
                error=f"segment {position} in the reply is missing {missing}",
            )
        columns = item.get("question_columns", [])
        if not isinstance(columns, list):
            return ModelAnswer(
                model=model,
                error=f"segment {position}'s question_columns is not an array",
            )
        segments.append(
            Segment(
                label=str(item["label"]),
                kind=str(item["kind"]),
                index=item["index"],
                first_page=item["first_page"],
                last_page=item["last_page"],
                note=str(item.get("note", "")),
                template=_template(item.get("template")),
                needs_review=item.get("template") == TEMPLATE_UNSURE,
                question_columns=tuple(columns),
                reading_order=_reading_order(item.get("reading_order")),
            )
        )

    return ModelAnswer(model=model, segments=tuple(segments))


def _template(value: object) -> str | None:
    """``unsure``/``none``/absent become no template; anything else is kept for
    validation to judge."""
    if value is None or value in (TEMPLATE_UNSURE, TEMPLATE_NONE):
        return None
    return str(value)


def _reading_order(value: object) -> str | None:
    """``none``/absent become no order; anything else is kept for validation."""
    if value is None or value == READING_ORDER_NONE:
        return None
    return str(value)
