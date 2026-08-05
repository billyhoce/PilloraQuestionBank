import base64

import anthropic

from app.logger import Timer, log, log_tokens

MODEL = "claude-haiku-4-5-20251001"


class TruncatedResponseError(RuntimeError):
    """The model hit ``max_tokens`` before finishing its tool call.

    The tool input is then partial — some parts missing, or none parsed at all —
    which is indistinguishable from "this question genuinely has one blank part"
    once it reaches the reviewer. Raised so the caller can surface a retry
    instead of silently saving fewer parts than the question has.
    """


LABEL_PARTS_TOOL = {
    "name": "label_parts",
    "description": (
        "Split the question into the parts printed on the paper, and for each part "
        "select the items from the numbered list that it tests and read the marks "
        "it is worth."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "parts": {
                "type": "array",
                "description": "One entry per printed part, in the order they appear.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": (
                                'The part designation exactly as printed, e.g. "(a)", '
                                '"(a)(i)", "(b)(ii)". Use an empty string if the '
                                "question has no lettered parts."
                            ),
                        },
                        "selected_codes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                'Codes from the numbered list, e.g. ["1.1", "2"], for '
                                "what THIS part tests. Pick one or more."
                            ),
                        },
                        "marks": {
                            "type": ["integer", "null"],
                            "description": (
                                "Marks printed for THIS part — e.g. \"(2 marks)\" or a "
                                'bracketed "[2]" next to its answer line. Use null if '
                                "this part has no marks of its own."
                            ),
                        },
                    },
                    "required": ["label", "selected_codes", "marks"],
                },
            },
        },
        "required": ["parts"],
    },
}


def _build_options(topics: list[dict]) -> tuple[str, dict[str, tuple[int, int | None]]]:
    """
    Returns (formatted_list_str, code_map).
    code_map maps codes like "1.1" or "2" to (topic_id, subtopic_id | None).
    Topics with subtopics: only subtopic lines are shown.
    Topics without subtopics: shown as a bare line.
    """
    lines: list[str] = []
    code_map: dict[str, tuple[int, int | None]] = {}

    for t in topics:
        major = str(t["topic_number"])
        subtopics = t.get("subtopics", [])
        if subtopics:
            for i, s in enumerate(subtopics, 1):
                code = f"{major}.{i}"
                lines.append(f"{code:<6} {t['name']} - {s['name']}")
                code_map[code] = (t["id"], s["id"])
        else:
            lines.append(f"{major:<6} {t['name']}")
            code_map[major] = (t["id"], None)

    return "\n".join(lines), code_map


def build_system_prompt(subject: str, stream: str, options_str: str) -> str:
    return (
        f"You are an expert in categorizing {stream} {subject} exam questions.\n"
        f"Selectable items:\n{options_str}\n\n"
        f"Split the question into parts:\n"
        f"- Split the question into the parts exactly as the paper labels them, in printed order.\n"
        f"- Treat (a)(i) and (a)(ii) as two separate parts. Never group them under a single (a). "
        f"A question with (a)(i), (a)(ii) and (b) has exactly three parts.\n"
        f"- A question with no lettered parts has exactly one part, with an empty label.\n"
        f"- Never invent a part that is not printed on the paper.\n\n"
        f"For each part:\n"
        f"- Pick one or more codes that best describe what that part is testing.\n"
        f"- For topics that have subtopics, only the subtopic lines are selectable — pick the specific subtopics that apply.\n"
        f"- For topics without subtopics, pick the bare topic code if it applies.\n"
        f"- Only return codes that appear in the list above.\n"
        f"- Report the marks printed for that part. Do NOT sum marks across parts. "
        f"If a single total is printed for the whole question and cannot be split between "
        f"the parts, put that total on the first part and use null for the rest."
    )


def label_question(
    question,
    topics: list[dict],
    image_bytes_list: list[bytes],
) -> dict:
    subject = question.paper.subject.name
    stream = question.paper.stream.name
    options_str, code_map = _build_options(topics)
    sys_prompt = build_system_prompt(subject, stream, options_str)

    image_blocks = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/webp",
                "data": base64.standard_b64encode(b).decode(),
            },
        }
        for b in image_bytes_list
    ]
    user_content = image_blocks + [{"type": "text", "text": "Split this question into its parts, and for each part identify the topics and subtopics it covers and how many marks it is worth."}]

    client = anthropic.Anthropic()
    with Timer() as t_call:
        resp = client.messages.create(
            model=MODEL,
            # A multi-part question emits one object per part, so this needs far
            # more room than the old single-selection tool did.
            max_tokens=1500,
            system=[{"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
            tools=[LABEL_PARTS_TOOL],
            tool_choice={"type": "tool", "name": "label_parts"},
        )
    log.info(f"{'label_question':<22}| haiku     | {t_call.s}")
    log_tokens("label_question", MODEL, resp.usage)

    # Check before touching content: a truncated tool call may not even carry a
    # usable input dict, and a partial parts list must never pass for a complete one.
    if resp.stop_reason == "max_tokens":
        raise TruncatedResponseError(
            f"label_parts response hit max_tokens ({resp.usage.output_tokens} output tokens)"
        )

    tool_input = resp.content[0].input
    parts: list[dict] = []
    for raw_part in tool_input.get("parts") or []:
        # Dedupe within a part only — the same subtopic can legitimately be
        # tested by two different parts of one question.
        seen: set[tuple[int, int | None]] = set()
        selections: list[dict] = []
        for code in raw_part.get("selected_codes") or []:
            pair = code_map.get(code)
            if pair is None or pair in seen:
                continue
            seen.add(pair)
            topic_id, subtopic_id = pair
            selections.append({"topic_id": topic_id, "subtopic_id": subtopic_id})
        parts.append({
            "label": raw_part.get("label") or "",
            "marks": raw_part.get("marks"),
            "selections": selections,
        })

    if not parts:
        # Every question has at least one part; fall back to a single blank one
        # so the reviewer gets an editable row rather than nothing.
        parts = [{"label": "", "marks": None, "selections": []}]

    return {"parts": parts}
