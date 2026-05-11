import base64
import json

import anthropic

from app.models.orm import QuestionTopic


def build_system_prompt(subject: str, stream: str, topics: list[dict]) -> str:
    topics_json = json.dumps(topics, indent=2)
    return (
        f"You are an expert in {subject} ({stream} stream) Singapore secondary school exams.\n"
        f"Available topics and subtopics:\n{topics_json}\n\n"
        "Given a question image, identify which topics it covers. "
        'Respond with valid JSON only: {"topics": [{"topic_id": <int>, "subtopic_id": <int|null>}]}'
    )


def parse_label_response(raw: str, valid_topic_ids: set[int]) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        data = json.loads(text)
        items = data.get("topics")
        if not isinstance(items, list):
            return []
        return [t for t in items if t.get("topic_id") in valid_topic_ids]
    except Exception:
        return []


def label_question(
    question,
    topics: list[dict],
    image_bytes_list: list[bytes],
    db,
) -> None:
    subject = question.paper.subject.name
    stream = question.paper.stream.name
    valid_ids = {t["id"] for t in topics}
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
    user_content = image_blocks + [{"type": "text", "text": "Identify the topics covered in this question."}]

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=[{"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    valid_subtopic_ids: set[int] = {
        s["id"] for t in topics for s in t.get("subtopics", [])
    }
    labeled = parse_label_response(resp.content[0].text, valid_ids)
    # Filter out any items with hallucinated subtopic IDs
    labeled = [
        item for item in labeled
        if item.get("subtopic_id") is None or item.get("subtopic_id") in valid_subtopic_ids
    ]
    for item in labeled:
        db.add(QuestionTopic(
            question_id=question.id,
            topic_id=item["topic_id"],
            subtopic_id=item.get("subtopic_id"),
        ))
    db.flush()
