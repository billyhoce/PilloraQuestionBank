import base64

import anthropic

from app.logger import Timer, log, log_tokens

LABEL_TOPICS_TOOL = {
    "name": "label_topics",
    "description": "Select all items from the numbered list that this question tests.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selected_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'Codes from the numbered list, e.g. ["1.1", "2"]. Pick one or more.',
            },
        },
        "required": ["selected_codes"],
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
        f"Rules:\n"
        f"- Pick one or more codes that best describe what the question is testing.\n"
        f"- For topics that have subtopics, only the subtopic lines are selectable — pick the specific subtopics that apply.\n"
        f"- For topics without subtopics, pick the bare topic code if it applies.\n"
        f"- Only return codes that appear in the list above."
    )


def label_question(
    question,
    topics: list[dict],
    image_bytes_list: list[bytes],
) -> list[dict]:
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
    user_content = image_blocks + [{"type": "text", "text": "Identify the topics and subtopics covered in this question."}]

    client = anthropic.Anthropic()
    with Timer() as t_call:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=[{"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
            tools=[LABEL_TOPICS_TOOL],
            tool_choice={"type": "tool", "name": "label_topics"},
        )
    log.info(f"{'label_question':<22}| haiku     | {t_call.s}")
    log_tokens("label_question", "claude-haiku-4-5-20251001", resp.usage)

    raw_codes: list[str] = resp.content[0].input.get("selected_codes", [])
    seen: set[tuple[int, int | None]] = set()
    out: list[dict] = []
    for code in raw_codes:
        pair = code_map.get(code)
        if pair is None or pair in seen:
            continue
        seen.add(pair)
        topic_id, subtopic_id = pair
        out.append({"topic_id": topic_id, "subtopic_id": subtopic_id})
    return out
