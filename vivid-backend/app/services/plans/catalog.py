"""The plans, from settings, so the numbers can be tuned without a deploy
(see `python -m app.scripts.token_economics`).

Users see credits; usage is recorded in tokens. One credit is
PLAN_TOKENS_PER_CREDIT tokens (500k by default), and the conversion happens
only here: allowances are stated in credits and compared in tokens.
"""
from dataclasses import dataclass

from app.core.config import settings

FREE, PRO, TEAM = "free", "pro", "team"


def tokens_per_credit() -> int:
    return max(int(settings.PLAN_TOKENS_PER_CREDIT), 1)


def to_credits(tokens: int) -> float:
    """Tokens as credits, to two decimals (what users see)."""
    return round(tokens / tokens_per_credit(), 2)


def to_tokens(credits: float) -> int:
    return int(round(credits * tokens_per_credit()))


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    #: USD per month (per seat on Team); yearly is the per-month price when
    #: paid for twelve months at once.
    price_usd: float
    yearly_price_usd: float
    #: None = unlimited.
    max_apps: int | None
    window_credits: float
    month_credits: float
    per_seat: bool = False

    @property
    def window_tokens(self) -> int:
        return to_tokens(self.window_credits)

    @property
    def month_tokens(self) -> int:
        return to_tokens(self.month_credits)

    def window_for(self, seats: int) -> int:
        """The window allowance in tokens, for this many seats."""
        return self.window_tokens * (seats if self.per_seat else 1)

    def month_for(self, seats: int) -> int:
        return self.month_tokens * (seats if self.per_seat else 1)

    def charge_usd(self, yearly: bool, seats: int) -> float:
        per_month = self.yearly_price_usd if yearly else self.price_usd
        return per_month * (12 if yearly else 1) * (seats if self.per_seat else 1)


def plans() -> dict[str, Plan]:
    s = settings
    return {
        FREE: Plan(FREE, "Free", 0.0, 0.0, s.PLAN_FREE_APPS, s.PLAN_FREE_WINDOW_CREDITS,
                   s.PLAN_FREE_MONTH_CREDITS),
        PRO: Plan(PRO, "Pro", s.PLAN_PRO_PRICE_USD, s.PLAN_PRO_YEARLY_PRICE_USD, None,
                  s.PLAN_PRO_WINDOW_CREDITS, s.PLAN_PRO_MONTH_CREDITS),
        TEAM: Plan(TEAM, "Team", s.PLAN_TEAM_PRICE_USD, s.PLAN_TEAM_YEARLY_PRICE_USD, None,
                   s.PLAN_TEAM_WINDOW_CREDITS, s.PLAN_TEAM_MONTH_CREDITS, per_seat=True),
    }


def get(plan_id: str) -> Plan:
    return plans().get(plan_id) or plans()[FREE]


def pack_price_usd(credits: int) -> float:
    return round(credits * settings.PLAN_CREDIT_PRICE_USD, 2)
