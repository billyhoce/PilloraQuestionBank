from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.orm import Paper, SchoolLevel, User, UserPremiumSchoolLevel
from app.routes.auth import require_admin
from app.schemas.users import (
    PremiumSchoolLevelsUpdate,
    UserCreate,
    UserListItem,
    UserListResponse,
    UserRoleUpdate,
)
from app.services.auth import normalize_email

router = APIRouter(prefix="/api", tags=["users"])


def _validate_school_levels(db: Session, wanted: set[int]) -> None:
    """Reject ids that name no school level, so a typo can't silently grant
    nothing."""
    if not wanted:
        return
    known = {sl_id for (sl_id,) in db.query(SchoolLevel.id).filter(SchoolLevel.id.in_(wanted))}
    unknown = sorted(wanted - known)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown school level id(s): {', '.join(map(str, unknown))}",
        )


@router.get("/users", response_model=UserListResponse)
def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users so an admin can manage their tiers. Admin-only.

    Unclaimed invites are ordinary rows here (flagged `is_invited`) rather than
    hidden, which is what makes a never-claimed invite — usually a mistyped
    address — visible instead of silently doing nothing."""
    users = db.query(User).order_by(User.id).all()
    return {"data": [UserListItem.model_validate(u) for u in users]}


@router.post("/users", response_model=UserListItem, status_code=201)
def create_user(
    payload: UserCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Pre-create an account for an address that has not signed up yet, so its
    premium access is already live when the person registers. Admin-only.

    The row carries **no credentials**, so it cannot be signed into. It is
    claimed when someone registers with this address (`POST /api/auth/register`)
    or signs in with Google on it — both keep the role and premium set here.

    The address must be the exact one they will sign in with: Google reports the
    canonical form of a Gmail address, so an invite typed with a dot or `+` alias
    will never match. Case does not matter — addresses are normalized."""
    email = normalize_email(payload.email)
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    wanted = set(payload.school_level_ids)
    _validate_school_levels(db, wanted)

    user = User(
        email=email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        password_hash=None,
        google_sub=None,
        role=payload.role,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    for sl_id in sorted(wanted):
        db.add(UserPremiumSchoolLevel(user_id=user.id, school_level_id=sl_id))
    db.flush()
    db.refresh(user)
    return UserListItem.model_validate(user)


@router.patch("/users/{user_id}/role", response_model=UserListItem)
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Change a user's role (admin / public). Admin-only.

    Premium access is *not* set here — it is a set of school levels, written by
    ``set_premium_school_levels`` below.

    An admin cannot change their own role — this avoids accidentally locking the
    last admin out of the management UI.
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = payload.role
    db.flush()
    return UserListItem.model_validate(user)


@router.put("/users/{user_id}/premium-school-levels", response_model=UserListItem)
def set_premium_school_levels(
    user_id: int,
    payload: PremiumSchoolLevelsUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Replace the set of school levels a user has premium access to. Admin-only.

    A full replace rather than a grant/revoke pair, so the admin UI can send the
    checked boxes as-is. Unlike the role endpoint there is no self-change guard:
    an admin already sees every school level, so granting themselves one changes
    nothing and cannot lock anyone out.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    wanted = set(payload.school_level_ids)
    _validate_school_levels(db, wanted)

    db.query(UserPremiumSchoolLevel).filter(
        UserPremiumSchoolLevel.user_id == user_id
    ).delete(synchronize_session=False)
    for sl_id in sorted(wanted):
        db.add(UserPremiumSchoolLevel(user_id=user_id, school_level_id=sl_id))
    db.flush()
    # The relationship was loaded before the rewrite above, so it still holds the
    # old set until expired.
    db.refresh(user)
    return UserListItem.model_validate(user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete an account. Admin-only. Premium grants cascade away with it.

    Two things are refused rather than allowed to break something:

    * **Deleting yourself.** This is also what keeps an admin from being locked
      out: the caller is an admin and cannot be the target, so deleting an admin
      always leaves at least the caller behind. No separate "last admin" check is
      needed — it could never fire.
    * **Deleting anyone who imported papers.** ``Paper.created_by`` is
      ``ON DELETE RESTRICT``, so this is an explanatory 409 naming the count
      rather than a database error surfacing as a 500.
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    papers = db.query(Paper).filter(Paper.created_by == user_id).count()
    if papers:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{user.email} imported {papers} paper(s) and cannot be deleted. "
                "Change their tier to Normal instead."
            ),
        )

    db.delete(user)
    db.flush()
    return Response(status_code=204)
