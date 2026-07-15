"""Tests for the admin user-management endpoints."""


# ---------------------------------------------------------------------------
# GET /api/users
# ---------------------------------------------------------------------------


def test_list_users_admin_only(admin_client, public_user, premium_user):
    resp = admin_client.get("/api/users")
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()["data"]}
    assert {"admin@test.com", "user@test.com", "premium@test.com"} <= emails
    # Every row exposes the fields the management UI needs.
    row = resp.json()["data"][0]
    assert set(row) >= {"id", "email", "role", "created_at"}


def test_list_users_forbidden_for_public(public_client):
    assert public_client.get("/api/users").status_code == 403


def test_list_users_requires_auth(client):
    assert client.get("/api/users").status_code == 401


# ---------------------------------------------------------------------------
# PATCH /api/users/{id}/role
# ---------------------------------------------------------------------------


def test_promote_user_to_premium(admin_client, public_user):
    resp = admin_client.patch(f"/api/users/{public_user.id}/role", json={"role": "premium"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "premium"


def test_change_role_to_admin(admin_client, public_user):
    resp = admin_client.patch(f"/api/users/{public_user.id}/role", json={"role": "admin"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_change_role_invalid_value_rejected(admin_client, public_user):
    resp = admin_client.patch(f"/api/users/{public_user.id}/role", json={"role": "superuser"})
    assert resp.status_code == 422


def test_change_own_role_rejected(admin_client, admin_user):
    resp = admin_client.patch(f"/api/users/{admin_user.id}/role", json={"role": "public"})
    assert resp.status_code == 400


def test_change_role_unknown_user_returns_404(admin_client):
    resp = admin_client.patch("/api/users/99999/role", json={"role": "premium"})
    assert resp.status_code == 404


def test_change_role_forbidden_for_public(public_client, premium_user):
    resp = public_client.patch(f"/api/users/{premium_user.id}/role", json={"role": "public"})
    assert resp.status_code == 403
