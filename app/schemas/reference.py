from typing import Optional

from pydantic import BaseModel, Field

_orm = {"from_attributes": True}


class NameRequest(BaseModel):
    name: str


class SchoolLevelResponse(BaseModel):
    id: int
    name: str
    model_config = _orm


class SubjectResponse(BaseModel):
    id: int
    name: str
    model_config = _orm


class StreamRequest(BaseModel):
    name: str
    school_level_id: int


class StreamResponse(BaseModel):
    id: int
    name: str
    school_level_id: int
    model_config = _orm


class LevelRequest(BaseModel):
    name: str
    sort_order: int
    school_level_id: int


class LevelResponse(BaseModel):
    id: int
    name: str
    sort_order: int
    school_level_id: int
    model_config = _orm


class SchoolResponse(BaseModel):
    id: int
    name: str
    model_config = _orm


class ExamTypeResponse(BaseModel):
    id: int
    name: str
    model_config = _orm


class TagResponse(BaseModel):
    id: int
    name: str
    model_config = _orm


class TopicRequest(BaseModel):
    subject_id: int
    stream_id: int
    name: str
    topic_number: int


class TopicResponse(BaseModel):
    id: int
    subject_id: int
    stream_id: int
    name: str
    topic_number: int
    model_config = _orm


class SubtopicRequest(BaseModel):
    topic_id: int
    name: str


class SubtopicResponse(BaseModel):
    id: int
    topic_id: int
    name: str
    model_config = _orm


class TopicWithSubtopicsResponse(BaseModel):
    id: int
    subject_id: int
    stream_id: int
    name: str
    topic_number: int
    subtopics: list[SubtopicResponse] = Field(default_factory=list)
    model_config = _orm


class SubtopicSyncItem(BaseModel):
    id: Optional[int] = None
    name: str


class TopicSyncItem(BaseModel):
    id: Optional[int] = None
    topic_number: int
    name: str
    subtopics: list[SubtopicSyncItem] = Field(default_factory=list)


class TopicSyncRequest(BaseModel):
    subject_id: int
    stream_id: int
    topics: list[TopicSyncItem] = Field(default_factory=list)
