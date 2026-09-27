"""Gifting credits or a plan to someone else (services/plans/gifts.py)."""
import html
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_session_user
from app.api.routes.wallet import _insufficient
from app.core.config import settings
from app.core.errors import APIError
from app.db.models import Gift, User
from app.schemas.gifts import GiftClaimedOut, GiftIn, GiftOut, GiftPreviewOut, GiftsOut
from app.services import mail, push
from app.services.plans import catalog, gifts
from app.services.wallet import ledger

log = logging.getLogger("vivid.gifts")

router = APIRouter(tags=["gifts"])


def _url(gift: Gift) -> str:
    return f"{settings.WEB_BASE_URL.rstrip('/')}/gift/{gift.token}"


def _what(gift: Gift) -> str:
    if gift.kind == "credits":
        return f"{catalog.to_credits(gift.tokens):g} Vivid credits"
    return f"Vivid {catalog.get(gift.plan).name} for {'a year' if gift.yearly else 'a month'}"


def _out(gift: Gift, sent: bool, emailed: bool | None = None, from_name: str | None = None) -> GiftOut:
    return GiftOut(
        id=gift.id, kind=gift.kind, email=gift.email if sent else "",
        credits=catalog.to_credits(gift.tokens) if gift.kind == "credits" else None,
        plan=gift.plan, yearly=gift.yearly,
        amount_usd=gift.amount_micro / 1_000_000 if gift.kind == "plan" and sent else None,
        message=gift.message, status=gifts.status_of(gift), created_at=gift.created_at, claim_by=gift.claim_by,
        url=_url(gift) if sent and gifts.status_of(gift) == "pending" else None, emailed=emailed,
        remaining_credits=catalog.to_credits(gift.remaining) if not sent and gift.kind == "credits" else None,
        use_by=gift.use_by if not sent else None, from_name=from_name)


def _error(e: gifts.GiftError) -> APIError:
    return APIError(e.status, e.code, str(e))


@router.post("/me/gifts", response_model=GiftOut, status_code=201)
async def give(body: GiftIn, user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    """Give credits (from what is left of your month; Pro and Max) or a plan
    (paid now from your wallet). Answers the gift with its claim link."""
    email = body.email.strip().lower()
    if not mail.valid_address(email):
        raise APIError(400, "bad_email", "That doesn't look like an email address.")
    try:
        if body.kind == "credits":
            if not body.credits:
                raise APIError(400, "bad_amount", "How many credits?")
            gift = await gifts.give_credits(db, user.id, email, body.credits, body.message)
        else:
            if not body.plan:
                raise APIError(400, "bad_plan", "Which plan?")
            gift = await gifts.give_plan(db, user.id, email, body.plan, body.yearly, body.message)
    except gifts.GiftError as e:
        await db.rollback()
        raise _error(e)
    except ledger.InsufficientFunds as e:
        await db.rollback()
        raise _insufficient(e)
    await db.commit()

    giver = user.name or "Someone"
    note = f'\n\nThey wrote: "{gift.message}"' if gift.message else ""
    text = (f"{giver} sent you {_what(gift)}.{note}\n\nOpen this link to claim it (it works once, for "
            f"{settings.GIFT_CLAIM_DAYS} days):\n{_url(gift)}\n")
    body_html = (f"<p>{html.escape(giver)} sent you <b>{html.escape(_what(gift))}</b>.</p>"
                 + (f"<p style=\"font-style:italic\">&ldquo;{html.escape(gift.message)}&rdquo;</p>" if gift.message else "")
                 + f"<p style=\"color:#6b6880;font-size:13px\">The link works once, for {settings.GIFT_CLAIM_DAYS} days.</p>")
    emailed = await mail.send(email, f"{giver} sent you a gift on Vivid", text,
                              mail.layout(f"A gift from {giver}", body_html, ("Claim your gift", _url(gift))))
    return _out(gift, sent=True, emailed=emailed)


@router.get("/me/gifts", response_model=GiftsOut)
async def my_gifts(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Gift).where(or_(Gift.from_user == user.id, Gift.claimed_by == user.id))
                             .order_by(Gift.created_at.desc()).limit(100))).scalars()
    rows = list(rows)
    names = {u.id: u.name for u in (await db.execute(
        select(User).where(User.id.in_({g.from_user for g in rows})))).scalars()}
    sent = [_out(g, sent=True) for g in rows if g.from_user == user.id]
    received = [_out(g, sent=False, from_name=names.get(g.from_user)) for g in rows if g.claimed_by == user.id]
    return GiftsOut(sent=sent, received=received,
                    gift_credits=catalog.to_credits(await gifts.balance(db, user.id)))


@router.delete("/me/gifts/{gift_id}", status_code=204)
async def cancel_gift(gift_id: str, user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    """Take back an unclaimed gift; a plan's price goes back to your wallet."""
    try:
        await gifts.cancel(db, user.id, gift_id)
    except gifts.GiftError as e:
        raise _error(e)
    await db.commit()
    return Response(status_code=204)


@router.get("/gifts/{token}", response_model=GiftPreviewOut)
async def preview_gift(token: str, db: AsyncSession = Depends(get_db)):
    """What a gift link shows before sign-in (no auth)."""
    try:
        gift = await gifts.by_token(db, token)
    except gifts.GiftError as e:
        raise _error(e)
    giver = await db.get(User, gift.from_user)
    return GiftPreviewOut(from_name=giver.name if giver else None, kind=gift.kind,
                          credits=catalog.to_credits(gift.tokens) if gift.kind == "credits" else None,
                          plan=gift.plan, yearly=gift.yearly, message=gift.message, status=gifts.status_of(gift))


@router.post("/gifts/{token}/claim", response_model=GiftClaimedOut)
async def claim_gift(token: str, user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    try:
        claimed = await gifts.claim(db, user.id, token)
    except gifts.GiftError as e:
        await db.rollback()
        raise _error(e)
    await db.commit()
    gift = claimed.gift
    push.send_later(gift.from_user, "Your gift was claimed",
                    f"{user.name or 'They'} claimed {_what(gift)}.", {"type": "gift_claimed"})
    giver = await db.get(User, gift.from_user)
    sub = claimed.subscription
    return GiftClaimedOut(gift=_out(gift, sent=False, from_name=giver.name if giver else None),
                          plan=sub.plan if sub else None, plan_until=sub.period_end if sub else None)
