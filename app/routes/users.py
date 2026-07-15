from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.orm import User
from app.routes.auth import require_admin
from app.schemas.users import UserListItem, UserListResponse, UserRoleUpdate

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
    """Change a user's tier (admin / public / premium). Admin-only.

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
