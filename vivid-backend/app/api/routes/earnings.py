"""An app owner's earnings from Vivid Pay: balance, payments, and withdrawals
to a Nigerian bank after a one-time BVN check.

    GET  /v1/earnings                      balance, pending, KYC, per-app totals
    GET  /v1/earnings/entries              the ledger, newest first
    GET  /v1/earnings/checkouts?project=   checkouts (orders) and their status
    POST /v1/earnings/kyc                  {bvn, first_name, last_name, dob?}
    GET  /v1/earnings/banks                banks to withdraw to
    GET  /v1/earnings/bank-accounts        saved accounts
    POST /v1/earnings/bank-accounts        {account_number, bank_uuid}; must be in the verified name
    POST /v1/earnings/withdrawals/quote    {amount_kobo} -> fee and stamp duty
    POST /v1/earnings/withdrawals          {amount_kobo, bank_account_id}
    GET  /v1/earnings/withdrawals
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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


@router.get("/entries")
async def my_entries(limit: int = 50, user: User = Depends(get_session_user),
                     db: AsyncSession = Depends(get_db)):
    rows = await earnings.entries(db, user.id, min(max(limit, 1), 200))
    return [{"id": e.id, "kind": e.kind, "amount_kobo": e.amount_kobo,
             "balance_after": e.balance_after, "description": e.description,
             "project_id": e.project_id, "created_at": e.created_at} for e in rows]


@router.get("/checkouts")
async def my_checkouts(project: str | None = None, limit: int = 50,
                       user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    q = select(VividPayCheckout).where(VividPayCheckout.owner_id == user.id)
    if project:
        q = q.where(VividPayCheckout.project_id == project)
    rows = (await db.execute(q.order_by(VividPayCheckout.created_at.desc())
                             .limit(min(max(limit, 1), 200)))).scalars()
    return [{**checkouts.view(c), "project_id": c.project_id, "fee_kobo": c.fee_kobo,
             "customer": c.customer, "created_at": c.created_at} for c in rows]


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
async def my_withdrawals(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(VividPayPayout).where(VividPayPayout.owner_id == user.id)
                             .order_by(VividPayPayout.created_at.desc()).limit(100))).scalars()
    return [_payout_out(p) for p in rows]
