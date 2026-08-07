from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.orm import SchoolLevel, User, UserPremiumSchoolLevel
from app.routes.auth import require_admin
from app.schemas.users import (
    PremiumSchoolLevelsUpdate,
    UserListItem,
    UserListResponse,
    UserRoleUpdate,
)

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/users", response_model=UserListResponse)
def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users so an admin can manage their tiers. Admin-only."""
    users = db.query(User).order_by(User.id).all()
    return {"data": [UserListItem.model_validate(u) for u in users]}


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
    if wanted:
        known = {
            sl_id
            for (sl_id,) in db.query(SchoolLevel.id).filter(SchoolLevel.id.in_(wanted))
        }
        unknown = sorted(wanted - known)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown school level id(s): {', '.join(map(str, unknown))}",
            )

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
