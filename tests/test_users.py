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
    assert set(row) >= {
        "id", "email", "first_name", "last_name", "role",
        "premium_school_levels", "created_at",
    }
    assert "password_hash" not in row


def test_list_users_reports_premium_school_levels(admin_client, premium_user):
    rows = admin_client.get("/api/users").json()["data"]
    row = next(u for u in rows if u["email"] == "premium@test.com")
    # Premium is a set of school levels, not a role value.
    assert row["role"] == "public"
    assert [sl["name"] for sl in row["premium_school_levels"]] == ["Secondary"]


def test_list_users_forbidden_for_public(public_client):
    assert public_client.get("/api/users").status_code == 403


def test_list_users_requires_auth(client):
    assert client.get("/api/users").status_code == 401


# ---------------------------------------------------------------------------
# PATCH /api/users/{id}/role
# ---------------------------------------------------------------------------


def test_premium_is_no_longer_a_role(admin_client, public_user):
    """It moved to PUT /users/{id}/premium-school-levels."""
    resp = admin_client.patch(f"/api/users/{public_user.id}/role", json={"role": "premium"})
    assert resp.status_code == 422


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
    resp = admin_client.patch("/api/users/99999/role", json={"role": "admin"})
    assert resp.status_code == 404


def test_change_role_forbidden_for_public(public_client, premium_user):
    resp = public_client.patch(f"/api/users/{premium_user.id}/role", json={"role": "public"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /api/users/{id}/premium-school-levels
# ---------------------------------------------------------------------------


def _put_levels(client, user_id, ids):
    return client.put(
        f"/api/users/{user_id}/premium-school-levels", json={"school_level_ids": ids}
    )


def test_grant_premium_school_level(admin_client, public_user, reference_data):
    resp = _put_levels(admin_client, public_user.id, [reference_data["school_level"].id])
    assert resp.status_code == 200
    assert [sl["name"] for sl in resp.json()["premium_school_levels"]] == ["Secondary"]
    # Granting premium does not touch the role.
    assert resp.json()["role"] == "public"


def test_grant_multiple_school_levels(admin_client, public_user, reference_data):
    resp = _put_levels(
        admin_client,
        public_user.id,
        [reference_data["school_level"].id, reference_data["other_school_level"].id],
    )
    assert resp.status_code == 200
    assert {sl["name"] for sl in resp.json()["premium_school_levels"]} == {
        "Secondary", "Primary",
    }


def test_set_premium_school_levels_replaces_rather_than_merges(
    admin_client, premium_user, reference_data
):
    """One payload both grants and revokes — the admin UI sends the ticked boxes."""
    resp = _put_levels(
        admin_client, premium_user.id, [reference_data["other_school_level"].id]
    )
    assert resp.status_code == 200
    assert [sl["name"] for sl in resp.json()["premium_school_levels"]] == ["Primary"]


def test_revoke_all_premium_school_levels(admin_client, premium_user):
    resp = _put_levels(admin_client, premium_user.id, [])
    assert resp.status_code == 200
    assert resp.json()["premium_school_levels"] == []


def test_set_premium_school_levels_is_idempotent(
    admin_client, public_user, reference_data
):
    ids = [reference_data["school_level"].id]
    assert _put_levels(admin_client, public_user.id, ids).status_code == 200
    resp = _put_levels(admin_client, public_user.id, ids)
    assert resp.status_code == 200
    assert len(resp.json()["premium_school_levels"]) == 1


def test_set_premium_school_levels_unknown_level_rejected(admin_client, public_user):
    resp = _put_levels(admin_client, public_user.id, [99999])
    assert resp.status_code == 422


def test_set_premium_school_levels_unknown_user_returns_404(
    admin_client, reference_data
):
    resp = _put_levels(admin_client, 99999, [reference_data["school_level"].id])
    assert resp.status_code == 404


def test_admin_may_grant_themselves(admin_client, admin_user, reference_data):
    """No self-guard here — an admin already sees every school level."""
    resp = _put_levels(admin_client, admin_user.id, [reference_data["school_level"].id])
    assert resp.status_code == 200


def test_set_premium_school_levels_forbidden_for_public(
    public_client, premium_user, reference_data
):
    resp = _put_levels(public_client, premium_user.id, [reference_data["school_level"].id])
    assert resp.status_code == 403


def test_set_premium_school_levels_requires_auth(client, reference_data):
    resp = _put_levels(client, 1, [reference_data["school_level"].id])
    assert resp.status_code == 401
