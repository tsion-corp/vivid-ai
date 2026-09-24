"""The owner's side: the earnings account on Pouch, bank accounts to
withdraw to, and withdrawals.

A withdrawal takes its amount and fees off the earnings at once (so the
same money cannot be withdrawn twice), then asks Pouch to pay it from the
owner's earnings account. If Pouch refuses, or later reports the transfer
failed, both come back as a reversal. Success only clears it from pending.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (User, VividPayAccount, VividPayBankAccount, VividPayCheckout,
                           VividPayPayout)
from app.services.vividpay import VividPayError, checkouts, earnings, kyc
from app.services.wallet import pouch

log = logging.getLogger("vivid.pay.payouts")

VIVID = "vivid"


# ---------------------------------------------------------- earnings account
async def ensure_earnings_account(db: AsyncSession, user: User) -> VividPayAccount:
    """The owner's Pouch account that their payments are gathered in and
    withdrawals are paid from; opened once. The caller commits."""
    account = await earnings.account_for(db, user.id, lock=True)
    if account.earnings_va_id:
        return account
    if not pouch.configured():
        raise VividPayError("Payments are not set up on this server.", "not_configured", 503)
    parts = (user.name or "").split()
    first = parts[0] if parts else (user.profile_email or user.email or "Vivid").split("@")[0]
    last = " ".join(parts[1:]) if len(parts) > 1 else "Earnings"
    try:
        customer_id = await pouch.ensure_customer_ref(
            "vpo_" + user.id.replace("-", ""), first, last, email=user.profile_email or user.email)
        va = await pouch.open_account(customer_id, pouch.idempotency_key("earnings", user.id))
    except pouch.PouchError as e:
        raise VividPayError(f"Could not open your earnings account: {e}", "upstream_error", 502)
    account.customer_id = customer_id
    account.earnings_va_id = va.get("id")
    account.earnings_account_number = va.get("account_number")
    account.earnings_bank_name = va.get("bank_name")
    return account


# ------------------------------------------------------------ bank accounts
async def add_bank_account(db: AsyncSession, user_id: str, account_number: str,
                           bank_uuid: str) -> VividPayBankAccount:
    account = await earnings.account_for(db, user_id)
    if account.kyc_status != "verified":
        raise VividPayError("Verify your BVN before adding a bank account.", "kyc_required", 403)
    number = "".join(ch for ch in account_number if ch.isdigit())
    if len(number) != 10:
        raise VividPayError("A Nigerian account number is 10 digits.")
    try:
        found = await pouch.validate_account(number, bank_uuid)
    except pouch.PouchError as e:
        raise VividPayError(f"The bank could not confirm that account: {e}", "bad_account")
    name = found.get("account_name") or ""
    if not kyc.names_match(account.kyc_name, name):
        raise VividPayError(f"That account is in the name {name or 'unknown'}; withdrawals go only "
                            f"to accounts in your verified name ({account.kyc_name}).",
                            "name_mismatch")
    existing = (await db.execute(select(VividPayBankAccount).where(
        VividPayBankAccount.user_id == user_id, VividPayBankAccount.account_number == number,
        VividPayBankAccount.bank_uuid == bank_uuid))).scalar_one_or_none()
    if existing is not None:
        return existing
    row = VividPayBankAccount(user_id=user_id, account_number=number, bank_uuid=bank_uuid,
                              bank_name=found.get("bank_name") or "Bank", account_name=name[:160])
    db.add(row)
    await db.flush()
    return row


# ------------------------------------------------------------- withdrawals
async def quote(amount_kobo: int) -> dict:
    fee, stamp = await pouch.payout_quote(amount_kobo)
    return {"amount_kobo": amount_kobo, "fee_kobo": fee, "stamp_duty_kobo": stamp,
            "total_kobo": amount_kobo + fee + stamp}


async def _withdrawn_today(db: AsyncSession, user_id: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    q = select(func.coalesce(func.sum(VividPayPayout.amount_kobo), 0)).where(
        VividPayPayout.owner_id == user_id, VividPayPayout.status != "failed",
        VividPayPayout.created_at >= since)
    return int((await db.execute(q)).scalar_one())


async def _ensure_funds_on_pouch(db: AsyncSession, account: VividPayAccount, needed: int) -> None:
    """The earnings account on Pouch must hold the payout; if earlier moves
    from order accounts failed, they are retried first."""
    have = await pouch.account_balance(account.earnings_va_id)
    if have >= needed:
        return
    stuck = (await db.execute(select(VividPayCheckout).where(
        VividPayCheckout.owner_id == account.user_id, VividPayCheckout.mode == "live",
        VividPayCheckout.sweep_status == "failed"))).scalars()
    for c in list(stuck):
        await checkouts.sweep(db, c)
    have = await pouch.account_balance(account.earnings_va_id)
    if have < needed:
        raise VividPayError("Some of your earnings are still settling. Try again in a few minutes.",
                            "settling", 409)


async def withdraw(db: AsyncSession, user_id: str, amount_kobo: int,
                   bank_account_id: str) -> VividPayPayout:
    """Pay earnings out to one of the owner's verified bank accounts. The
    caller commits (the payout row and entries are flushed first)."""
    account = await earnings.account_for(db, user_id)
    if account.kyc_status != "verified":
        raise VividPayError("Verify your BVN before your first withdrawal.", "kyc_required", 403)
    if not account.earnings_va_id:
        raise VividPayError("You have no earnings account yet.", "not_found", 404)
    if amount_kobo < settings.VIVIDPAY_MIN_WITHDRAWAL_KOBO:
        raise VividPayError(f"The smallest withdrawal is ₦{settings.VIVIDPAY_MIN_WITHDRAWAL_KOBO / 100:,.0f}.")
    if await _withdrawn_today(db, user_id) + amount_kobo > settings.VIVIDPAY_DAILY_WITHDRAWAL_KOBO:
        raise VividPayError(f"That is over the daily limit of "
                            f"₦{settings.VIVIDPAY_DAILY_WITHDRAWAL_KOBO / 100:,.0f}.", "limit")
    bank = await db.get(VividPayBankAccount, bank_account_id)
    if bank is None or bank.user_id != user_id:
        raise VividPayError("No such bank account.", "not_found", 404)
    q = await quote(amount_kobo)
    if account.balance_kobo < q["total_kobo"]:
        raise earnings.InsufficientEarnings(account.balance_kobo, q["total_kobo"])
    await _ensure_funds_on_pouch(db, account, q["total_kobo"])

    payout = VividPayPayout(owner_id=user_id, amount_kobo=amount_kobo, fee_kobo=q["fee_kobo"],
                            stamp_duty_kobo=q["stamp_duty_kobo"], bank_account_id=bank.id,
                            account_number=bank.account_number, bank_name=bank.bank_name,
                            recipient_name=bank.account_name)
    db.add(payout)
    await db.flush()
    await earnings.post(db, user_id, -amount_kobo, earnings.WITHDRAWAL, VIVID,
                        f"withdrawal:{payout.id}", payout_id=payout.id,
                        description=f"To {bank.bank_name} {bank.account_number[-4:]}")
    fees = q["fee_kobo"] + q["stamp_duty_kobo"]
    if fees:
        await earnings.post(db, user_id, -fees, earnings.WITHDRAWAL_FEE, VIVID,
                            f"withdrawal-fee:{payout.id}", payout_id=payout.id,
                            description="Bank transfer fee")
    locked = await earnings.account_for(db, user_id, lock=True)
    locked.pending_kobo += amount_kobo
    try:
        sent = await pouch.create_payout(account.earnings_va_id, amount_kobo, bank.account_number,
                                         bank.bank_uuid, reference=reference_of(payout),
                                         narration="Vivid earnings")
    except pouch.PouchError as e:
        if e.unreachable:
            # It may have gone through: stay pending, the reconciler finds
            # it by reference (or reverses it when Pouch has no such payout).
            log.warning("payout %s outcome unknown: %s", payout.id, e)
            return payout
        # A refusal: nothing was sent. The caller commits the reversal and
        # then reports payout.error.
        await _reverse(db, payout, str(e))
        return payout
    payout.pouch_payout_id = sent.get("id")
    if _status_of(sent) == "success":
        await settle(db, payout, "success",
                     actual_fee_kobo=pouch.kobo_of(sent["fee"]) if sent.get("fee") is not None else None)
    return payout


def reference_of(payout: VividPayPayout) -> str:
    return f"wd-{payout.id.replace('-', '')}"


async def _reverse(db: AsyncSession, payout: VividPayPayout, error: str) -> None:
    """A failed withdrawal: its amount and fees come back, once."""
    if payout.status == "failed":
        return
    payout.status, payout.error = "failed", error[:500]
    total = payout.amount_kobo + payout.fee_kobo + payout.stamp_duty_kobo
    await earnings.post(db, payout.owner_id, total, earnings.REVERSAL, VIVID,
                        f"reversal:{payout.id}", payout_id=payout.id,
                        description="Withdrawal failed; returned")
    account = await earnings.account_for(db, payout.owner_id, lock=True)
    account.pending_kobo = max(account.pending_kobo - payout.amount_kobo, 0)


async def settle(db: AsyncSession, payout: VividPayPayout, status: str, error: str = "",
                 actual_fee_kobo: int | None = None) -> None:
    """Pouch's final word on a withdrawal. When Pouch charged less than the
    fee taken up front (its quote route is not always there), the rest is
    given back. The caller commits."""
    if payout.status != "pending":
        return
    if status == "success":
        payout.status = "success"
        account = await earnings.account_for(db, payout.owner_id, lock=True)
        account.pending_kobo = max(account.pending_kobo - payout.amount_kobo, 0)
        if actual_fee_kobo is not None and 0 <= actual_fee_kobo < payout.fee_kobo:
            await earnings.post(db, payout.owner_id, payout.fee_kobo - actual_fee_kobo,
                                earnings.ADJUSTMENT, VIVID, f"fee-refund:{payout.id}",
                                payout_id=payout.id, description="Transfer fee was lower")
            payout.fee_kobo = actual_fee_kobo
    elif status == "failed":
        await _reverse(db, payout, error or "the bank transfer failed")


def _status_of(data: dict) -> str | None:
    # Pouch's payout objects carry `latest_status`; the docs' examples say `status`.
    s = (data.get("status") or data.get("latest_status") or "").lower()
    if s in ("success", "successful", "completed"):
        return "success"
    if s in ("failed", "reversed", "rejected", "cancelled", "canceled"):
        return "failed"
    return None


async def refresh(db: AsyncSession, payout: VividPayPayout) -> None:
    """Ask Pouch how a pending withdrawal went. One whose request never got
    an answer is looked up by reference; if Pouch has none after ten
    minutes, it never started and is reversed."""
    if payout.status != "pending":
        return
    try:
        if payout.pouch_payout_id:
            data = await pouch.get_payout(payout.pouch_payout_id)
        else:
            data = await pouch.find_payout(reference_of(payout))
            if data is None:
                created = payout.created_at if payout.created_at.tzinfo else \
                    payout.created_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - created > timedelta(minutes=10):
                    await _reverse(db, payout, "the bank transfer never started")
                return
            payout.pouch_payout_id = data.get("id")
    except pouch.PouchError as e:
        log.info("could not refresh payout %s: %s", payout.id, e)
        return
    status = _status_of(data)
    if status:
        fee = pouch.kobo_of(data["fee"]) if data.get("fee") is not None else None
        await settle(db, payout, status, data.get("failure_reason") or data.get("error") or "",
                     actual_fee_kobo=fee)
