"""Tests for database connection error handling."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import DatabaseConnectionError, get_db
from app.main import app


def _operational_error():
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_get_db_raises_database_connection_error_on_session_create_failure():
    with patch("app.db.SessionLocal", side_effect=_operational_error()):
        gen = get_db()
        with pytest.raises(DatabaseConnectionError):
            next(gen)


def test_get_db_raises_database_connection_error_when_query_fails():
    gen = get_db()
    next(gen)
    with pytest.raises(DatabaseConnectionError):
        gen.throw(_operational_error())


def test_get_db_logs_connection_failure():
    with patch("app.db.log") as mock_log, patch("app.db.SessionLocal", side_effect=_operational_error()):
        gen = get_db()
        with pytest.raises(DatabaseConnectionError):
            next(gen)
    assert mock_log.error.called


def test_database_unavailable_returns_503():
    with patch("app.db.SessionLocal", side_effect=_operational_error()):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/school-levels")
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Database is temporarily unavailable — please retry."}
