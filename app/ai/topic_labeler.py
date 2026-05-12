import base64
import json

import anthropic

from app.models.orm import QuestionTopic

LABEL_TOPICS_TOOL = {
    "name": "label_topics",
    "description": "Record which topics and subtopics are covered by the question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic_id": {"type": "integer"},
                        "subtopic_id": {"type": ["integer", "null"]},
                    },
                    "required": ["topic_id", "subtopic_id"],
                },
            },
        },
        "required": ["topics"],
    },
}


def build_system_prompt(subject: str, stream: str, topics: list[dict]) -> str:
    topics_json = json.dumps(topics, indent=2)
    return (
        f"You are an expert in {subject} ({stream} stream) Singapore secondary school exams.\n"
        f"Available topics and subtopics:\n{topics_json}"
    )


def label_question(
    question,
    topics: list[dict],
    image_bytes_list: list[bytes],
    db,
) -> None:
    subject = question.paper.subject.name
    stream = question.paper.stream.name
    valid_topic_ids = {t["id"] for t in topics}
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
    user_content = image_blocks + [{"type": "text", "text": "Identify the topics covered in this question."}]

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=[{"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
        tools=[LABEL_TOPICS_TOOL],
        tool_choice={"type": "tool", "name": "label_topics"},
    )

    items = resp.content[0].input.get("topics", [])
    items = [
        item for item in items
        if item.get("topic_id") in valid_topic_ids
        and (item.get("subtopic_id") is None or item.get("subtopic_id") in valid_subtopic_ids)
    ]
    for item in items:
        db.add(QuestionTopic(
            question_id=question.id,
            topic_id=item["topic_id"],
            subtopic_id=item.get("subtopic_id"),
        ))
    db.flush()
