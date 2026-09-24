"""Tokens used by an account: its own projects. Builder usage rows are per
project; the account is the project's owner."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import usage as builder_usage
from app.core.config import settings
from app.db.models import BuilderProject, BuilderUsageEvent, Subscription
from app.services.plans import catalog


@dataclass
class Account:
    """Whose allowance a user's work draws on."""
    #: The paying user.
    owner_id: str
    #: Whose projects count against it.
    user_ids: list[str]
    plan: catalog.Plan
    subscription: Subscription | None
    #: Start of the monthly allowance: the paid period, or the calendar month.
    month_start: datetime


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def active_subscription(db: AsyncSession, user_id: str) -> Subscription | None:
    sub = await db.get(Subscription, user_id)
    if sub is None:
        return None
    now = datetime.now(timezone.utc)
    if sub.status == "grace" and sub.grace_until and _aware(sub.grace_until) < now:
        return None
    if sub.status == "canceled" and _aware(sub.period_end) < now:
        return None
    return sub


async def account_for(db: AsyncSession, user_id: str) -> Account:
    sub = await active_subscription(db, user_id)
    if sub is not None:
        return Account(user_id, [user_id], catalog.get(sub.plan), sub, _aware(sub.period_start))
    return Account(user_id, [user_id], catalog.get(catalog.FREE), None,
                   builder_usage.month_start())


async def tokens_since(db: AsyncSession, user_ids: list[str], since: datetime) -> int:
    """Model tokens plus images at their token equivalent."""
    image_tokens = settings.PLAN_IMAGE_TOKEN_EQUIVALENT
    q = (select(func.coalesce(func.sum(case(
            (BuilderUsageEvent.unit == "images", BuilderUsageEvent.quantity * image_tokens),
            else_=BuilderUsageEvent.quantity)), 0))
         .join(BuilderProject, BuilderProject.id == BuilderUsageEvent.project_id)
         .where(BuilderProject.owner_id.in_(user_ids), BuilderUsageEvent.kind == "model",
                BuilderUsageEvent.unit.in_(("tokens", "images")),
                BuilderUsageEvent.created_at >= since))
    return int((await db.execute(q)).scalar_one() or 0)


@dataclass
class Meter:
    window_used: int
    window_limit: int
    window_resets_at: datetime
    month_used: int
    month_limit: int
    month_resets_at: datetime

    @property
    def over(self) -> bool:
        return self.window_used >= self.window_limit or self.month_used >= self.month_limit


async def _oldest_in_window(db: AsyncSession, user_ids: list[str], since: datetime) -> datetime | None:
    q = (select(func.min(BuilderUsageEvent.created_at))
         .join(BuilderProject, BuilderProject.id == BuilderUsageEvent.project_id)
         .where(BuilderProject.owner_id.in_(user_ids), BuilderUsageEvent.kind == "model",
                BuilderUsageEvent.created_at >= since))
    return (await db.execute(q)).scalar_one_or_none()


def _next_month(start: datetime) -> datetime:
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return start.replace(year=year, month=month)


async def meter(db: AsyncSession, account: Account) -> Meter:
    now = datetime.now(timezone.utc)
    window = timedelta(hours=settings.PLAN_WINDOW_HOURS)
    since = now - window
    window_used = await tokens_since(db, account.user_ids, since)
    oldest = await _oldest_in_window(db, account.user_ids, since)
    # A rolling window: capacity comes back as the oldest usage in it ages out.
    resets = (_aware(oldest) + window) if oldest else now
    month_used = await tokens_since(db, account.user_ids, account.month_start)
    month_resets = (_aware(account.subscription.period_end) if account.subscription
                    else _next_month(account.month_start))
    return Meter(window_used, account.plan.window_tokens, resets,
                 month_used, account.plan.month_tokens, month_resets)
