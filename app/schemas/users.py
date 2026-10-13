from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, computed_field, field_validator

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
    last_login_at: Optional[datetime] = None
    papers_generated: int = 0

    # Excluded from the response — only the derived flags below are exposed, so
    # the admin UI can show how an account signs in without seeing the hash.
    password_hash: Optional[str] = Field(default=None, exclude=True)
    google_sub: Optional[str] = Field(default=None, exclude=True)

    @computed_field
    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)

    @computed_field
    @property
    def has_google(self) -> bool:
        return bool(self.google_sub)

    @computed_field
    @property
    def is_invited(self) -> bool:
        """Pre-created by an admin and not yet claimed. Derived from the absence
        of both credentials rather than stored, so it can never disagree with
        whether the account can actually be signed into."""
        return not self.password_hash and not self.google_sub

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    data: list[UserListItem]


class UserCreate(BaseModel):
    """An admin pre-creating an account for someone who has not signed up yet, so
    their premium access is already live the moment they do.

    No password: the row carries no credentials at all until the person claims it
    by registering or signing in with Google on the same address."""

    email: EmailStr
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)
    role: str = "public"
    school_level_ids: list[int] = []

    @field_validator("first_name", "last_name")
    @classmethod
    def trim(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {', '.join(VALID_ROLES)}")
        return v


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
