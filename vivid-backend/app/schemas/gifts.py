from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GiftIn(BaseModel):
    kind: Literal["credits", "plan"]
    #: Where the gift link is emailed. The link is also returned: whoever
    #: opens it signed in claims the gift.
    email: str = Field(max_length=320)
    #: kind credits: how many, from what is left of your month.
    credits: int | None = Field(default=None, ge=1, le=10_000)
    #: kind plan: pro | max, a month or a year.
    plan: Literal["pro", "max"] | None = None
    yearly: bool = False
    message: str | None = Field(default=None, max_length=280)


class GiftOut(BaseModel):
    id: str
    kind: str
    email: str
    credits: float | None = None
    plan: str | None = None
    yearly: bool = False
    amount_usd: float | None = None
    message: str | None = None
    #: pending | claimed | cancelled | expired
    status: str
    created_at: datetime
    claim_by: datetime
    #: Sent gifts only: the claim link, to pass on another way if need be.
    url: str | None = None
    #: This time only: whether the email went out.
    emailed: bool | None = None
    #: Received credit gifts: what is left, and until when.
    remaining_credits: float | None = None
    use_by: datetime | None = None
    #: The other person: the giver on a received gift.
    from_name: str | None = None


class GiftsOut(BaseModel):
    sent: list[GiftOut]
    received: list[GiftOut]
    #: Gifted credits you can spend now (they are spent before extra credits).
    gift_credits: float


class GiftPreviewOut(BaseModel):
    """What a gift link shows before it is claimed."""
    from_name: str | None
    kind: str
    credits: float | None = None
    plan: str | None = None
    yearly: bool = False
    message: str | None = None
    status: str


class GiftClaimedOut(BaseModel):
    gift: GiftOut
    #: A plan gift: the plan you are on now, and until when.
    plan: str | None = None
    plan_until: datetime | None = None
