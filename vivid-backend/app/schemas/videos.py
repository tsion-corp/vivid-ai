from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class VideoIn(BaseModel):
    #: A preset (default, polished, yc-parody, chaotic, deadpan, cinematic,
    #: app-store) or a short freeform direction of feel; inferred when empty.
    tone: str | None = Field(default=None, max_length=80)
    format: Literal["landscape", "vertical", "square"] = "landscape"
    #: What to focus on, in the person's words.
    direction: str | None = Field(default=None, max_length=300)


class VideoOut(BaseModel):
    id: str
    #: queued | composing | rendering | done | failed | canceled
    status: str
    tone: str | None = None
    format: str
    direction: str | None = None
    duration_s: float | None = None
    #: When done: 7-day links to the MP4 and its poster (JPG).
    video_url: str | None = None
    poster_url: str | None = None
    #: 1-3 sentences to post it with.
    share_copy: str | None = None
    error: str | None = None
    #: allowance (included in the plan) | wallet (paid, refunded if it fails)
    paid_with: str
    amount_usd: float | None = None
    created_at: datetime
    finished_at: datetime | None = None


class VideoAllowanceOut(BaseModel):
    plan: str
    included: int
    used: int
    left: int
    #: One more beyond the allowance, from the wallet.
    price_usd: float
    resets_at: datetime
