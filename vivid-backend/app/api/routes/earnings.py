"""An app owner's earnings from Vivid Pay: balance, payments, and withdrawals
to a Nigerian bank after a one-time BVN check.

    GET  /v1/earnings                      balance, pending, KYC, per-app totals
    GET  /v1/earnings/entries              history, newest first: payments and withdrawals
                                           with their fees folded in (?kind=&project=&since=&until=)
    GET  /v1/earnings/checkouts            orders (?status=&project=&q=&mode=)
    POST /v1/earnings/kyc                  {bvn, first_name, last_name, dob?}
    GET  /v1/earnings/banks                banks to withdraw to
    GET  /v1/earnings/bank-accounts        saved accounts
    POST /v1/earnings/bank-accounts        {account_number, bank_uuid}; must be in the verified name
    POST /v1/earnings/withdrawals/quote    {amount_kobo} -> fee and stamp duty
    POST /v1/earnings/withdrawals          {amount_kobo, bank_account_id}
    GET  /v1/earnings/withdrawals          (?status=)

The three lists page with ?offset=&limit= and answer {items, has_more}.
"""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_session_user
from app.core.errors import APIError
from app.db.models import (BuilderProject, User, VividPayBankAccount, VividPayCheckout,
                           VividPayEntry, VividPayPayout)
from app.services.vividpay import VividPayError, checkouts, earnings, kyc, payouts
from app.services.wallet import pouch

router = APIRouter(prefix="/earnings", tags=["earnings"])


def _err(e: VividPayError) -> APIError:
    return APIError(e.status, e.code, str(e))


@router.get("")
async def my_earnings(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    account = await earnings.account_for(db, user.id)
    await db.commit()
    per_app = (await db.execute(
        select(VividPayEntry.project_id, BuilderProject.name,
               func.coalesce(func.sum(VividPayEntry.amount_kobo), 0))
        .join(BuilderProject, BuilderProject.id == VividPayEntry.project_id)
        .where(VividPayEntry.owner_id == user.id, VividPayEntry.kind.in_(
            (earnings.PAYMENT, earnings.FEE)))
        .group_by(VividPayEntry.project_id, BuilderProject.name))).all()
    return {"balance_kobo": account.balance_kobo, "pending_kobo": account.pending_kobo,
            "kyc": {"status": account.kyc_status, "name": account.kyc_name},
            "earnings_account": ({"account_number": account.earnings_account_number,
                                  "bank_name": account.earnings_bank_name}
                                 if account.earnings_va_id else None),
            "apps": [{"project_id": pid, "name": name, "net_kobo": int(total)}
                     for pid, name, total in per_app],
            "available": pouch.configured()}


MAX_PAGE = 500


def _page(limit: int, offset: int) -> tuple[int, int]:
    return min(max(limit, 1), MAX_PAGE), max(offset, 0)


def _paged(rows: list, limit: int) -> tuple[list, bool]:
    return rows[:limit], len(rows) > limit


def _day(value: str | None, end: bool = False) -> datetime | None:
    """A YYYY-MM-DD bound, the start of that day, or the start of the next."""
    if not value:
        return None
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise APIError(422, "invalid_date", "Dates are YYYY-MM-DD.")
    return datetime.combine(d + timedelta(days=1) if end else d, time.min, tzinfo=timezone.utc)


#: History shows what moved the balance, one row per payment or withdrawal:
#: Vivid's fee is folded into its payment (the row is what the owner got)
#: and the transfer fee, and any refund of it, into its withdrawal (the row
#: is what left the balance). Rows still add up to the balance.
_FOLDED = (earnings.FEE, earnings.WITHDRAWAL_FEE)
_HISTORY_KINDS = {"payments": (earnings.PAYMENT,),
                  "withdrawals": (earnings.WITHDRAWAL, earnings.REVERSAL)}


@router.get("/entries")
async def my_entries(kind: str | None = None, project: str | None = None,
                     since: str | None = None, until: str | None = None,
                     limit: int = 20, offset: int = 0,
                     user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    limit, offset = _page(limit, offset)
    q = select(VividPayEntry).where(
        VividPayEntry.owner_id == user.id, VividPayEntry.kind.not_in(_FOLDED),
        ~and_(VividPayEntry.kind == earnings.ADJUSTMENT,
              VividPayEntry.provider_ref.like("fee-refund:%")))
    if kind in _HISTORY_KINDS:
        q = q.where(VividPayEntry.kind.in_(_HISTORY_KINDS[kind]))
    if project:
        q = q.where(VividPayEntry.project_id == project)
    if (lo := _day(since)) is not None:
        q = q.where(VividPayEntry.created_at >= lo)
    if (hi := _day(until, end=True)) is not None:
        q = q.where(VividPayEntry.created_at < hi)
    rows, more = _paged(list((await db.execute(
        q.order_by(VividPayEntry.created_at.desc(), VividPayEntry.id.desc())
        .offset(offset).limit(limit + 1))).scalars()), limit)

    # What folds into each row.
    fee_refs = [f"fee:{e.provider_ref}" for e in rows if e.kind == earnings.PAYMENT]
    payout_ids = [e.payout_id for e in rows if e.kind == earnings.WITHDRAWAL and e.payout_id]
    extra: dict[str, int] = {}
    if fee_refs or payout_ids:
        for f in (await db.execute(select(VividPayEntry).where(
                VividPayEntry.owner_id == user.id,
                or_(and_(VividPayEntry.kind == earnings.FEE, VividPayEntry.provider_ref.in_(fee_refs)),
                    and_(VividPayEntry.payout_id.in_(payout_ids or [""]),
                         or_(VividPayEntry.kind == earnings.WITHDRAWAL_FEE,
                             VividPayEntry.provider_ref.like("fee-refund:%"))))))).scalars():
            k = f.provider_ref.removeprefix("fee:") if f.kind == earnings.FEE else f"payout:{f.payout_id}"
            extra[k] = extra.get(k, 0) + f.amount_kobo
    checkout_ids = {e.checkout_id for e in rows if e.checkout_id}
    orders = {c.id: c for c in (await db.execute(select(VividPayCheckout).where(
        VividPayCheckout.id.in_(checkout_ids)))).scalars()} if checkout_ids else {}
    project_ids = {e.project_id for e in rows if e.project_id}
    apps = dict((await db.execute(select(BuilderProject.id, BuilderProject.name).where(
        BuilderProject.id.in_(project_ids)))).all()) if project_ids else {}

    items = []
    for e in rows:
        amount, title = e.amount_kobo, e.description
        if e.kind == earnings.PAYMENT:
            amount += extra.get(e.provider_ref, 0)
            c = orders.get(e.checkout_id or "")
            title = (c.reference if c else None) or title
        elif e.kind == earnings.WITHDRAWAL:
            amount += extra.get(f"payout:{e.payout_id}", 0)
        c = orders.get(e.checkout_id or "")
        items.append({"id": e.id, "kind": e.kind, "amount_kobo": amount, "title": title,
                      "customer": (c.customer or {}).get("name") if c else None,
                      "project_id": e.project_id, "app": apps.get(e.project_id or ""),
                      "created_at": e.created_at})
    return {"items": items, "has_more": more}


@router.get("/checkouts")
async def my_checkouts(project: str | None = None, status: str | None = None, q: str | None = None,
                       mode: str = "live", limit: int = 20, offset: int = 0,
                       user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    limit, offset = _page(limit, offset)
    now = datetime.now(timezone.utc)
    query = select(VividPayCheckout).where(VividPayCheckout.owner_id == user.id)
    if mode in ("live", "test"):
        query = query.where(VividPayCheckout.mode == mode)
    if project:
        query = query.where(VividPayCheckout.project_id == project)
    if status == "expired":
        query = query.where(VividPayCheckout.status == "pending", VividPayCheckout.expires_at < now)
    elif status == "pending":
        query = query.where(VividPayCheckout.status == "pending", VividPayCheckout.expires_at >= now)
    elif status in ("paid", "partial"):
        query = query.where(VividPayCheckout.status == status)
    if q and q.strip():
        like = f"%{q.strip()[:80]}%"
        query = query.where(or_(VividPayCheckout.reference.ilike(like),
                                cast(VividPayCheckout.customer, String).ilike(like)))
    rows, more = _paged(list((await db.execute(
        query.order_by(VividPayCheckout.created_at.desc(), VividPayCheckout.id.desc())
        .offset(offset).limit(limit + 1))).scalars()), limit)
    return {"items": [{**checkouts.view(c), "project_id": c.project_id,
                       "credited_kobo": c.credited_kobo, "customer": c.customer,
                       "created_at": c.created_at} for c in rows],
            "has_more": more}


class KycIn(BaseModel):
    bvn: str = Field(pattern=r"^\d{11}$")
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    dob: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/kyc")
async def verify_identity(body: KycIn, user: User = Depends(get_session_user),
                          db: AsyncSession = Depends(get_db)):
    try:
        account = await kyc.verify(db, user.id, body.bvn, body.first_name, body.last_name, body.dob)
    except VividPayError as e:
        await db.commit()                     # a failed check is remembered
        raise _err(e)
    await db.commit()
    return {"status": account.kyc_status, "name": account.kyc_name}


@router.get("/banks")
async def list_banks(user: User = Depends(get_session_user)):
    try:
        return [{"uuid": b["uuid"], "name": b["name"]}
                for b in sorted(await pouch.banks(), key=lambda b: b["name"])]
    except pouch.PouchError as e:
        raise APIError(502, "upstream_error", str(e))


def _bank_out(b: VividPayBankAccount) -> dict:
    return {"id": b.id, "account_number": b.account_number, "bank_name": b.bank_name,
            "account_name": b.account_name, "bank_uuid": b.bank_uuid}


@router.get("/bank-accounts")
async def my_bank_accounts(user: User = Depends(get_session_user),
                           db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(VividPayBankAccount).where(
        VividPayBankAccount.user_id == user.id).order_by(VividPayBankAccount.created_at))).scalars()
    return [_bank_out(b) for b in rows]


class BankIn(BaseModel):
    account_number: str = Field(min_length=10, max_length=20)
    bank_uuid: str = Field(min_length=1, max_length=64)


@router.post("/bank-accounts", status_code=201)
async def add_bank(body: BankIn, user: User = Depends(get_session_user),
                   db: AsyncSession = Depends(get_db)):
    try:
        row = await payouts.add_bank_account(db, user.id, body.account_number, body.bank_uuid)
    except VividPayError as e:
        raise _err(e)
    await db.commit()
    return _bank_out(row)


class AmountIn(BaseModel):
    amount_kobo: int = Field(gt=0)


@router.post("/withdrawals/quote")
async def quote_withdrawal(body: AmountIn, user: User = Depends(get_session_user)):
    return await payouts.quote(body.amount_kobo)


class WithdrawIn(AmountIn):
    bank_account_id: str


def _payout_out(p: VividPayPayout) -> dict:
    return {"id": p.id, "amount_kobo": p.amount_kobo, "fee_kobo": p.fee_kobo,
            "stamp_duty_kobo": p.stamp_duty_kobo, "status": p.status, "error": p.error,
            "bank_name": p.bank_name, "account_number": p.account_number,
            "recipient_name": p.recipient_name, "created_at": p.created_at}


@router.post("/withdrawals", status_code=201)
async def withdraw(body: WithdrawIn, user: User = Depends(get_session_user),
                   db: AsyncSession = Depends(get_db)):
    try:
        payout = await payouts.withdraw(db, user.id, body.amount_kobo, body.bank_account_id)
    except VividPayError as e:
        await db.rollback()
        raise _err(e)
    await db.commit()
    if payout.status == "failed":
        raise APIError(502, "upstream_error",
                       f"The bank transfer could not be started: {payout.error}. Nothing was taken.")
    return _payout_out(payout)


@router.get("/withdrawals")
async def my_withdrawals(status: str | None = None, limit: int = 20, offset: int = 0,
                         user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    limit, offset = _page(limit, offset)
    q = select(VividPayPayout).where(VividPayPayout.owner_id == user.id)
    if status in ("pending", "success", "failed"):
        q = q.where(VividPayPayout.status == status)
    rows, more = _paged(list((await db.execute(
        q.order_by(VividPayPayout.created_at.desc(), VividPayPayout.id.desc())
        .offset(offset).limit(limit + 1))).scalars()), limit)
    return {"items": [_payout_out(p) for p in rows], "has_more": more}
