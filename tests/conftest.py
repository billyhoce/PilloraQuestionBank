import io
import os

# Must be before any app imports — db.py reads DATABASE_URL at import time
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from datetime import datetime

import bcrypt
import boto3
import pytest
from moto import mock_aws
from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.main import app
from app.models.orm import (
    ExamType,
    Level,
    Paper,
    Question,
    QuestionPage,
    QuestionTopic,
    School,
    SchoolLevel,
    Stream,
    Subject,
    Subtopic,
    Topic,
    User,
)

_S3_BUCKET = "test-bucket"


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_engine():
    """Single in-memory SQLite engine shared across the session.

    StaticPool ensures all SQLAlchemy connections see the same in-memory DB.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_fk(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Function-scoped session; every test is rolled back on teardown."""
    with Session(db_engine) as session:
        session.begin()
        yield session
        session.rollback()


@pytest.fixture
def client(db_session):
    """TestClient wired to the per-test db_session via dependency override."""

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------


def _create_user(db_session: Session, email: str, password: str, role: str) -> User:
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
    user = User(
        email=email,
        password_hash=hashed,
        role=role,
        created_at=datetime.utcnow(),
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def admin_user(db_session):
    return _create_user(db_session, "admin@test.com", "Adminpass123!", "admin")


@pytest.fixture
def public_user(db_session):
    return _create_user(db_session, "user@test.com", "Userpass123!", "public")


@pytest.fixture
def admin_client(client, admin_user):
    """TestClient pre-authenticated as the admin user."""
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "Adminpass123!"})
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    return client


@pytest.fixture
def public_client(client, public_user):
    """TestClient pre-authenticated as a public user."""
    resp = client.post("/api/auth/login", json={"email": "user@test.com", "password": "Userpass123!"})
    assert resp.status_code == 200, f"Public login failed: {resp.text}"
    return client


# ---------------------------------------------------------------------------
# S3 fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_s3():
    """Mocked AWS S3 with a pre-created test bucket."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=_S3_BUCKET)
        yield s3


# ---------------------------------------------------------------------------
# Reference data fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def reference_data(db_session):
    """One row of every reference table, flushed but not committed."""
    school_level = SchoolLevel(name="Secondary")
    db_session.add(school_level)
    db_session.flush()

    subject = Subject(name="Math")
    db_session.add(subject)
    db_session.flush()

    stream = Stream(name="G3", school_level_id=school_level.id)
    db_session.add(stream)
    db_session.flush()

    level = Level(name="Sec 3", sort_order=9, school_level_id=school_level.id)
    db_session.add(level)
    db_session.flush()

    school = School(name="Raffles Institution")
    db_session.add(school)
    db_session.flush()

    exam_type = ExamType(name="EOY")
    db_session.add(exam_type)
    db_session.flush()

    topic = Topic(
        subject_id=subject.id,
        stream_id=stream.id,
        name="Algebra",
        topic_number=1,
    )
    db_session.add(topic)
    db_session.flush()

    subtopic = Subtopic(topic_id=topic.id, name="Linear Equations")
    db_session.add(subtopic)
    db_session.flush()

    return {
        "school_level": school_level,
        "subject": subject,
        "stream": stream,
        "level": level,
        "school": school,
        "exam_type": exam_type,
        "topic": topic,
        "subtopic": subtopic,
    }


# ---------------------------------------------------------------------------
# Sample paper fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_paper(db_session, reference_data, admin_user):
    """Paper with 3 questions and associated pages, flushed into db_session.

    Q1: marks=5, 1 question page (2480×800)
    Q2: marks=3, 1 question page (2480×600) + 1 answer page (2480×400)
    Q3: marks=2, 1 question page (2480×200)
    """
    rd = reference_data
    paper = Paper(
        subject_id=rd["subject"].id,
        stream_id=rd["stream"].id,
        level_id=rd["level"].id,
        school_id=rd["school"].id,
        exam_type_id=rd["exam_type"].id,
        year=2024,
        paper_number="1",
        created_by=admin_user.id,
        created_at=datetime.utcnow(),
    )
    db_session.add(paper)
    db_session.flush()

    q1 = Question(paper_id=paper.id, question_number=1, marks=5, created_at=datetime.utcnow())
    q2 = Question(paper_id=paper.id, question_number=2, marks=3, created_at=datetime.utcnow())
    q3 = Question(paper_id=paper.id, question_number=3, marks=2, created_at=datetime.utcnow())
    db_session.add_all([q1, q2, q3])
    db_session.flush()

    pages = [
        QuestionPage(
            question_id=q1.id,
            page_order=0,
            image_key=f"papers/{paper.id}/q1/question_0.webp",
            page_type="question",
            width_px=2480,
            height_px=800,
        ),
        QuestionPage(
            question_id=q2.id,
            page_order=0,
            image_key=f"papers/{paper.id}/q2/question_0.webp",
            page_type="question",
            width_px=2480,
            height_px=600,
        ),
        QuestionPage(
            question_id=q2.id,
            page_order=0,
            image_key=f"papers/{paper.id}/q2/answer_0.webp",
            page_type="answer",
            width_px=2480,
            height_px=400,
        ),
        QuestionPage(
            question_id=q3.id,
            page_order=0,
            image_key=f"papers/{paper.id}/q3/question_0.webp",
            page_type="question",
            width_px=2480,
            height_px=200,
        ),
    ]
    db_session.add_all(pages)
    db_session.flush()

    return paper


# ---------------------------------------------------------------------------
# Image / PDF byte fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def minimal_webp_bytes():
    """2480×800 white WebP image as bytes."""
    img = Image.new("RGB", (2480, 800), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=85)
    return buf.getvalue()


@pytest.fixture(scope="session")
def minimal_pdf_bytes():
    """Minimal 1-page PDF bytes (no real content, just a valid PDF structure)."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF"
    )
