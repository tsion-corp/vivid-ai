"""The wallet and plans: a user's USD balance with Vivid, how to top it up
(a bank virtual account or crypto addresses), its history, and the builder
plan it pays for.

    GET    /v1/wallet?currency=NGN      balance, shown in USD and one other currency
    GET    /v1/wallet/entries           history, newest first
    GET    /v1/wallet/rates             USD rates for the display currencies
    POST   /v1/wallet/bank-account      the user's naira virtual account (made on first call)
    GET    /v1/wallet/crypto/options    tokens and chains to top up with
    POST   /v1/wallet/crypto/address    the user's address for one option (made on first call)
    POST   /v1/wallet/credit-packs      buy extra builder credits
    GET    /v1/plans                    the plans and their prices
    GET    /v1/me/plan                  the user's plan, usage meters and extra tokens
    POST   /v1/me/plan                  subscribe or change plan (paid from the wallet)
    DELETE /v1/me/plan                  cancel at the end of the period
    GET    /v1/team                     Team: seats and members
    POST   /v1/team/invites             Team: invite by email
    POST   /v1/team/accept              accept an invite sent to this user's email
    DELETE /v1/team/members/{id}
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_session_user
from app.core.config import settings
from app.core.errors import APIError
from app.db.models import BuilderProject, TeamMember, User, WalletFunding
from app.services.plans import catalog, subscriptions, usage
from app.services.wallet import MICRO, crypto_options, dextopus, fx, ledger, pouch

router = APIRouter(tags=["wallet"])
log = logging.getLogger("vivid.wallet")


def _usd(micro: int) -> float:
    return round(micro / MICRO, 6)


async def _display(micro: int, currency: str) -> dict | None:
    try:
        return await fx.display(micro, currency)
    except fx.RatesUnavailable:
        return None


# ------------------------------------------------------------------ wallet
@router.get("/wallet")
async def get_wallet(currency: str = Query("NGN", max_length=3),
                     user: User = Depends(get_session_user),
                     db: AsyncSession = Depends(get_db)):
    wallet = await ledger.wallet_for(db, user.id)
    await db.commit()
    return {"balance_micro": wallet.balance_micro, "balance_usd": _usd(wallet.balance_micro),
            "display": await _display(wallet.balance_micro, currency),
            "currencies": settings.WALLET_DISPLAY_CURRENCIES,
            "extra_credits": catalog.to_credits(wallet.extra_tokens),
            "bank_available": pouch.configured(), "crypto_available": dextopus.configured()}


@router.get("/wallet/entries")
async def wallet_entries(limit: int = Query(50, ge=1, le=200),
                         before: datetime | None = None,
                         user: User = Depends(get_session_user),
                         db: AsyncSession = Depends(get_db)):
    rows = await ledger.entries(db, user.id, limit=limit, before=before)
    return [{"id": e.id, "kind": e.kind, "amount_usd": _usd(e.amount_micro),
             "amount_micro": e.amount_micro, "balance_after_usd": _usd(e.balance_after),
             "original_amount": e.original_amount, "original_currency": e.original_currency,
             "fx_rate": float(e.fx_rate) if e.fx_rate is not None else None,
             "description": e.description, "ref": e.ref, "created_at": e.created_at}
            for e in rows]


@router.get("/wallet/rates")
async def wallet_rates():
    try:
        r = await fx.rates()
    except fx.RatesUnavailable as e:
        raise APIError(503, "rates_unavailable", str(e))
    return {"base": "USD", "as_of": r.as_of,
            "rates": {c: r.per_usd.get(c) for c in settings.WALLET_DISPLAY_CURRENCIES
                      if r.per_usd.get(c)}}


def _bank_out(f: WalletFunding) -> dict:
    return {"account_number": f.address, "account_name": f.account_name,
            "bank_name": f.bank_name, "currency": "NGN", "created_at": f.created_at}


class BankAccountIn(BaseModel):
    #: Only when the bank partner insists on it.
    bvn: str | None = Field(default=None, pattern=r"^\d{11}$")
    phone: str | None = Field(default=None, max_length=20)


@router.post("/wallet/bank-account")
async def bank_account(body: BankAccountIn | None = None,
                       user: User = Depends(get_session_user),
                       db: AsyncSession = Depends(get_db)):
    """The user's naira account; transfers into it credit the wallet."""
    existing = (await db.execute(select(WalletFunding).where(
        WalletFunding.user_id == user.id, WalletFunding.provider == "pouch"))).scalars().first()
    if existing is not None:
        return _bank_out(existing)
    if not pouch.configured():
        raise APIError(503, "not_configured", "Bank transfers are not set up yet.")
    body = body or BankAccountIn()
    email = user.profile_email or (user.email if "@" in (user.email or "") else None)
    try:
        customer_id = await pouch.ensure_customer(user.id, user.name, email, body.phone, body.bvn)
        va = await pouch.create_virtual_account(user.id, customer_id)
    except pouch.PouchError as e:
        message = str(e)
        code = "bvn_required" if "bvn" in message.lower() and not body.bvn else "upstream_error"
        raise APIError(502, code, message)
    funding = WalletFunding(user_id=user.id, provider="pouch", option="bank",
                            external_id=va["id"], customer_id=customer_id,
                            address=va["account_number"], account_name=va.get("account_name"),
                            bank_name=va.get("bank_name"))
    db.add(funding)
    await db.commit()
    return _bank_out(funding)


@router.get("/wallet/crypto/options")
async def crypto_options_list(user: User = Depends(get_session_user),
                              db: AsyncSession = Depends(get_db)):
    mine = {f.option: f.address for f in (await db.execute(select(WalletFunding).where(
        WalletFunding.user_id == user.id, WalletFunding.provider == "dextopus"))).scalars()}
    return {"available": dextopus.configured(),
            "min_usd": settings.WALLET_CRYPTO_MIN_USD,
            "settles_as": "USDC on Base",
            "options": [{"key": o.key, "symbol": o.symbol, "chain": o.chain,
                         "network_note": o.network_note, "address": mine.get(o.key)}
                        for o in crypto_options.OPTIONS]}


class CryptoAddressIn(BaseModel):
    option: str = Field(max_length=32)


@router.post("/wallet/crypto/address")
async def crypto_address(body: CryptoAddressIn, user: User = Depends(get_session_user),
                         db: AsyncSession = Depends(get_db)):
    option = crypto_options.get(body.option)
    if option is None:
        raise APIError(400, "bad_request", "Unknown token or network.")
    existing = (await db.execute(select(WalletFunding).where(
        WalletFunding.user_id == user.id, WalletFunding.provider == "dextopus",
        WalletFunding.option == option.key))).scalars().first()
    if existing is None:
        if not dextopus.configured():
            raise APIError(503, "not_configured", "Crypto top-ups are not set up yet.")
        try:
            data = await dextopus.static_address(user.id, option)
        except dextopus.DextopusError as e:
            raise APIError(502, "upstream_error", str(e))
        existing = WalletFunding(user_id=user.id, provider="dextopus", option=option.key,
                                 external_id=data.get("id") or data["depositAddress"],
                                 address=data["depositAddress"], chain_id=option.chain_id,
                                 asset=option.asset)
        db.add(existing)
        await db.commit()
    return {"option": option.key, "symbol": option.symbol, "chain": option.chain,
            "address": existing.address, "network_note": option.network_note,
            "min_usd": settings.WALLET_CRYPTO_MIN_USD, "settles_as": "USDC on Base"}


class PackIn(BaseModel):
    credits: int


@router.post("/wallet/credit-packs")
async def buy_credit_pack(body: PackIn, user: User = Depends(get_session_user),
                          db: AsyncSession = Depends(get_db)):
    account = await usage.account_for(db, user.id)
    try:
        extra = await subscriptions.buy_pack(db, user.id, body.credits, owner_id=account.owner_id)
    except subscriptions.PlanError as e:
        raise APIError(400, "bad_request", str(e))
    except ledger.InsufficientFunds as e:
        await db.rollback()
        raise _insufficient(e)
    await db.commit()
    return {"extra_credits": extra}


def _insufficient(e: ledger.InsufficientFunds) -> APIError:
    return APIError(402, "insufficient_funds",
                    f"Your wallet has ${_usd(e.balance_micro):,.2f}; this needs "
                    f"${_usd(e.needed_micro):,.2f}. Top up by bank transfer or crypto.")


# ------------------------------------------------------------------- plans
def _plan_out(p: catalog.Plan) -> dict:
    return {"id": p.id, "name": p.name, "price_usd": p.price_usd,
            "yearly_price_usd": p.yearly_price_usd, "per_seat": p.per_seat,
            "max_apps": p.max_apps, "window_credits": p.window_credits,
            "window_hours": settings.PLAN_WINDOW_HOURS, "month_credits": p.month_credits}


@router.get("/plans")
async def list_plans():
    packs = [{"credits": c, "price_usd": catalog.pack_price_usd(c)} for c in settings.PLAN_CREDIT_PACKS]
    try:
        ngn = await fx.rate("NGN")
    except fx.RatesUnavailable:
        ngn = None
    return {"plans": [_plan_out(p) for p in catalog.plans().values()],
            "tokens_per_credit": catalog.tokens_per_credit(),
            "credit_price_usd": settings.PLAN_CREDIT_PRICE_USD,
            "credit_packs": packs, "usd_ngn": ngn}


async def _me_plan(db: AsyncSession, user: User) -> dict:
    account = await usage.account_for(db, user.id)
    m = await usage.meter(db, account)
    wallet = await ledger.wallet_for(db, account.owner_id)
    owned = int((await db.execute(select(func.count()).select_from(BuilderProject).where(
        BuilderProject.owner_id == user.id))).scalar_one())
    sub = account.subscription
    return {"plan": _plan_out(account.plan), "seats": account.seats,
            "team_owner": account.owner_id if account.owner_id != user.id else None,
            "status": sub.status if sub else "active",
            "yearly": bool(sub and sub.yearly),
            "period_end": sub.period_end if sub else None,
            "grace_until": sub.grace_until if sub else None,
            "apps": {"used": owned, "limit": account.plan.max_apps},
            "window": {"used": catalog.to_credits(m.window_used),
                       "limit": catalog.to_credits(m.window_limit),
                       "resets_at": m.window_resets_at, "hours": settings.PLAN_WINDOW_HOURS},
            "month": {"used": catalog.to_credits(m.month_used),
                      "limit": catalog.to_credits(m.month_limit), "resets_at": m.month_resets_at},
            "extra_credits": catalog.to_credits(wallet.extra_tokens)}


@router.get("/me/plan")
async def my_plan(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    out = await _me_plan(db, user)
    await db.commit()
    return out


class PlanIn(BaseModel):
    plan: str
    yearly: bool = False
    seats: int = Field(default=1, ge=1, le=50)


@router.post("/me/plan")
async def change_plan(body: PlanIn, user: User = Depends(get_session_user),
                      db: AsyncSession = Depends(get_db)):
    try:
        await subscriptions.subscribe(db, user.id, body.plan, body.yearly, body.seats)
    except subscriptions.PlanError as e:
        raise APIError(400, "bad_request", str(e))
    except ledger.InsufficientFunds as e:
        await db.rollback()
        raise _insufficient(e)
    await db.commit()
    return await _me_plan(db, user)


@router.delete("/me/plan")
async def cancel_plan(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    await subscriptions.cancel(db, user.id)
    await db.commit()
    return await _me_plan(db, user)


# -------------------------------------------------------------------- team
@router.get("/team")
async def my_team(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    account = await usage.account_for(db, user.id)
    rows = (await db.execute(select(TeamMember).where(
        TeamMember.team_owner_id == account.owner_id).order_by(TeamMember.created_at))).scalars()
    return {"owner": account.owner_id, "is_owner": account.owner_id == user.id,
            "plan": account.plan.id, "seats": account.seats,
            "members": [{"id": m.id, "email": m.email, "status": m.status, "user_id": m.user_id}
                        for m in rows]}


class InviteIn(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/team/invites", status_code=201)
async def invite(body: InviteIn, user: User = Depends(get_session_user),
                 db: AsyncSession = Depends(get_db)):
    account = await usage.account_for(db, user.id)
    if account.plan.id != catalog.TEAM or account.owner_id != user.id:
        raise APIError(403, "forbidden", "Only the owner of a Team plan can invite people.")
    members = (await db.execute(select(func.count()).select_from(TeamMember).where(
        TeamMember.team_owner_id == user.id))).scalar_one()
    if members + 1 >= account.seats:                  # the owner holds a seat
        raise APIError(402, "plan_limit", "Every seat is taken. Add seats to invite more people.")
    email = body.email.strip().lower()
    db.add(TeamMember(team_owner_id=user.id, email=email))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise APIError(409, "conflict", "That person is already invited.")
    return {"email": email, "status": "invited"}


@router.post("/team/accept")
async def accept_invite(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    emails = {e.lower() for e in (user.email, user.profile_email) if e and "@" in e}
    invite_row = (await db.execute(select(TeamMember).where(
        TeamMember.email.in_(emails), TeamMember.status == "invited"))).scalars().first() \
        if emails else None
    if invite_row is None:
        raise APIError(404, "not_found", "No team invite for this account.")
    invite_row.user_id, invite_row.status = user.id, "active"
    await db.commit()
    return {"team_owner": invite_row.team_owner_id, "status": "active"}


@router.delete("/team/members/{member_id}", status_code=204)
async def remove_member(member_id: str, user: User = Depends(get_session_user),
                        db: AsyncSession = Depends(get_db)):
    row = await db.get(TeamMember, member_id)
    if row is None or (row.team_owner_id != user.id and row.user_id != user.id):
        raise APIError(404, "not_found", "No such member")
    await db.delete(row)
    await db.commit()
