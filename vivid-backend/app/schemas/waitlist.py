from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class WaitlistJoin(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr = Field(max_length=320)
    use_case: str = Field(min_length=1, max_length=4000)
    heard_from: str = Field(min_length=1, max_length=160)

    @field_validator("first_name", "last_name", "use_case", "heard_from", mode="before")
    @classmethod
    def _strip(cls, value):
        # "   " would pass min_length, so blank-after-strip fails here instead.
        return value.strip() if isinstance(value, str) else value


class WaitlistJoined(BaseModel):
    """The public answer. Deliberately carries nothing from the row: the
    form is unauthenticated, so it must not read back anyone's details."""
    ok: bool = True
    #: True when this email was already on the list; its details were updated.
    already_joined: bool


class WaitlistEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    first_name: str
    last_name: str
    email: str
    use_case: str
    heard_from: str
    created_at: datetime
    updated_at: datetime


class WaitlistPage(BaseModel):
    total: int
    entries: list[WaitlistEntryOut]
