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


@pytest.mark.parametrize("hashed", [None, ""])
def test_verify_password_rejects_missing_hash(hashed):
    """Google-only accounts store no password_hash — reject rather than raise."""
    assert verify_password("anything", hashed) is False


def test_create_access_token_contains_subject_and_exp():
    token = create_access_token({"sub": "42"})
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert "exp" in payload


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


def _register_payload(**overrides):
    payload = {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "new@example.com",
        "password": "Secure123!",
    }
    payload.update(overrides)
    return payload


def test_register_success(client):
    resp = client.post("/api/auth/register", json=_register_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert body["first_name"] == "Ada"
    assert body["last_name"] == "Lovelace"
    assert "password_hash" not in body
    assert "password" not in body


def test_register_reports_password_account_not_google(client):
    resp = client.post("/api/auth/register", json=_register_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["has_password"] is True
    assert body["has_google"] is False


def test_register_trims_surrounding_whitespace_from_names(client):
    resp = client.post("/api/auth/register", json=_register_payload(first_name="  Ada  ", last_name=" Lovelace "))
    assert resp.status_code == 201
    assert resp.json()["first_name"] == "Ada"
    assert resp.json()["last_name"] == "Lovelace"


@pytest.mark.parametrize("field", ["first_name", "last_name"])
def test_register_blank_name_returns_422(client, field):
    resp = client.post("/api/auth/register", json=_register_payload(**{field: "   "}))
    assert resp.status_code == 422


def test_register_duplicate_email_returns_409(client):
    payload = _register_payload(email="dup@example.com")
    client.post("/api/auth/register", json=payload)
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 409


def test_register_short_password_returns_422(client):
    resp = client.post("/api/auth/register", json=_register_payload(password="short"))
    assert resp.status_code == 422


@pytest.mark.parametrize("password", [
    "secure123!",    # no uppercase
    "SECURE123!",    # no lowercase
    "Securepass!",   # no number
    "Secure1234",    # no special character
])
def test_register_weak_password_returns_422(client, password):
    resp = client.post("/api/auth/register", json=_register_payload(password=password))
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


def test_login_unknown_email_is_indistinguishable_from_a_wrong_password(client, admin_user):
    """The Google hint is the only case that reveals anything about an account;
    these two must stay identical."""
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Whatever1!"})
    wrong = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "Whatever1!"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


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


# ---------------------------------------------------------------------------
# Email normalization
# ---------------------------------------------------------------------------


def test_register_stores_the_email_lower_cased(client):
    resp = client.post(
        "/api/auth/register",
        json={
            "first_name": "Mixed",
            "last_name": "Case",
            "email": "MiXeD@Test.COM",
            "password": "Validpass123!",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "mixed@test.com"


def test_login_is_case_insensitive(client, public_user):
    resp = client.post(
        "/api/auth/login", json={"email": "USER@TEST.COM", "password": "Userpass123!"}
    )
    assert resp.status_code == 200


def test_register_rejects_an_existing_address_in_a_different_case(client, public_user):
    """Without folding case this would create a second account for one person —
    the same bug that would strand an invite when they sign in with Google."""
    resp = client.post(
        "/api/auth/register",
        json={
            "first_name": "Dup",
            "last_name": "Licate",
            "email": "User@Test.com",
            "password": "Validpass123!",
        },
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Claiming an admin-created invite
# ---------------------------------------------------------------------------


def test_register_claims_a_pending_invite_and_keeps_its_premium(
    client, db_session, invited_user, reference_data
):
    """A 409 here would leave an invited user unable to sign up at all."""
    user_id = invited_user.id
    resp = client.post(
        "/api/auth/register",
        json={
            "first_name": "Claimed",
            "last_name": "Account",
            "email": "invited@test.com",
            "password": "Validpass123!",
        },
    )
    assert resp.status_code == 201
    body = resp.json()

    # The same row, not a second one.
    assert body["id"] == user_id
    assert [sl["id"] for sl in body["premium_school_levels"]] == [
        reference_data["school_level"].id
    ]
    assert body["has_password"] is True
    assert body["first_name"] == "Claimed"

    from app.models.orm import User
    assert db_session.query(User).filter(User.email == "invited@test.com").count() == 1


def test_register_claims_an_invite_regardless_of_case(client, invited_user):
    resp = client.post(
        "/api/auth/register",
        json={
            "first_name": "Claimed",
            "last_name": "Account",
            "email": "INVITED@test.com",
            "password": "Validpass123!",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == invited_user.id


def test_register_keeps_the_role_an_admin_set_on_the_invite(client, db_session):
    from tests.conftest import _create_invited_user

    _create_invited_user(db_session, "futureadmin@test.com", role="admin")
    resp = client.post(
        "/api/auth/register",
        json={
            "first_name": "Future",
            "last_name": "Admin",
            "email": "futureadmin@test.com",
            "password": "Validpass123!",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "admin"


def test_register_does_not_overwrite_a_name_the_admin_recorded(client, db_session):
    from app.models.orm import User
    from tests.conftest import _create_invited_user

    invited = _create_invited_user(db_session, "named@test.com")
    invited.first_name = "Recorded"
    db_session.flush()

    resp = client.post(
        "/api/auth/register",
        json={
            "first_name": "Typed",
            "last_name": "Themselves",
            "email": "named@test.com",
            "password": "Validpass123!",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["first_name"] == "Recorded"   # kept
    assert resp.json()["last_name"] == "Themselves"  # filled in


def test_register_still_rejects_an_account_that_has_a_password(client, public_user):
    """Only a *credential-less* row may be claimed — otherwise registering over
    someone else's address would be an account takeover."""
    resp = client.post(
        "/api/auth/register",
        json={
            "first_name": "Not",
            "last_name": "Yours",
            "email": "user@test.com",
            "password": "Validpass123!",
        },
    )
    assert resp.status_code == 409


def test_password_login_on_an_unclaimed_invite_is_the_generic_401(client, invited_user):
    """An invite has no password *and* no google_sub, so it must not trip the
    "created with Google" 409 — that would disclose the address exists."""
    resp = client.post(
        "/api/auth/login", json={"email": "invited@test.com", "password": "Anything123!"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


# ---------------------------------------------------------------------------
# last_login_at
# ---------------------------------------------------------------------------


def test_login_stamps_last_login_at(client, db_session, public_user):
    """Written inside _set_session_cookie, which both the password path and the
    Google callback share."""
    assert public_user.last_login_at is None

    client.post("/api/auth/login", json={"email": "user@test.com", "password": "Userpass123!"})

    # flush before refresh: refresh() discards pending changes rather than
    # flushing them, so reading straight back would look like nothing happened.
    db_session.flush()
    db_session.refresh(public_user)
    assert public_user.last_login_at is not None
