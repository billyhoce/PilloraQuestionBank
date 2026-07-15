from datetime import datetime

from pydantic import BaseModel, field_validator

# DB role values. The frontend labels 'public' as "Normal"; the stored value
# stays 'public' to avoid migrating existing rows.
VALID_ROLES = ("admin", "public", "premium")


class UserListItem(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    data: list[UserListItem]


class UserRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {', '.join(VALID_ROLES)}")
        return v
