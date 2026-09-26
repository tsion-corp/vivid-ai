"""The wallet and plans: a user's USD balance with Vivid, how to top it up
(a bank virtual account or crypto addresses), its history, and the builder
plan it pays for.

    GET    /v1/wallet?currency=NGN      balance, shown in USD and one other currency
    GET    /v1/wallet/entries           history, newest first
    GET    /v1/wallet/rates             USD rates for the display currencies
    POST   /v1/wallet/bank-account      the user's naira virtual account (made on first call)
    GET    /v1/wallet/crypto/options    tokens and chains to top up with
    GET    /v1/wallet/crypto/chains     every network a deposit can come from
    GET    /v1/wallet/crypto/tokens     the tokens one network can send (?chain_id=)
    POST   /v1/wallet/crypto/address    the user's address for one option, or any
                                        {chain_id, asset} (made on first call)
    POST   /v1/wallet/credit-packs      buy extra builder credits
    GET    /v1/plans                    the plans and their prices
    GET    /v1/me/plan                  the user's plan, usage meters and extra tokens
    POST   /v1/me/plan                  subscribe or change plan (paid from the wallet)
    DELETE /v1/me/plan                  cancel at the end of the period
"""
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_session_user
from app.core.config import settings
from app.core.errors import APIError
from app.db.models import BuilderProject, User, WalletFunding
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


# The Dextopus catalog barely changes; an hour's cache keeps the Add funds
# flow instant and Dextopus unbothered.
_CATALOG_TTL = 3600
_catalog: dict[str, tuple[float, list[dict]]] = {}


async def _cached(key: str, load) -> list[dict]:
    hit = _catalog.get(key)
    if hit and time.monotonic() - hit[0] < _CATALOG_TTL:
        return hit[1]
    if not dextopus.configured():
        raise APIError(503, "not_configured", "Crypto top-ups are not set up yet.")
    try:
        rows = await load()
    except dextopus.DextopusError as e:
        if hit:
            return hit[1]                        # stale beats nothing
        raise APIError(502, "upstream_error", str(e))
    _catalog[key] = (time.monotonic(), rows)
    return rows


async def _chains() -> list[dict]:
    async def load():
        out = []
        for c in await dextopus.chains():
            if not c.get("chainId") or not c.get("name"):
                continue
            name = crypto_options.CHAIN_NAMES.get(str(c["name"]), str(c["name"]))
            out.append({"chain_id": int(c["chainId"]), "name": name,
                        "logo_url": c.get("logoUrl"),
                        "native_symbol": (c.get("nativeCurrency") or {}).get("symbol")})
        return sorted(out, key=lambda c: c["name"].lower())
    return await _cached("chains", load)


async def _tokens(chain_id: int) -> list[dict]:
    async def load():
        rank = {s: i for i, s in enumerate(crypto_options.TOKEN_ORDER)}
        rows = [{"asset": crypto_options.origin_asset(chain_id, str(t["address"])),
                 "symbol": str(t.get("symbol") or "?"), "name": str(t.get("name") or ""),
                 "logo_url": t.get("logoUrl")}
                for t in await dextopus.tokens(chain_id) if t.get("address")]
        native = crypto_options.origin_asset(chain_id, crypto_options.NATIVE_PLACEHOLDER)
        # Stablecoins first (what people pay with), then the native coin, then the rest.
        return sorted(rows, key=lambda t: (rank.get(t["symbol"].upper(), len(rank) + (0 if t["asset"] == native else 1)),
                                           t["symbol"].lower()))
    return await _cached(f"tokens:{chain_id}", load)


def _min_usd(chain_id: int) -> float:
    """Ethereum mainnet costs more to move than a dollar is worth."""
    return max(settings.WALLET_CRYPTO_MIN_USD, 10.0) if chain_id == crypto_options.ETHEREUM \
        else settings.WALLET_CRYPTO_MIN_USD


@router.get("/wallet/crypto/chains")
async def crypto_chains(user: User = Depends(get_session_user)):
    chains = await _chains()
    by_name = {c["name"]: c for c in chains}
    return {"available": dextopus.configured(), "settles_as": "USDC on Base",
            "min_usd": settings.WALLET_CRYPTO_MIN_USD,
            "recommended": [by_name[n]["chain_id"] for n in crypto_options.RECOMMENDED if n in by_name],
            "chains": chains}


@router.get("/wallet/crypto/tokens")
async def crypto_tokens(chain_id: int, user: User = Depends(get_session_user)):
    return {"chain_id": chain_id, "min_usd": _min_usd(chain_id), "tokens": await _tokens(chain_id)}


class CryptoAddressIn(BaseModel):
    option: str | None = Field(default=None, max_length=32)
    chain_id: int | None = None
    asset: str | None = Field(default=None, max_length=128)


@router.post("/wallet/crypto/address")
async def crypto_address(body: CryptoAddressIn, user: User = Depends(get_session_user),
                         db: AsyncSession = Depends(get_db)):
    """The user's address for a named option ("usdc-base"), or for any token
    and chain from the catalog. The symbol and network name come from the
    catalog, never from the request."""
    if body.chain_id is not None and body.asset:
        chain = next((c for c in await _chains() if c["chain_id"] == body.chain_id), None)
        token = next((t for t in await _tokens(body.chain_id)
                      if t["asset"].lower() == body.asset.lower()), None) if chain else None
        if chain is None or token is None:
            raise APIError(400, "bad_request", "That token can't be deposited on that network.")
        key = crypto_options.pair_key(chain["chain_id"], token["asset"])
        chain_id, asset, symbol, chain_name = chain["chain_id"], token["asset"], token["symbol"], chain["name"]
        note = f"{chain_name} network only"
    else:
        option = crypto_options.get(body.option or "")
        if option is None:
            raise APIError(400, "bad_request", "Unknown token or network.")
        key, chain_id, asset, symbol, chain_name = (option.key, option.chain_id, option.asset,
                                                    option.symbol, option.chain)
        note = option.network_note
    existing = (await db.execute(select(WalletFunding).where(
        WalletFunding.user_id == user.id, WalletFunding.provider == "dextopus",
        WalletFunding.option == key))).scalars().first()
    if existing is None:
        if not dextopus.configured():
            raise APIError(503, "not_configured", "Crypto top-ups are not set up yet.")
        try:
            data = await dextopus.static_address_for(user.id, key, chain_id, asset)
        except dextopus.DextopusError as e:
            raise APIError(502, "upstream_error", str(e))
        # For crypto, account_name and bank_name hold the token and network
        # names, so a deposit's receipt can say what arrived.
        existing = WalletFunding(user_id=user.id, provider="dextopus", option=key,
                                 external_id=data.get("id") or data["depositAddress"],
                                 address=data["depositAddress"], chain_id=chain_id,
                                 asset=asset, account_name=symbol[:160], bank_name=chain_name[:80])
        db.add(existing)
        await db.commit()
    return {"option": key, "symbol": symbol, "chain": chain_name, "chain_id": chain_id,
            "address": existing.address, "network_note": note,
            "min_usd": _min_usd(chain_id), "settles_as": "USDC on Base"}


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
    # What happened, in the message; how to fix it only in details.options,
    # so a store app can leave "top up" unsaid.
    return APIError(402, "insufficient_funds",
                    f"Your wallet has ${_usd(e.balance_micro):,.2f}; this needs "
                    f"${_usd(e.needed_micro):,.2f}.",
                    details={"balance_micro": e.balance_micro, "needed_micro": e.needed_micro,
                             "short_micro": max(e.needed_micro - e.balance_micro, 0),
                             "options": ["top_up"]})


# ------------------------------------------------------------------- plans
def _plan_out(p: catalog.Plan) -> dict:
    return {"id": p.id, "name": p.name, "price_usd": p.price_usd,
            "yearly_price_usd": p.yearly_price_usd,
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
            # Cached input counts at this weight of a token (see section 13
            # of llms.txt); uncached input and output count in full.
            "cached_token_weight": settings.PLAN_CACHED_TOKEN_WEIGHT,
            "credit_price_usd": settings.PLAN_CREDIT_PRICE_USD,
            "credit_packs": packs, "usd_ngn": ngn}


class PlanOut(BaseModel):
    id: str
    name: str
    price_usd: float
    yearly_price_usd: float | None = None
    #: None: unlimited.
    max_apps: int | None = None
    window_credits: float
    window_hours: int
    month_credits: float


class AppsMeter(BaseModel):
    used: int
    #: None: unlimited.
    limit: int | None = None


class CreditMeter(BaseModel):
    used: float
    limit: float
    resets_at: datetime
    #: The rolling window's length (window meter only).
    hours: int | None = None


class MyPlanOut(BaseModel):
    """The user's plan and what is left of it; amounts in credits."""
    plan: PlanOut
    #: active | grace (a renewal could not be paid; Free after grace_until) |
    #: canceled (keeps the plan until period_end)
    status: str
    yearly: bool
    period_end: datetime | None = None
    grace_until: datetime | None = None
    apps: AppsMeter
    window: CreditMeter
    month: CreditMeter
    extra_credits: float


async def _me_plan(db: AsyncSession, user: User) -> dict:
    account = await usage.account_for(db, user.id)
    m = await usage.meter(db, account)
    wallet = await ledger.wallet_for(db, account.owner_id)
    owned = int((await db.execute(select(func.count()).select_from(BuilderProject).where(
        BuilderProject.owner_id == user.id))).scalar_one())
    sub = account.subscription
    return {"plan": _plan_out(account.plan),
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


@router.get("/me/plan", response_model=MyPlanOut)
async def my_plan(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    out = await _me_plan(db, user)
    await db.commit()
    return out


class PlanIn(BaseModel):
    plan: str
    yearly: bool = False


@router.post("/me/plan", response_model=MyPlanOut)
async def change_plan(body: PlanIn, user: User = Depends(get_session_user),
                      db: AsyncSession = Depends(get_db)):
    try:
        await subscriptions.subscribe(db, user.id, body.plan, body.yearly)
    except subscriptions.PlanError as e:
        raise APIError(400, "bad_request", str(e))
    except ledger.InsufficientFunds as e:
        await db.rollback()
        raise _insufficient(e)
    await db.commit()
    return await _me_plan(db, user)


@router.delete("/me/plan", response_model=MyPlanOut)
async def cancel_plan(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    await subscriptions.cancel(db, user.id)
    await db.commit()
    return await _me_plan(db, user)
