from datetime import datetime

from pydantic import BaseModel, field_validator

from app.schemas.reference import SchoolLevelResponse

# DB role values. The frontend labels 'public' as "Normal"; the stored value
# stays 'public' to avoid migrating existing rows. Premium is *not* a role — it
# is the set of school levels in `premium_school_levels`.
VALID_ROLES = ("admin", "public")


class UserListItem(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str
    premium_school_levels: list[SchoolLevelResponse] = []
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


class PremiumSchoolLevelsUpdate(BaseModel):
    """The complete set of school levels a user should have premium access to —
    a replace, not a merge, so one payload can both grant and revoke."""

    school_level_ids: list[int]
