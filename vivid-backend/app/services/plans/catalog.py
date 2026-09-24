"""The plans, from settings, so the numbers can be tuned without a deploy
(see `python -m app.scripts.token_economics`)."""
from dataclasses import dataclass

from app.core.config import settings

FREE, PRO, TEAM = "free", "pro", "team"


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
    window_tokens: int
    month_tokens: int
    per_seat: bool = False

    def window_for(self, seats: int) -> int:
        return self.window_tokens * (seats if self.per_seat else 1)

    def month_for(self, seats: int) -> int:
        return self.month_tokens * (seats if self.per_seat else 1)

    def charge_usd(self, yearly: bool, seats: int) -> float:
        per_month = self.yearly_price_usd if yearly else self.price_usd
        return per_month * (12 if yearly else 1) * (seats if self.per_seat else 1)


def plans() -> dict[str, Plan]:
    s = settings
    return {
        FREE: Plan(FREE, "Free", 0.0, 0.0, s.PLAN_FREE_APPS, s.PLAN_FREE_WINDOW_TOKENS,
                   s.PLAN_FREE_MONTH_TOKENS),
        PRO: Plan(PRO, "Pro", s.PLAN_PRO_PRICE_USD, s.PLAN_PRO_YEARLY_PRICE_USD, None,
                  s.PLAN_PRO_WINDOW_TOKENS, s.PLAN_PRO_MONTH_TOKENS),
        TEAM: Plan(TEAM, "Team", s.PLAN_TEAM_PRICE_USD, s.PLAN_TEAM_YEARLY_PRICE_USD, None,
                   s.PLAN_TEAM_WINDOW_TOKENS, s.PLAN_TEAM_MONTH_TOKENS, per_seat=True),
    }


def get(plan_id: str) -> Plan:
    return plans().get(plan_id) or plans()[FREE]


def pack_price_usd(tokens: int) -> float:
    return round(tokens / 1_000_000 * settings.PLAN_EXTRA_TOKEN_PRICE_USD, 2)
