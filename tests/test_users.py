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


# ---------------------------------------------------------------------------
# PATCH /api/users/{id}/role
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Derived sign-in status
# ---------------------------------------------------------------------------


def test_list_users_exposes_sign_in_flags(admin_client, public_user, invited_user):
    """The admin table needs to tell a password account from a Google one and
    from an unclaimed invite, without ever seeing the hash."""
    rows = {u["email"]: u for u in admin_client.get("/api/users").json()["data"]}

    normal = rows["user@test.com"]
    assert (normal["has_password"], normal["has_google"], normal["is_invited"]) == (True, False, False)
    assert "password_hash" not in normal and "google_sub" not in normal

    invited = rows["invited@test.com"]
    assert (invited["has_password"], invited["has_google"], invited["is_invited"]) == (False, False, True)
    # An invite is listed like any other row, so a mistyped address is visible
    # rather than silently doing nothing.
    assert invited["last_login_at"] is None
    assert invited["papers_generated"] == 0


# ---------------------------------------------------------------------------
# POST /api/users — pre-adding a user by email
# ---------------------------------------------------------------------------


def test_create_user_pre_grants_premium(admin_client, reference_data):
    sl = reference_data["school_level"]
    resp = admin_client.post(
        "/api/users",
        json={
            "email": "newcomer@test.com",
            "first_name": "New",
            "last_name": "Comer",
            "school_level_ids": [sl.id],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "newcomer@test.com"
    assert body["is_invited"] is True
    assert [level["id"] for level in body["premium_school_levels"]] == [sl.id]


def test_create_user_normalizes_the_email(admin_client):
    """Google's OIDC claim is lower-case, so an invite typed in mixed case has to
    fold or it would never match the account they sign in with."""
    resp = admin_client.post("/api/users", json={"email": "MiXeD@Test.COM"})
    assert resp.status_code == 201
    assert resp.json()["email"] == "mixed@test.com"


def test_create_user_rejects_a_duplicate_address(admin_client, public_user):
    resp = admin_client.post("/api/users", json={"email": "USER@test.com"})
    assert resp.status_code == 409


def test_create_user_rejects_unknown_school_level(admin_client):
    resp = admin_client.post(
        "/api/users", json={"email": "x@test.com", "school_level_ids": [99999]}
    )
    assert resp.status_code == 422


def test_create_user_is_admin_only(public_client):
    resp = public_client.post("/api/users", json={"email": "x@test.com"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/users/{id}
# ---------------------------------------------------------------------------


def test_delete_user_removes_the_account_and_its_premium(
    admin_client, db_session, premium_user
):
    from app.models.orm import User, UserPremiumSchoolLevel

    user_id = premium_user.id
    assert admin_client.delete(f"/api/users/{user_id}").status_code == 204

    assert db_session.get(User, user_id) is None
    remaining = (
        db_session.query(UserPremiumSchoolLevel)
        .filter(UserPremiumSchoolLevel.user_id == user_id)
        .count()
    )
    assert remaining == 0


def test_delete_user_refuses_self(admin_client, admin_user):
    resp = admin_client.delete(f"/api/users/{admin_user.id}")
    assert resp.status_code == 400


def test_deleting_another_admin_always_leaves_one_behind(
    admin_client, db_session, admin_user
):
    """There is no separate "last admin" guard because refusing self-delete makes
    one unnecessary: the caller is an admin and can't be the target, so an admin
    always survives."""
    from app.models.orm import User
    from tests.conftest import _create_user

    second = _create_user(db_session, "admin2@test.com", "Adminpass123!", "admin")
    assert admin_client.delete(f"/api/users/{second.id}").status_code == 204

    assert db_session.query(User).filter(User.role == "admin").count() == 1
    assert db_session.get(User, admin_user.id) is not None


def test_delete_user_who_imported_papers_is_a_409(admin_client, db_session, sample_paper):
    """Paper.created_by is ON DELETE RESTRICT, so this must be an explanatory 409
    rather than a database error surfacing as a 500."""
    from tests.conftest import _create_user

    importer = _create_user(db_session, "importer@test.com", "Importpass123!", "public")
    sample_paper.created_by = importer.id
    db_session.flush()

    resp = admin_client.delete(f"/api/users/{importer.id}")
    assert resp.status_code == 409
    assert "cannot be deleted" in resp.json()["detail"]


def test_delete_unknown_user_returns_404(admin_client):
    assert admin_client.delete("/api/users/99999").status_code == 404


def test_delete_user_is_admin_only(public_client, premium_user):
    resp = public_client.delete(f"/api/users/{premium_user.id}")
    assert resp.status_code == 403
