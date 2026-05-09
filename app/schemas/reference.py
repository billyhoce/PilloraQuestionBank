from pydantic import BaseModel

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
