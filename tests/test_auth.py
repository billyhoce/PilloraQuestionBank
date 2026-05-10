"""Tests for auth service functions and auth routes."""
from datetime import timedelta

import pytest

from app.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


# ---------------------------------------------------------------------------
# Service layer — pure functions (no DB, no HTTP)
# ---------------------------------------------------------------------------


def test_hash_password_produces_bcrypt_hash():
    result = hash_password("mypassword")
    assert result.startswith("$2b$")
    assert result != "mypassword"


def test_verify_password_correct():
    hashed = hash_password("secret")
    assert verify_password("secret", hashed) is True


def test_verify_password_incorrect():
    hashed = hash_password("secret")
    assert verify_password("wrong", hashed) is False


def test_create_access_token_contains_subject_and_exp():
    token = create_access_token({"sub": "42"})
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert "exp" in payload


def test_decode_valid_token():
    token = create_access_token({"sub": "99"})
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "99"


def test_decode_expired_token():
    token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))
    result = decode_access_token(token)
    assert result is None


def test_decode_tampered_token():
    token = create_access_token({"sub": "1"})
    tampered = token[:-4] + "XXXX"
    result = decode_access_token(tampered)
    assert result is None


# ---------------------------------------------------------------------------
# Routes — registration
# ---------------------------------------------------------------------------


def test_register_success(client):
    resp = client.post("/api/auth/register", json={"email": "new@example.com", "password": "Secure123!"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert "password_hash" not in body
    assert "password" not in body


def test_register_duplicate_email_returns_409(client):
    payload = {"email": "dup@example.com", "password": "Secure123!"}
    client.post("/api/auth/register", json=payload)
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 409


def test_register_invalid_email_returns_422(client):
    resp = client.post("/api/auth/register", json={"email": "notanemail", "password": "Secure123!"})
    assert resp.status_code == 422


def test_register_short_password_returns_422(client):
    resp = client.post("/api/auth/register", json={"email": "ok@example.com", "password": "short"})
    assert resp.status_code == 422


@pytest.mark.parametrize("password", [
    "secure123!",    # no uppercase
    "SECURE123!",    # no lowercase
    "Securepass!",   # no number
    "Secure1234",    # no special character
])
def test_register_weak_password_returns_422(client, password):
    resp = client.post("/api/auth/register", json={"email": "ok@example.com", "password": password})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Routes — login / logout
# ---------------------------------------------------------------------------


def test_login_success_sets_httponly_cookie(client, admin_user):
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "Adminpass123!"})
    assert resp.status_code == 200
    cookie_header = resp.headers.get("set-cookie", "")
    assert "access_token" in cookie_header
    assert "HttpOnly" in cookie_header


def test_login_wrong_password_returns_401(client, admin_user):
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "wrongpass"})
    assert resp.status_code == 401


def test_login_unknown_email_returns_401(client):
    resp = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "pass1234"})
    assert resp.status_code == 401


def test_logout_clears_cookie(admin_client):
    resp = admin_client.post("/api/auth/logout")
    assert resp.status_code == 200
    cookie_header = resp.headers.get("set-cookie", "")
    # Cookie should be deleted: either empty value or Max-Age=0
    assert "access_token" in cookie_header
    assert "Max-Age=0" in cookie_header or 'access_token=""' in cookie_header


# ---------------------------------------------------------------------------
# Routes — authorization guards
# ---------------------------------------------------------------------------


def test_protected_route_no_token_returns_401(client):
    resp = client.delete("/api/subjects/1")
    assert resp.status_code == 401


def test_admin_route_public_token_returns_403(public_client):
    resp = public_client.delete("/api/subjects/1")
    assert resp.status_code == 403


def test_admin_route_admin_token_succeeds(admin_client, reference_data):
    subject_id = reference_data["subject"].id
    resp = admin_client.delete(f"/api/subjects/{subject_id}")
    assert resp.status_code in (204, 409)  # 409 if FK constraint, 204 if deleted
