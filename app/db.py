import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.logger import log

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


class Base(DeclarativeBase):
    pass


class DatabaseConnectionError(Exception):
    """Raised when the database is unreachable."""


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    try:
        db = SessionLocal()
    except OperationalError as e:
        log.error(f"{'get_db':<22}| db_connect| {e}")
        raise DatabaseConnectionError("Could not connect to the database") from e

    try:
        yield db
        db.commit()
    except OperationalError as e:
        db.rollback()
        log.error(f"{'get_db':<22}| db_connect| {e}")
        raise DatabaseConnectionError("Lost connection to the database") from e
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
