"""Subscribing, renewing and cancelling, all paid from the wallet.

- Subscribing charges the whole period (a month, or twelve at the yearly
  rate) up front. Changing plan mid-period credits the unused part of the
  current one first, so an upgrade costs only the difference.
- Cancelling keeps the plan to the end of the period, then it lapses to Free.
- Renewal runs from a daily poller: the wallet pays the next period; when it
  cannot, the plan stays in grace for BILLING_GRACE_DAYS, then lapses.
- Extra credits are bought in packs, added to the account's wallet.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Subscription
from app.db.session import async_session
from app.services.plans import catalog
from app.services.wallet import ledger, to_micro

log = logging.getLogger("vivid.plans")

VIVID = "vivid"


class PlanError(Exception):
    """A request that cannot be done; str() is safe to show."""


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _period(start: datetime, yearly: bool) -> datetime:
    return start + (timedelta(days=365) if yearly else timedelta(days=30))


def _unused_credit_micro(sub: Subscription, now: datetime) -> int:
    """The unused part of the current paid period, in micro-USD."""
    if sub.status != "active":
        return 0
    start, end = _aware(sub.period_start), _aware(sub.period_end)
    total = (end - start).total_seconds()
    left = (end - now).total_seconds()
    if total <= 0 or left <= 0:
        return 0
    paid = catalog.get(sub.plan).charge_usd(sub.yearly)
    return int(to_micro(paid) * left / total)


async def subscribe(db: AsyncSession, user_id: str, plan_id: str,
                    yearly: bool = False) -> Subscription:
    """Start or change a paid plan now. Raises ledger.InsufficientFunds when
    the wallet cannot pay the difference. The caller commits."""
    if plan_id not in (catalog.PRO, catalog.MAX):
        raise PlanError("pick Pro or Max; Free is what you get by cancelling")
    plan = catalog.get(plan_id)
    now = datetime.now(timezone.utc)
    sub = await db.get(Subscription, user_id)
    credit = _unused_credit_micro(sub, now) if sub is not None else 0
    price = to_micro(plan.charge_usd(yearly))
    # A plan change is a deliberate action, never a retried delivery: each
    # gets its own reference (two changes in one second must both be paid).
    change_ref = uuid.uuid4().hex
    if credit:
        await ledger.credit(db, user_id, credit, ledger.REFUND, VIVID,
                            f"plan-unused:{user_id}:{change_ref}", ref=sub.plan,
                            description=f"Unused {catalog.get(sub.plan).name} time")
    await ledger.debit(db, user_id, price, ledger.PLAN, VIVID, f"plan:{user_id}:{change_ref}",
                       ref=plan_id, original_amount=str(plan.charge_usd(yearly)),
                       original_currency="USD",
                       description=f"{plan.name}, "
                                   f"{'1 year' if yearly else '1 month'}")
    if sub is None:
        sub = Subscription(user_id=user_id, plan=plan_id)
        db.add(sub)
    sub.plan, sub.seats, sub.yearly = plan_id, 1, yearly
    sub.status, sub.auto_renew, sub.grace_until = "active", True, None
    sub.period_start, sub.period_end = now, _period(now, yearly)
    return sub


async def cancel(db: AsyncSession, user_id: str) -> Subscription | None:
    """Keep the plan to the end of the period, then lapse to Free."""
    sub = await db.get(Subscription, user_id)
    if sub is None:
        return None
    sub.status, sub.auto_renew = "canceled", False
    return sub


async def buy_pack(db: AsyncSession, user_id: str, credits: int, owner_id: str | None = None) -> float:
    """Extra credits from the wallet, for the account that pays. Kept as tokens underneath so a turn's exact usage
    can be taken off. Returns the account's extra credits."""
    if credits not in settings.PLAN_CREDIT_PACKS:
        raise PlanError(f"packs are {', '.join(str(p) for p in settings.PLAN_CREDIT_PACKS)} credits")
    price = catalog.pack_price_usd(credits)
    await ledger.debit(db, user_id, to_micro(price), ledger.TOKEN_PACK, VIVID,
                       f"pack:{user_id}:{uuid.uuid4().hex}", ref=str(credits), original_amount=str(price),
                       original_currency="USD", description=f"{credits} extra credits")
    wallet = await ledger.wallet_for(db, owner_id or user_id, lock=True)
    wallet.extra_tokens += catalog.to_tokens(credits)
    return catalog.to_credits(wallet.extra_tokens)


async def renew_due(db: AsyncSession) -> dict:
    """One pass over subscriptions whose period has ended. The caller commits."""
    now = datetime.now(timezone.utc)
    done = {"renewed": 0, "grace": 0, "lapsed": 0}
    rows = (await db.execute(select(Subscription).where(Subscription.period_end <= now))).scalars()
    for sub in list(rows):
        if sub.status == "canceled" or not sub.auto_renew:
            await db.delete(sub)
            done["lapsed"] += 1
            continue
        if sub.status == "grace" and sub.grace_until and _aware(sub.grace_until) < now:
            await db.delete(sub)
            done["lapsed"] += 1
            continue
        plan = catalog.get(sub.plan)
        price = to_micro(plan.charge_usd(sub.yearly))
        period_ref = _aware(sub.period_end).strftime("%Y%m%dT%H%M%S")
        try:
            await ledger.debit(db, sub.user_id, price, ledger.PLAN, VIVID,
                               f"plan-renew:{sub.user_id}:{period_ref}", ref=sub.plan,
                               original_currency="USD", original_amount=str(plan.charge_usd(sub.yearly)),
                               description=f"{plan.name} renewal")
        except ledger.InsufficientFunds:
            if sub.status != "grace":
                sub.status = "grace"
                sub.grace_until = now + timedelta(days=settings.BILLING_GRACE_DAYS)
                done["grace"] += 1
            continue
        start = _aware(sub.period_end)
        sub.period_start, sub.period_end = start, _period(start, sub.yearly)
        sub.status, sub.grace_until = "active", None
        done["renewed"] += 1
    return done


_LOCK = "plans:renew"


async def renewer(redis, interval: float = 3600) -> None:
    """Hourly (renewals are due at any hour); one process per pass."""
    while True:
        await asyncio.sleep(interval)
        try:
            if not await redis.set(_LOCK, "1", nx=True, ex=int(interval) - 60):
                continue
        except Exception:
            pass
        try:
            async with async_session() as db:
                result = await renew_due(db)
                await db.commit()
            if any(result.values()):
                log.info("plan renewals: %s", result)
            # The same hourly pass removes the money records of accounts
            # deleted more than seven years ago (app/services/account.py).
            from app.services import account
            async with async_session() as db:
                purged = await account.purge_expired(db)
                await db.commit()
            if purged:
                log.info("purged the records of %d accounts deleted over seven years ago", purged)
        except Exception as e:
            log.warning("plan renewal pass failed: %s", e)
