from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models.orm import (
    ExamType,
    Level,
    School,
    SchoolLevel,
    Stream,
    Subject,
    Subtopic,
    Topic,
    User,
)
from app.routes.auth import require_admin
from app.schemas.reference import (
    ExamTypeResponse,
    LevelRequest,
    LevelResponse,
    NameRequest,
    SchoolLevelResponse,
    SchoolResponse,
    StreamRequest,
    StreamResponse,
    SubjectResponse,
    SubtopicRequest,
    SubtopicResponse,
    TopicRequest,
    TopicResponse,
    TopicWithSubtopicsResponse,
)

router = APIRouter(prefix="/api", tags=["reference"])


def _not_found(label: str):
    raise HTTPException(status_code=404, detail=f"{label} not found")


def _delete_with_fk_guard(db: Session, obj, label: str):
    try:
        sp = db.begin_nested()
        db.delete(obj)
        db.flush()
        sp.commit()
    except IntegrityError:
        sp.rollback()
        raise HTTPException(status_code=409, detail=f"Cannot delete {label} with dependent data")


# ---------------------------------------------------------------------------
# School levels
# ---------------------------------------------------------------------------


@router.get("/school-levels")
def list_school_levels(db: Session = Depends(get_db)):
    return {"data": db.query(SchoolLevel).all()}


@router.get("/school-levels/{school_level_id}", response_model=SchoolLevelResponse)
def get_school_level(school_level_id: int, db: Session = Depends(get_db)):
    obj = db.get(SchoolLevel, school_level_id)
    if obj is None:
        _not_found("School level")
    return obj


@router.post("/school-levels", response_model=SchoolLevelResponse, status_code=201)
def create_school_level(payload: NameRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = SchoolLevel(name=payload.name)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="School level already exists")
    return obj


@router.put("/school-levels/{school_level_id}", response_model=SchoolLevelResponse)
def update_school_level(school_level_id: int, payload: NameRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(SchoolLevel, school_level_id)
    if obj is None:
        _not_found("School level")
    obj.name = payload.name
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="School level already exists")
    return obj


@router.delete("/school-levels/{school_level_id}", status_code=204)
def delete_school_level(school_level_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(SchoolLevel, school_level_id)
    if obj is None:
        _not_found("School level")
    _delete_with_fk_guard(db, obj, "school level")


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


@router.get("/subjects")
def list_subjects(db: Session = Depends(get_db)):
    return {"data": db.query(Subject).all()}


@router.get("/subjects/{subject_id}", response_model=SubjectResponse)
def get_subject(subject_id: int, db: Session = Depends(get_db)):
    obj = db.get(Subject, subject_id)
    if obj is None:
        _not_found("Subject")
    return obj


@router.post("/subjects", response_model=SubjectResponse, status_code=201)
def create_subject(payload: NameRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = Subject(name=payload.name)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Subject already exists")
    return obj


@router.put("/subjects/{subject_id}", response_model=SubjectResponse)
def update_subject(subject_id: int, payload: NameRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(Subject, subject_id)
    if obj is None:
        _not_found("Subject")
    obj.name = payload.name
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Subject already exists")
    return obj


@router.delete("/subjects/{subject_id}", status_code=204)
def delete_subject(subject_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(Subject, subject_id)
    if obj is None:
        _not_found("Subject")
    _delete_with_fk_guard(db, obj, "subject")


# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------


@router.get("/streams")
def list_streams(db: Session = Depends(get_db)):
    return {"data": db.query(Stream).all()}


@router.get("/streams/{stream_id}", response_model=StreamResponse)
def get_stream(stream_id: int, db: Session = Depends(get_db)):
    obj = db.get(Stream, stream_id)
    if obj is None:
        _not_found("Stream")
    return obj


@router.post("/streams", response_model=StreamResponse, status_code=201)
def create_stream(payload: StreamRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = Stream(name=payload.name, school_level_id=payload.school_level_id)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Stream already exists")
    return obj


@router.put("/streams/{stream_id}", response_model=StreamResponse)
def update_stream(stream_id: int, payload: StreamRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(Stream, stream_id)
    if obj is None:
        _not_found("Stream")
    obj.name = payload.name
    obj.school_level_id = payload.school_level_id
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Stream already exists")
    return obj


@router.delete("/streams/{stream_id}", status_code=204)
def delete_stream(stream_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(Stream, stream_id)
    if obj is None:
        _not_found("Stream")
    _delete_with_fk_guard(db, obj, "stream")


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------


@router.get("/levels")
def list_levels(db: Session = Depends(get_db)):
    return {"data": db.query(Level).order_by(Level.sort_order).all()}


@router.get("/levels/{level_id}", response_model=LevelResponse)
def get_level(level_id: int, db: Session = Depends(get_db)):
    obj = db.get(Level, level_id)
    if obj is None:
        _not_found("Level")
    return obj


@router.post("/levels", response_model=LevelResponse, status_code=201)
def create_level(payload: LevelRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = Level(name=payload.name, sort_order=payload.sort_order, school_level_id=payload.school_level_id)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Level already exists")
    return obj


@router.put("/levels/{level_id}", response_model=LevelResponse)
def update_level(level_id: int, payload: LevelRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(Level, level_id)
    if obj is None:
        _not_found("Level")
    obj.name = payload.name
    obj.sort_order = payload.sort_order
    obj.school_level_id = payload.school_level_id
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Level already exists")
    return obj


@router.delete("/levels/{level_id}", status_code=204)
def delete_level(level_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(Level, level_id)
    if obj is None:
        _not_found("Level")
    _delete_with_fk_guard(db, obj, "level")


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------


@router.get("/schools")
def list_schools(db: Session = Depends(get_db)):
    return {"data": db.query(School).all()}


@router.get("/schools/{school_id}", response_model=SchoolResponse)
def get_school(school_id: int, db: Session = Depends(get_db)):
    obj = db.get(School, school_id)
    if obj is None:
        _not_found("School")
    return obj


@router.post("/schools", response_model=SchoolResponse, status_code=201)
def create_school(payload: NameRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = School(name=payload.name)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="School already exists")
    return obj


@router.put("/schools/{school_id}", response_model=SchoolResponse)
def update_school(school_id: int, payload: NameRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(School, school_id)
    if obj is None:
        _not_found("School")
    obj.name = payload.name
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="School already exists")
    return obj


@router.delete("/schools/{school_id}", status_code=204)
def delete_school(school_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(School, school_id)
    if obj is None:
        _not_found("School")
    _delete_with_fk_guard(db, obj, "school")


# ---------------------------------------------------------------------------
# Exam types
# ---------------------------------------------------------------------------


@router.get("/exam-types")
def list_exam_types(db: Session = Depends(get_db)):
    return {"data": db.query(ExamType).all()}


@router.get("/exam-types/{exam_type_id}", response_model=ExamTypeResponse)
def get_exam_type(exam_type_id: int, db: Session = Depends(get_db)):
    obj = db.get(ExamType, exam_type_id)
    if obj is None:
        _not_found("Exam type")
    return obj


@router.post("/exam-types", response_model=ExamTypeResponse, status_code=201)
def create_exam_type(payload: NameRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = ExamType(name=payload.name)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Exam type already exists")
    return obj


@router.put("/exam-types/{exam_type_id}", response_model=ExamTypeResponse)
def update_exam_type(exam_type_id: int, payload: NameRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(ExamType, exam_type_id)
    if obj is None:
        _not_found("Exam type")
    obj.name = payload.name
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Exam type already exists")
    return obj


@router.delete("/exam-types/{exam_type_id}", status_code=204)
def delete_exam_type(exam_type_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(ExamType, exam_type_id)
    if obj is None:
        _not_found("Exam type")
    _delete_with_fk_guard(db, obj, "exam type")


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


@router.get("/topics")
def list_topics(subject_id: Optional[int] = None, stream_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Topic).options(joinedload(Topic.subtopics))
    if subject_id is not None:
        q = q.filter(Topic.subject_id == subject_id)
    if stream_id is not None:
        q = q.filter(Topic.stream_id == stream_id)
    topics = q.order_by(Topic.topic_number).all()
    return {"data": [TopicWithSubtopicsResponse.model_validate(t) for t in topics]}


@router.get("/topics/{topic_id}", response_model=TopicResponse)
def get_topic(topic_id: int, db: Session = Depends(get_db)):
    obj = db.get(Topic, topic_id)
    if obj is None:
        _not_found("Topic")
    return obj


@router.post("/topics", response_model=TopicResponse, status_code=201)
def create_topic(payload: TopicRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = Topic(
        subject_id=payload.subject_id,
        stream_id=payload.stream_id,
        name=payload.name,
        topic_number=payload.topic_number,
    )
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Topic already exists for this subject and stream")
    return obj


@router.put("/topics/{topic_id}", response_model=TopicResponse)
def update_topic(topic_id: int, payload: TopicRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(Topic, topic_id)
    if obj is None:
        _not_found("Topic")
    obj.subject_id = payload.subject_id
    obj.stream_id = payload.stream_id
    obj.name = payload.name
    obj.topic_number = payload.topic_number
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Topic already exists for this subject and stream")
    return obj


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(Topic, topic_id)
    if obj is None:
        _not_found("Topic")
    _delete_with_fk_guard(db, obj, "topic")


# ---------------------------------------------------------------------------
# Subtopics
# ---------------------------------------------------------------------------


@router.get("/subtopics")
def list_subtopics(topic_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Subtopic)
    if topic_id is not None:
        q = q.filter(Subtopic.topic_id == topic_id)
    return {"data": q.all()}


@router.get("/subtopics/{subtopic_id}", response_model=SubtopicResponse)
def get_subtopic(subtopic_id: int, db: Session = Depends(get_db)):
    obj = db.get(Subtopic, subtopic_id)
    if obj is None:
        _not_found("Subtopic")
    return obj


@router.post("/subtopics", response_model=SubtopicResponse, status_code=201)
def create_subtopic(payload: SubtopicRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = Subtopic(topic_id=payload.topic_id, name=payload.name)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Subtopic already exists for this topic")
    return obj


@router.put("/subtopics/{subtopic_id}", response_model=SubtopicResponse)
def update_subtopic(subtopic_id: int, payload: SubtopicRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(Subtopic, subtopic_id)
    if obj is None:
        _not_found("Subtopic")
    obj.topic_id = payload.topic_id
    obj.name = payload.name
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Subtopic already exists for this topic")
    return obj


@router.delete("/subtopics/{subtopic_id}", status_code=204)
def delete_subtopic(subtopic_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    obj = db.get(Subtopic, subtopic_id)
    if obj is None:
        _not_found("Subtopic")
    _delete_with_fk_guard(db, obj, "subtopic")
