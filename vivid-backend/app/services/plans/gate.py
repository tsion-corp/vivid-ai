"""Whether work may start, and what it costs afterwards.

A turn is checked when it starts and always allowed to finish: it is
refused only if the account is already past its window or month allowance
and has no extra tokens. After the turn, whatever it used beyond the
allowance comes off the extra tokens.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BuilderProject
from app.services.plans import usage
from app.services.wallet import ledger


@dataclass
class TurnCheck:
    ok: bool
    account: usage.Account
    meter: usage.Meter
    extra_tokens: int
    #: The project is past the plan's app limit (after a downgrade).
    read_only: bool = False

    def body(self) -> dict:
        return {"plan": self.account.plan.id,
                "window_used": self.meter.window_used, "window_limit": self.meter.window_limit,
                "window_resets_at": _iso(self.meter.window_resets_at),
                "month_used": self.meter.month_used, "month_limit": self.meter.month_limit,
                "month_resets_at": _iso(self.meter.month_resets_at),
                "extra_tokens": self.extra_tokens,
                "options": ["wait", "buy_tokens", "upgrade"]}


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def active_projects(db: AsyncSession, user_id: str, limit: int) -> list[str]:
    """On a plan with an app limit, the projects that may still run turns:
    the most recently updated `limit` of them."""
    rows = await db.execute(select(BuilderProject.id).where(BuilderProject.owner_id == user_id)
                            .order_by(BuilderProject.updated_at.desc()).limit(limit))
    return list(rows.scalars())


async def can_start_turn(db: AsyncSession, user_id: str, project_id: str) -> TurnCheck:
    account = await usage.account_for(db, user_id)
    m = await usage.meter(db, account)
    wallet = await ledger.wallet_for(db, account.owner_id)
    read_only = False
    if account.plan.max_apps is not None:
        read_only = project_id not in await active_projects(db, user_id, account.plan.max_apps)
    ok = not read_only and (not m.over or wallet.extra_tokens > 0)
    return TurnCheck(ok, account, m, wallet.extra_tokens, read_only)


async def settle_turn(db: AsyncSession, check: TurnCheck) -> int:
    """Take the turn's tokens beyond the allowance off the extra tokens.
    Returns how many were taken. The caller commits."""
    before = check.meter
    after = await usage.meter(db, check.account)
    over_before = max(before.window_used - before.window_limit,
                      before.month_used - before.month_limit, 0)
    over_after = max(after.window_used - after.window_limit,
                     after.month_used - after.month_limit, 0)
    beyond = max(over_after - over_before, 0)
    if beyond <= 0:
        return 0
    wallet = await ledger.wallet_for(db, check.account.owner_id, lock=True)
    taken = min(beyond, wallet.extra_tokens)
    wallet.extra_tokens -= taken
    return taken


async def can_create_project(db: AsyncSession, user_id: str) -> tuple[bool, usage.Account, int]:
    account = await usage.account_for(db, user_id)
    owned = int((await db.execute(select(func.count()).select_from(BuilderProject)
                                  .where(BuilderProject.owner_id == user_id))).scalar_one())
    limit = account.plan.max_apps
    return (limit is None or owned < limit), account, owned
