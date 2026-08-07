"""Tests for the Google OAuth 2.0 sign-in flow.

Google itself is never contacted: the two network helpers in
``app.services.google_oauth`` are monkeypatched, in the same spirit as ``moto``
standing in for S3 elsewhere in this suite.
"""
from urllib.parse import parse_qs, urlparse

import pytest

from app.models.orm import User
from app.services import google_oauth


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def google_configured(monkeypatch):
    """Pretend the deployment has Google credentials set."""
    monkeypatch.setattr(google_oauth, "_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(google_oauth, "_GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(
        google_oauth, "_GOOGLE_REDIRECT_URI", "https://testserver/api/auth/google/callback"
    )


@pytest.fixture
def google_profile(monkeypatch):
    """Stub the code exchange. Mutate the returned dict to vary the profile."""
    profile = {
        "sub": "google-sub-123",
        "email": "grace@example.com",
        "email_verified": True,
        "given_name": "Grace",
        "family_name": "Hopper",
    }

    def _profile_from_code(code):
        assert code == "auth-code"
        return profile

    monkeypatch.setattr(google_oauth, "profile_from_code", _profile_from_code)
    return profile


def _start_flow(client):
    """Hit /google/login and return the `state` nonce it planted in the cookie jar."""
    resp = client.get("/api/auth/google/login", follow_redirects=False)
    assert resp.status_code == 307
    return client.cookies["oauth_state"]


def _callback(client, state, code="auth-code"):
    return client.get(
        f"/api/auth/google/callback?code={code}&state={state}", follow_redirects=False
    )


def _error_code(resp):
    """The ?error= value from a failed-callback redirect."""
    return parse_qs(urlparse(resp.headers["location"]).query)["error"][0]


# ---------------------------------------------------------------------------
# Service layer — pure functions
# ---------------------------------------------------------------------------


def test_is_configured_false_without_env(monkeypatch):
    monkeypatch.setattr(google_oauth, "_GOOGLE_CLIENT_ID", "")
    assert google_oauth.is_configured() is False


def test_is_configured_true_with_env(google_configured):
    assert google_oauth.is_configured() is True


def test_authorization_url_carries_client_id_scopes_and_state(google_configured):
    url = google_oauth.build_authorization_url("nonce-abc")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.netloc == "accounts.google.com"
    assert params["client_id"] == ["test-client-id"]
    assert params["response_type"] == ["code"]
    assert params["state"] == ["nonce-abc"]
    assert params["scope"] == ["openid email profile"]
    # The secret must never appear in a URL the browser can see.
    assert "test-client-secret" not in url


def test_profile_from_code_errors_without_access_token(monkeypatch, google_configured):
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code: {"error": "invalid_grant"})
    with pytest.raises(google_oauth.GoogleOAuthError):
        google_oauth.profile_from_code("bad-code")


# ---------------------------------------------------------------------------
# Routes — provider discovery
# ---------------------------------------------------------------------------


def test_providers_reports_google_enabled(client, google_configured):
    assert client.get("/api/auth/providers").json() == {"google": True}


def test_providers_reports_google_disabled(client, monkeypatch):
    monkeypatch.setattr(google_oauth, "_GOOGLE_CLIENT_ID", "")
    assert client.get("/api/auth/providers").json() == {"google": False}


def test_google_login_unconfigured_returns_503(client, monkeypatch):
    monkeypatch.setattr(google_oauth, "_GOOGLE_CLIENT_ID", "")
    resp = client.get("/api/auth/google/login", follow_redirects=False)
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Routes — starting the flow
# ---------------------------------------------------------------------------


def test_google_login_redirects_to_google_and_sets_state_cookie(client, google_configured):
    resp = client.get("/api/auth/google/login", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("https://accounts.google.com/")

    cookie_header = resp.headers.get("set-cookie", "")
    assert "oauth_state" in cookie_header
    assert "HttpOnly" in cookie_header

    # The state in the URL must be the one we can later verify against.
    state_in_url = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    assert state_in_url == client.cookies["oauth_state"]


# ---------------------------------------------------------------------------
# Routes — callback: account creation, linking, return visits
# ---------------------------------------------------------------------------


def test_callback_creates_new_user(client, db_session, google_configured, google_profile):
    state = _start_flow(client)
    resp = _callback(client, state)

    assert resp.status_code == 307
    assert resp.headers["location"] == "/"
    assert "access_token" in resp.headers.get("set-cookie", "")

    user = db_session.query(User).filter(User.email == "grace@example.com").one()
    assert user.google_sub == "google-sub-123"
    assert user.first_name == "Grace"
    assert user.last_name == "Hopper"
    assert user.role == "public"
    assert user.password_hash is None


def test_callback_session_is_usable(client, google_configured, google_profile):
    state = _start_flow(client)
    _callback(client, state)

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "grace@example.com"
    assert me.json()["has_google"] is True
    assert me.json()["has_password"] is False


def test_callback_links_existing_password_account_and_keeps_role(
    client, db_session, google_configured, google_profile, reference_data
):
    google_profile["email"] = "premium@test.com"
    from tests.conftest import _create_user, _grant_premium

    existing = _create_user(
        db_session, "premium@test.com", "Premiumpass123!", "public",
        first_name="Existing", last_name="Name",
    )
    _grant_premium(db_session, existing, reference_data["school_level"])
    existing_id = existing.id

    state = _start_flow(client)
    resp = _callback(client, state)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"

    matches = db_session.query(User).filter(User.email == "premium@test.com").all()
    assert len(matches) == 1, "must link, not create a second account"
    assert matches[0].id == existing_id
    assert matches[0].google_sub == "google-sub-123"
    assert matches[0].role == "public", "linking must not change the role"
    assert [sl.name for sl in matches[0].premium_school_levels] == ["Secondary"], (
        "linking must not revoke premium access"
    )
    # A name the user typed themselves is never overwritten by Google's.
    assert matches[0].first_name == "Existing"
    assert matches[0].password_hash is not None, "password login must still work"


def test_callback_backfills_blank_names_on_link(
    client, db_session, google_configured, google_profile
):
    google_profile["email"] = "blank@test.com"
    from tests.conftest import _create_user

    _create_user(db_session, "blank@test.com", "Blankpass123!", "public", first_name="", last_name="")

    state = _start_flow(client)
    _callback(client, state)

    user = db_session.query(User).filter(User.email == "blank@test.com").one()
    assert user.first_name == "Grace"
    assert user.last_name == "Hopper"


def test_callback_returning_user_does_not_duplicate(
    client, db_session, google_configured, google_profile
):
    _callback(client, _start_flow(client))
    client.post("/api/auth/logout")

    # Same Google account, but the email on it has since changed. Matching on
    # `sub` must still find the original row.
    google_profile["email"] = "grace.hopper@example.com"
    resp = _callback(client, _start_flow(client))
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"

    assert db_session.query(User).filter(User.google_sub == "google-sub-123").count() == 1


def test_callback_handles_missing_google_names(
    client, db_session, google_configured, google_profile
):
    del google_profile["given_name"]
    del google_profile["family_name"]

    _callback(client, _start_flow(client))

    user = db_session.query(User).filter(User.email == "grace@example.com").one()
    assert user.first_name == ""
    assert user.last_name == ""


# ---------------------------------------------------------------------------
# Routes — callback: failure modes
# ---------------------------------------------------------------------------


def test_callback_state_mismatch_is_rejected(client, db_session, google_configured, google_profile):
    _start_flow(client)
    resp = _callback(client, "not-the-state-we-issued")

    assert resp.status_code == 307
    assert _error_code(resp) == "google_state_mismatch"
    assert "access_token" not in resp.headers.get("set-cookie", "")
    assert db_session.query(User).filter(User.email == "grace@example.com").count() == 0


def test_callback_without_state_cookie_is_rejected(client, db_session, google_configured, google_profile):
    # No /google/login first, so nothing to compare against.
    resp = _callback(client, "fabricated-state")
    assert _error_code(resp) == "google_state_mismatch"
    assert db_session.query(User).count() == 0


def test_callback_unverified_email_is_rejected(client, db_session, google_configured, google_profile):
    google_profile["email_verified"] = False
    resp = _callback(client, _start_flow(client))

    assert _error_code(resp) == "google_email_unverified"
    assert db_session.query(User).filter(User.email == "grace@example.com").count() == 0


def test_callback_user_denied_consent(client, db_session, google_configured):
    state = _start_flow(client)
    resp = client.get(
        f"/api/auth/google/callback?error=access_denied&state={state}", follow_redirects=False
    )
    assert _error_code(resp) == "google_cancelled"
    assert db_session.query(User).count() == 0


def test_callback_token_exchange_failure(client, db_session, monkeypatch, google_configured, google_profile):
    def _boom(code):
        raise google_oauth.GoogleOAuthError("token exchange returned 400")

    monkeypatch.setattr(google_oauth, "profile_from_code", _boom)

    resp = _callback(client, _start_flow(client))
    assert _error_code(resp) == "google_failed"
    assert db_session.query(User).count() == 0


# ---------------------------------------------------------------------------
# Password login must stay closed for Google-only accounts
# ---------------------------------------------------------------------------


def test_google_only_account_password_login_points_at_google(client, google_configured, google_profile):
    _callback(client, _start_flow(client))
    client.post("/api/auth/logout")

    resp = client.post(
        "/api/auth/login", json={"email": "grace@example.com", "password": "Secure123!"}
    )
    # Not a 500 from bcrypt, and not the generic 401 either — a password login
    # here can never succeed, so say what will work instead.
    assert resp.status_code == 409
    assert "Google" in resp.json()["detail"]


def test_google_only_account_never_logs_in_with_a_password(client, google_configured, google_profile):
    _callback(client, _start_flow(client))
    client.post("/api/auth/logout")

    resp = client.post(
        "/api/auth/login", json={"email": "grace@example.com", "password": ""}
    )
    assert resp.status_code == 409
    assert "access_token" not in resp.headers.get("set-cookie", "")


def test_linked_account_still_logs_in_with_its_password(
    client, db_session, google_configured, google_profile
):
    """An account with both a password and a Google link keeps working both ways."""
    google_profile["email"] = "user@test.com"
    from tests.conftest import _create_user

    _create_user(db_session, "user@test.com", "Userpass123!", "public")
    _callback(client, _start_flow(client))
    client.post("/api/auth/logout")

    resp = client.post(
        "/api/auth/login", json={"email": "user@test.com", "password": "Userpass123!"}
    )
    assert resp.status_code == 200
    assert "access_token" in resp.headers.get("set-cookie", "")


def test_linked_account_wrong_password_stays_a_generic_401(
    client, db_session, google_configured, google_profile
):
    """The Google hint must not leak for accounts that do have a password."""
    google_profile["email"] = "user@test.com"
    from tests.conftest import _create_user

    _create_user(db_session, "user@test.com", "Userpass123!", "public")
    _callback(client, _start_flow(client))
    client.post("/api/auth/logout")

    resp = client.post(
        "/api/auth/login", json={"email": "user@test.com", "password": "WrongPass123!"}
    )
    assert resp.status_code == 401
    assert "Google" not in resp.json()["detail"]
