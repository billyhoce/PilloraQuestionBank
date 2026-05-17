import base64
import json

import anthropic

LABEL_SUBTOPICS_TOOL = {
    "name": "label_subtopics",
    "description": "Record which subtopics are covered by the question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subtopic_ids": {
                "type": "array",
                "items": {"type": "integer"},
            },
        },
        "required": ["subtopic_ids"],
    },
}


def build_system_prompt(subject: str, stream: str, topics: list[dict]) -> str:
    topics_json = json.dumps(topics, indent=2)
    return (
        f"You are an expert in categorizing exam questions into relevant subtopics.\n"
        f"Available topics and their subtopics:\n{topics_json}\n"
        f"Pick the subtopic IDs that best describe what the question is testing. "
        f"You may pick multiple subtopics, including more than one under the same parent topic. "
        f"Only return subtopic IDs that appear in the list above. "
        f"If you are unsure, lean towards picking fewer subtopics rather than more, but pick at least one if you can. "
        f"Most of the time, each question will only require one subtopic, only occasionally requiring two or three."
    )


def label_question(
    question,
    topics: list[dict],
    image_bytes_list: list[bytes],
) -> list[dict]:
    subject = question.paper.subject.name
    stream = question.paper.stream.name
    valid_subtopic_ids = {s["id"] for t in topics for s in t.get("subtopics", [])}
    sys_prompt = build_system_prompt(subject, stream, topics)

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
    user_content = image_blocks + [{"type": "text", "text": "Identify the subtopics covered in this question."}]

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=[{"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
        tools=[LABEL_SUBTOPICS_TOOL],
        tool_choice={"type": "tool", "name": "label_subtopics"},
    )

    items = resp.content[0].input.get("subtopic_ids", [])
    seen: set[int] = set()
    out: list[dict] = []
    for sid in items:
        if sid in valid_subtopic_ids and sid not in seen:
            seen.add(sid)
            out.append({"subtopic_id": sid})
    return out
