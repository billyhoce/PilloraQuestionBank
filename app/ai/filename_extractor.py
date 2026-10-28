import base64

import anthropic

from app.ai.job_cost import record_usage
from app.logger import Timer, log
from app.models.orm import ExamType, Level, School, Stream, Subject

_EMPTY: dict = {
    "school_id": None,
    "subject_id": None,
    "level_id": None,
    "stream_id": None,
    "exam_type_id": None,
    "year": None,
    "paper_number": None,
}

# ── Add few-shot examples here ───────────────────────────────────────────────
# Format each example as plain text, e.g.:
#
#   Filename: "RI_2024_EMath_Sec4_Prelim_P1.pdf"
#   → school="Raffles Institution", year=2024, subject="E Math",
#     level="Sec 4", exam_type="Preliminary Examination", paper_number="1"
#
#   Filename: "scan001.pdf"
#   → all fields null (generic name carries no metadata)
# ─────────────────────────────────────────────────────────────────────────────
_EXAMPLES: str = (
    "'2024 S3 EM WA2 CGS - P1' should be parsed as "
    "school='Crescent Girls School', year=2024, subject='E Math', level='Secondary 3', exam_type='WA2', paper_number=1\n"
    "Explanation: '2024' matches the year format; 'S3' maps to 'Sec 3' level; 'EM' is a common abbreviation for 'E Math'; "
    "'WA2' matches the exam type; 'P1' is an abbreviation for 'Paper 1'.\n\n"
    "'ANDSS 4E2024EM' should be parsed as "
    "school='Anderson Secondary School', year=2024, subject='E Math', level='Secondary 4', exam_type=null, paper_number=null\n"
    "Explanation: 'ANDSS' is a abbreviation for 'Anderson Secondary School'; '4E' indicates 'Secondary 4' and 'Express' stream; "
)

_EXTRACTION_TOOL: dict = {
    "name": "extract_paper_metadata",
    "description": (
        "Extract structured metadata from a Singapore secondary school "
        "exam paper: its cover page when one is attached, and its filename. "
        "Return null for any field that cannot be determined."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "school": {
                "type": ["string", "null"],
                "description": (
                    "School name exactly as listed in Available Schools. If the paper names a school "
                    "that is not in the list, give the name as printed instead; null if none is named."
                ),
            },
            "year": {
                "type": ["integer", "null"],
                "description": "4-digit exam year (e.g. 2024), or null.",
            },
            "subject": {
                "type": ["string", "null"],
                "description": "Subject name exactly as listed in Available Subjects, or null.",
            },
            "level": {
                "type": ["string", "null"],
                "description": "Level name exactly as listed in Available Levels, or null.",
            },
            "stream": {
                "type": ["string", "null"],
                "description": "Stream name exactly as listed in Available Streams, or null.",
            },
            "exam_type": {
                "type": ["string", "null"],
                "description": "Exam type exactly as listed in Available Exam Types, or null.",
            },
            "paper_number": {
                "type": ["string", "null"],
                "description": "Paper number string (e.g. '1', '2'), or null.",
            },
        },
        "required": ["school", "year", "subject", "level", "stream", "exam_type", "paper_number"],
    },
}


def _fetch_reference_data(db) -> dict:
    return {
        "schools": db.query(School).all(),
        "subjects": db.query(Subject).all(),
        "levels": db.query(Level).all(),
        "streams": db.query(Stream).all(),
        "exam_types": db.query(ExamType).all(),
    }


def build_system_prompt(ref_data: dict) -> str:
    schools_str    = "\n".join(f"  - {s.name}" for s in ref_data["schools"])    or "  (none)"
    subjects_str   = "\n".join(f"  - {s.name}" for s in ref_data["subjects"])   or "  (none)"
    levels_str     = "\n".join(f"  - {l.name}" for l in ref_data["levels"])     or "  (none)"
    streams_str    = "\n".join(f"  - {s.name}" for s in ref_data.get("streams", [])) or "  (none)"
    exam_types_str = "\n".join(f"  - {e.name}" for e in ref_data["exam_types"]) or "  (none)"

    examples_section = (
        f"\n## Examples\n{_EXAMPLES.strip()}\n" if _EXAMPLES.strip() else ""
    )

    return (
        "You are a metadata extractor for Singapore exam papers. You are given the paper's "
        "filename and, usually, its cover page(s) as a PDF document. The cover page is the "
        "better evidence: school, subject, level, stream, exam type, year and paper number are "
        "normally printed on it. Use the filename as a hint, and to fill what the cover does not say.\n\n"
        "Filenames vary widely: some encode rich metadata "
        "(e.g. 'RI_2024_EMath_Sec4_Prelim_P1.pdf'), while others are completely "
        "generic (e.g. 'scan001.pdf', 'document.pdf'). "
        "Do not guess — return null for any field you are not confident about.\n\n"
        "You MUST pick values exclusively from the lists below. "
        "If a filename token does not closely match an entry in the list, return null for that field.\n\n"
        f"## Available Schools\n{schools_str}\n\n"
        f"## Available Subjects\n{subjects_str}\n\n"
        f"## Available Levels\n{levels_str}\n\n"
        f"## Available Streams\n{streams_str}\n\n"
        f"## Available Exam Types\n{exam_types_str}"
        f"{examples_section}"
    )


def resolve_metadata(extracted: dict, ref_data: dict) -> dict:
    result = dict(_EMPTY)
    result["year"] = extracted.get("year")
    result["paper_number"] = extracted.get("paper_number")

    school_map    = {s.name.lower(): s.id for s in ref_data["schools"]}
    subject_map   = {s.name.lower(): s.id for s in ref_data["subjects"]}
    level_map     = {l.name.lower(): l.id for l in ref_data["levels"]}
    exam_type_map = {e.name.lower(): e.id for e in ref_data["exam_types"]}
    stream_map    = {s.name.lower(): s.id for s in ref_data.get("streams", [])}

    if extracted.get("school"):
        result["school_id"] = school_map.get(extracted["school"].lower())
    if extracted.get("subject"):
        result["subject_id"] = subject_map.get(extracted["subject"].lower())
    if extracted.get("level"):
        result["level_id"] = level_map.get(extracted["level"].lower())
    if extracted.get("stream"):
        result["stream_id"] = stream_map.get(extracted["stream"].lower())
    if extracted.get("exam_type"):
        result["exam_type_id"] = exam_type_map.get(extracted["exam_type"].lower())

    return result


# The names whose raw text is kept beside the resolved ids (``extracted``), so a name that matched
# nothing in the reference lists (e.g. "Raffles Instn") is still shown to the admin at review.
EXTRACTED_NAMES = ("school", "subject", "level", "stream", "exam_type")


def _raw_names(extracted: dict) -> dict:
    return {k: (extracted.get(k) or None) for k in EXTRACTED_NAMES}


MODEL = "claude-haiku-4-5-20251001"
# The tool result is a handful of short fields; 256 truncated it once ``stream`` was added.
MAX_TOKENS = 512


def _user_content(filename: str, cover: bytes | None) -> str | list:
    """The user turn: the cover pages as a ``document`` block (when given) and the filename hint."""
    if cover is None:
        return f'Extract metadata from this exam paper filename: "{filename}"'
    return [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(cover).decode("ascii"),
            },
        },
        {
            "type": "text",
            "text": (
                "Extract metadata from this exam paper's cover page (attached). "
                f'Its filename, as a hint, is: "{filename}"'
            ),
        },
    ]


def _call(client, ref_data: dict, filename: str, cover: bytes | None) -> dict:
    with Timer() as t_call:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=build_system_prompt(ref_data),
            tools=[_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_paper_metadata"},
            messages=[{"role": "user", "content": _user_content(filename, cover)}],
        )
    tool_input = resp.content[0].input  # dict, no JSON parsing needed
    record_usage(
        "read paper metadata from the cover" if cover is not None else "read paper metadata from the filename",
        MODEL, resp.usage, getattr(resp, "_request_id", None),
        reply=tool_input, seconds=t_call.s, stop_reason=resp.stop_reason,
    )
    return tool_input


def extract_paper_metadata(filename: str, db, cover: bytes | None = None) -> dict:
    """The paper's metadata, resolved to reference-data ids, plus ``extracted``: the raw names read
    (school, subject, level, stream, exam type; each null when none was read), resolved or not.

    ``cover`` is a PDF of the paper's cover pages (or, without any, its first page); the filename
    stays as a hint, and is all there is when ``cover`` is ``None``. A failed call with a cover is
    retried once on the filename alone; a failure there gives empty metadata (no ``extracted``).
    Never raises.
    """
    try:
        ref_data = _fetch_reference_data(db)
        client = anthropic.Anthropic()
        try:
            extracted = _call(client, ref_data, filename, cover)
        except Exception as e:
            if cover is None:
                raise
            log.warning("reading metadata from the cover failed (%s: %s); retrying on the filename alone",
                        type(e).__name__, e)
            extracted = _call(client, ref_data, filename, None)
        return {**resolve_metadata(extracted, ref_data), "extracted": _raw_names(extracted)}
    except Exception as e:
        log.warning("could not read paper metadata (%s: %s); leaving it blank", type(e).__name__, e)
        return dict(_EMPTY)


# The Manual import flow reads a filename only.
extract_metadata = extract_paper_metadata
