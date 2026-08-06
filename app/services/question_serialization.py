"""Turning ORM questions into the dicts the API returns.

Shared by the browse endpoints (`routes/questions.py`) and the admin paper
editor (`routes/papers.py`), which is why these are public names in a service
module rather than underscore-private helpers on a route module.

Every function here expects the relations it reads to be eager-loaded — use the
options in `question_query` — and takes the presigned-URL maker as an argument
rather than importing it, so callers and tests cross the same seam.
"""

from typing import Callable, Optional

from app.models.orm import Paper, Question, QuestionPart

# Makes a presigned URL for an object key. Injected so tests don't have to
# monkeypatch a module-level import to keep S3 out of the picture.
Presigner = Callable[[str], str]


def paper_info(paper: Paper) -> dict:
    return {
        "id": paper.id,
        "year": paper.year,
        "paper_number": paper.paper_number,
        "is_premium": paper.is_premium,
        "subject_name": paper.subject.name,
        "stream_name": paper.stream.name,
        "level_name": paper.level.name,
        "school_name": paper.school.name,
        "exam_type_name": paper.exam_type.name,
    }


def first_page_url(question: Question, presign: Presigner) -> Optional[str]:
    pages = sorted(
        [p for p in question.pages if p.page_type == "question"],
        key=lambda p: p.page_order,
    )
    if not pages:
        return None
    try:
        return presign(pages[0].image_key)
    except Exception:
        return None


def part_topic_infos(part: QuestionPart) -> list[dict]:
    """Topic infos for a single part."""
    if not part.topics:
        return []
    subtopics_by_topic: dict[int, list[str]] = {}
    for qs in part.part_subtopics:
        subtopics_by_topic.setdefault(qs.topic_id, []).append(qs.subtopic.name)
    return [
        {
            "topic_name": qt.topic.name,
            "topic_number": qt.topic.topic_number,
            "subtopic_names": subtopics_by_topic.get(qt.topic_id, []),
        }
        for qt in part.topics
    ]


def topic_infos(question: Question) -> list[dict]:
    """The question's topics as a de-duplicated union across all its parts.

    Two parts testing the same topic collapse to one entry whose subtopic names
    are merged, so browse cards look the same as they did when topics were
    recorded at question level.
    """
    merged: dict[int, dict] = {}
    for part in question.parts:
        subtopics_by_topic: dict[int, list[str]] = {}
        for qs in part.part_subtopics:
            subtopics_by_topic.setdefault(qs.topic_id, []).append(qs.subtopic.name)
        for qt in part.topics:
            entry = merged.setdefault(
                qt.topic_id,
                {
                    "topic_name": qt.topic.name,
                    "topic_number": qt.topic.topic_number,
                    "subtopic_names": [],
                },
            )
            for name in subtopics_by_topic.get(qt.topic_id, []):
                if name not in entry["subtopic_names"]:
                    entry["subtopic_names"].append(name)
    return list(merged.values())


def part_infos(question: Question) -> list[dict]:
    return [
        {
            "part_order": part.part_order,
            "label": part.label,
            "marks": part.marks,
            "topics": part_topic_infos(part),
        }
        for part in sorted(question.parts, key=lambda p: p.part_order)
    ]


def tag_infos(question: Question) -> list[dict]:
    return [
        {"id": qt.tag.id, "name": qt.tag.name}
        for qt in question.tags
    ]


def serialize_list_item(
    q: Question, presign: Presigner, can_view_premium: bool = True
) -> dict:
    """Build a QuestionListItem dict for a question (with eager-loaded relations).

    When the question belongs to a premium paper and the viewer isn't entitled
    (``can_view_premium`` is False), the image URL is withheld and ``locked`` is
    set so the frontend shows a paywall placeholder instead of the image.
    """
    locked = q.paper.is_premium and not can_view_premium
    return {
        "id": q.id,
        "question_number": q.question_number,
        "marks": q.total_marks,
        "paper_info": paper_info(q.paper),
        "topics": topic_infos(q),
        "tags": tag_infos(q),
        "first_page_url": None if locked else first_page_url(q, presign),
        "locked": locked,
    }
