"""Gifts: credits from the giver's monthly allowance, or a Pro/Max plan paid
from their wallet, for someone else.

A gift is a single-use link (emailed, and shown to the giver to pass on):
emails are not verified for every sign-in, so a gift is claimed by whoever
opens the link signed in, never matched to an account by address.

- Credits are counted as used in the giver's month the moment they are
  given (usage.meter adds them), so nobody gives what they don't have. Only
  paid plans can give credits (free accounts would farm them). Claimed, they
  last GIFT_CREDIT_DAYS and are spent before the recipient's extra credits.
- A plan is paid when given. Claimed: a Free account gets it for the period
  (not renewing; it lapses to Free after); the same plan is extended; Pro to
  Max upgrades, with the unused Pro time refunded to the recipient; a higher
  plan than the gift is refused (the giver can cancel for a refund).
- Unclaimed after GIFT_CLAIM_DAYS, or cancelled: a plan's price goes back to
  the giver; credits were this month's allowance and simply lapse.
"""
import secrets as secrets_mod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Gift, Subscription
from app.services.plans import catalog, subscriptions, usage
from app.services.wallet import ledger, to_micro

VIVID = "vivid"


class GiftError(Exception):
    """A request that cannot be done; `code` for clients, str() to show."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def status_of(gift: Gift) -> str:
    """pending | claimed | cancelled | expired (unclaimed past claim_by)"""
    if gift.cancelled_at:
        return "cancelled"
    if gift.claimed_at:
        return "claimed"
    return "expired" if _aware(gift.claim_by) <= _now() else "pending"


async def balance(db: AsyncSession, user_id: str) -> int:
    """Unexpired gifted credit tokens the user can spend."""
    q = select(func.coalesce(func.sum(Gift.remaining), 0)).where(
        Gift.claimed_by == user_id, Gift.kind == "credits", Gift.remaining > 0, Gift.use_by > _now())
    return int((await db.execute(q)).scalar_one() or 0)


async def spend(db: AsyncSession, user_id: str, tokens: int) -> int:
    """Take up to `tokens` from the user's gifted credits, soonest to expire
    first. Returns how many were taken. The caller commits."""
    if tokens <= 0:
        return 0
    rows = (await db.execute(select(Gift).where(
        Gift.claimed_by == user_id, Gift.kind == "credits", Gift.remaining > 0, Gift.use_by > _now())
        .order_by(Gift.use_by).with_for_update())).scalars()
    taken = 0
    for gift in rows:
        use = min(gift.remaining, tokens - taken)
        gift.remaining -= use
        taken += use
        if taken >= tokens:
            break
    return taken


async def _pending_count(db: AsyncSession, user_id: str) -> int:
    q = select(func.count()).select_from(Gift).where(
        Gift.from_user == user_id, Gift.claimed_at.is_(None), Gift.cancelled_at.is_(None),
        Gift.claim_by > _now())
    return int((await db.execute(q)).scalar_one())


def _new(from_user: str, kind: str, email: str, message: str | None) -> Gift:
    return Gift(from_user=from_user, kind=kind, email=email, message=(message or "").strip()[:280] or None,
                token=secrets_mod.token_urlsafe(24), claim_by=_now() + timedelta(days=settings.GIFT_CLAIM_DAYS))


async def give_credits(db: AsyncSession, user_id: str, email: str, credits: int,
                       message: str | None = None) -> Gift:
    """The caller commits."""
    if credits < 1:
        raise GiftError("bad_amount", "Give at least 1 credit.")
    account = await usage.account_for(db, user_id)
    if account.plan.id == catalog.FREE:
        raise GiftError("plan_required", "Gifting credits comes with Pro and Max.", 402)
    if await _pending_count(db, user_id) >= settings.GIFT_MAX_PENDING:
        raise GiftError("too_many_gifts", "You have many gifts waiting to be claimed. Cancel some first.", 409)
    meter = await usage.meter(db, account)
    left = max(meter.month_limit - meter.month_used, 0)
    tokens = catalog.to_tokens(credits)
    if tokens > left:
        raise GiftError("not_enough_credits",
                        f"You have {catalog.to_credits(left):g} credits left this month.", 409)
    gift = _new(user_id, "credits", email, message)
    gift.tokens = tokens
    db.add(gift)
    await db.flush()
    return gift


async def give_plan(db: AsyncSession, user_id: str, email: str, plan_id: str, yearly: bool,
                    message: str | None = None) -> Gift:
    """Paid now from the giver's wallet (ledger.InsufficientFunds when short).
    The caller commits."""
    if plan_id not in (catalog.PRO, catalog.MAX):
        raise GiftError("bad_plan", "Gift Pro or Max.")
    if await _pending_count(db, user_id) >= settings.GIFT_MAX_PENDING:
        raise GiftError("too_many_gifts", "You have many gifts waiting to be claimed. Cancel some first.", 409)
    plan = catalog.get(plan_id)
    price = to_micro(plan.charge_usd(yearly))
    gift = _new(user_id, "plan", email, message)
    gift.plan, gift.yearly, gift.amount_micro = plan_id, yearly, price
    db.add(gift)
    await db.flush()
    await ledger.debit(db, user_id, price, ledger.GIFT, VIVID, f"gift:{gift.id}", ref=plan_id,
                       original_amount=str(plan.charge_usd(yearly)), original_currency="USD",
                       description=f"{plan.name} for {'a year' if yearly else 'a month'}, as a gift")
    return gift


async def _refund(db: AsyncSession, gift: Gift, why: str) -> None:
    if gift.kind == "plan" and gift.amount_micro > 0:
        await ledger.credit(db, gift.from_user, gift.amount_micro, ledger.REFUND, VIVID,
                            f"gift-refund:{gift.id}", ref=gift.plan,
                            description=f"Gift of {catalog.get(gift.plan).name} {why}")


async def cancel(db: AsyncSession, user_id: str, gift_id: str) -> Gift:
    """The giver takes back an unclaimed gift. The caller commits."""
    gift = await db.get(Gift, gift_id)
    if gift is None or gift.from_user != user_id:
        raise GiftError("not_found", "No such gift.", 404)
    if status_of(gift) == "claimed":
        raise GiftError("already_claimed", "That gift was already claimed.", 409)
    if gift.cancelled_at is None:
        gift.cancelled_at = _now()
        await _refund(db, gift, "cancelled")
    return gift


async def expire_due(db: AsyncSession) -> int:
    """Unclaimed gifts past their claim date: a plan's price back to the
    giver. From the hourly plans pass. The caller commits."""
    rows = (await db.execute(select(Gift).where(
        Gift.claimed_at.is_(None), Gift.cancelled_at.is_(None), Gift.claim_by <= _now()))).scalars()
    n = 0
    for gift in list(rows):
        gift.cancelled_at = _now()
        await _refund(db, gift, "not claimed in time")
        n += 1
    return n


async def by_token(db: AsyncSession, token: str) -> Gift:
    gift = (await db.execute(select(Gift).where(Gift.token == token))).scalar_one_or_none()
    if gift is None:
        raise GiftError("not_found", "This gift link is not valid.", 404)
    return gift


@dataclass
class Claimed:
    gift: Gift
    #: What the recipient's plan became, for a plan gift.
    subscription: Subscription | None = None


async def claim(db: AsyncSession, user_id: str, token: str) -> Claimed:
    """The caller commits."""
    gift = await by_token(db, token)
    status = status_of(gift)
    if status != "pending":
        raise GiftError("gift_gone", {"claimed": "This gift was already claimed.",
                                      "cancelled": "This gift was cancelled.",
                                      "expired": "This gift has expired."}[status], 410)
    if gift.from_user == user_id:
        raise GiftError("own_gift", "That's your own gift. Send the link to the person it's for.", 409)
    now = _now()
    sub = None
    if gift.kind == "credits":
        gift.remaining = gift.tokens
        gift.use_by = now + timedelta(days=settings.GIFT_CREDIT_DAYS)
    else:
        sub = await _grant_plan(db, user_id, gift, now)
    gift.claimed_by, gift.claimed_at = user_id, now
    return Claimed(gift, sub)


_RANK = {catalog.FREE: 0, catalog.PRO: 1, catalog.MAX: 2}


async def _grant_plan(db: AsyncSession, user_id: str, gift: Gift, now: datetime) -> Subscription:
    period = timedelta(days=365 if gift.yearly else 30)
    current = await usage.active_subscription(db, user_id)
    sub = await db.get(Subscription, user_id)
    if current is not None and _RANK.get(current.plan, 0) > _RANK[gift.plan]:
        raise GiftError("already_higher",
                        f"You're already on {catalog.get(current.plan).name}. Ask them to cancel the gift "
                        "for a refund, or to send Max.", 409)
    if current is not None and current.plan == gift.plan and current.status in ("active", "canceled"):
        # The same plan: more time on it.
        current.period_end = _aware(current.period_end) + period
        return current
    if current is not None and current.status == "active":
        # Pro to Max: the unused Pro time back to the recipient's wallet.
        credit = subscriptions._unused_credit_micro(current, now)
        if credit:
            await ledger.credit(db, user_id, credit, ledger.REFUND, VIVID, f"gift-unused:{gift.id}",
                                ref=current.plan, description=f"Unused {catalog.get(current.plan).name} time")
    if sub is None:
        sub = Subscription(user_id=user_id, plan=gift.plan)
        db.add(sub)
    sub.plan, sub.seats, sub.yearly = gift.plan, 1, gift.yearly
    # A gift does not renew on the recipient's wallet; they may subscribe.
    sub.status, sub.auto_renew, sub.grace_until = "active", False, None
    sub.period_start, sub.period_end = now, now + period
    return sub
