"""Checkouts: an order's payment, and the account number its customer pays.

A live checkout gets its own Pouch virtual account, limited to the order's
amount, so a transfer names its order. A checkout opened from the builder's
preview is `test`: it never touches Pouch and is paid with `simulate`.

When Pouch reports a transfer into a checkout's account, the checkout is
marked paid (or partial), the owner's earnings get the money less Vivid's
fee, and the money is moved on Pouch to the owner's earnings account, which
is what withdrawals are paid from. Money arriving after a checkout expired
is still the owner's; the checkout is flagged late.
"""
import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import secrets as vault
from app.core.config import settings
from app.db.models import (BuilderProject, VividPayAccount, VividPayCheckout,
                           VividPayProject)
from app.services.models_gateway import http
from app.services.vividpay import VividPayError, earnings, fee_for
from app.services.wallet import pouch

log = logging.getLogger("vivid.pay.checkouts")

POUCH = "pouch"
TEST_ACCOUNT = {"account_number": "0000000000", "bank_name": "Test bank (preview)"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def view(c: VividPayCheckout) -> dict:
    """What an app sees about a checkout."""
    from app.services.vividpay import crypto
    status = c.status
    if status == "pending" and _aware(c.expires_at) < _now():
        status = "expired"
    return {"id": c.id, "reference": c.reference, "status": status, "mode": c.mode,
            "amount_kobo": c.amount_kobo, "paid_kobo": c.paid_kobo,
            "account_number": c.account_number, "account_name": c.account_name,
            "bank_name": c.bank_name, "expires_at": _aware(c.expires_at).isoformat(),
            "paid_at": _aware(c.paid_at).isoformat() if c.paid_at else None, "late": c.late,
            "crypto_enabled": crypto.enabled(), "crypto": crypto.view(c)}


def _names(app_name: str) -> tuple[str, str]:
    """The account name a payer's bank shows: the app's name, via Vivid."""
    words = [w for w in "".join(ch if ch.isalnum() or ch == " " else " " for ch in app_name).split()]
    return (" ".join(words)[:60] or "Vivid"), "via Vivid"


async def create(db: AsyncSession, pay: VividPayProject, project: BuilderProject,
                 amount_kobo: int, reference: str, customer: dict | None, meta: dict | None,
                 mode: str) -> VividPayCheckout:
    """A checkout for this order; the same reference returns the same
    checkout while it can still be paid. The caller commits."""
    if not (settings.VIVIDPAY_MIN_CHECKOUT_KOBO <= amount_kobo <= settings.VIVIDPAY_MAX_CHECKOUT_KOBO):
        raise VividPayError(
            f"Amounts go from ₦{settings.VIVIDPAY_MIN_CHECKOUT_KOBO / 100:,.0f} to "
            f"₦{settings.VIVIDPAY_MAX_CHECKOUT_KOBO / 100:,.0f}.")
    reference = (reference or "").strip()[:128]
    if not reference:
        raise VividPayError("A checkout needs the order's reference.")
    existing = (await db.execute(select(VividPayCheckout).where(
        VividPayCheckout.project_id == project.id,
        VividPayCheckout.reference == reference))).scalar_one_or_none()
    if existing is not None:
        if existing.amount_kobo != amount_kobo:
            raise VividPayError("That order already has a checkout for a different amount.",
                                "conflict", 409)
        return existing
    c = VividPayCheckout(project_id=project.id, owner_id=pay.owner_id, reference=reference,
                         amount_kobo=amount_kobo, mode=mode,
                         customer={k: str(v)[:160] for k, v in (customer or {}).items()
                                   if k in ("name", "email", "phone") and v},
                         meta=meta if isinstance(meta, dict) else None,
                         expires_at=_now() + timedelta(minutes=settings.VIVIDPAY_CHECKOUT_MINUTES))
    db.add(c)
    await db.flush()
    first, last = _names(project.name or "Vivid app")
    if mode == "test":
        c.account_number, c.bank_name = TEST_ACCOUNT["account_number"], TEST_ACCOUNT["bank_name"]
        c.account_name = f"{first} {last}"
        return c
    try:
        customer_id = await pouch.ensure_customer_ref(
            "vp_" + c.id.replace("-", ""), first, last,
            email=(customer or {}).get("email"), phone=(customer or {}).get("phone"))
        va = await pouch.open_account(customer_id, pouch.idempotency_key("checkout", c.id),
                                      funding_limit_kobo=amount_kobo)
    except pouch.PouchError as e:
        raise VividPayError(f"Could not open a payment account: {e}", "upstream_error", 502)
    c.va_id = va.get("id")
    c.account_number = va.get("account_number")
    c.account_name = va.get("account_name") or f"{first} {last}"
    c.bank_name = va.get("bank_name")
    return c


async def record_transfer(db: AsyncSession, c: VividPayCheckout, transfer: dict) -> bool:
    """A Pouch transfer into this checkout's account: credit the owner once
    (net of Pouch's own charge, less Vivid's fee) and update the checkout.
    False if already recorded. The caller commits, then calls sweep()."""
    tid = str(transfer.get("id") or "")
    gross = pouch.kobo_of(transfer.get("amount"))
    net = pouch.kobo_of(transfer.get("net_amount")) if transfer.get("net_amount") is not None else gross
    if not tid or net <= 0:
        return False
    entry = await earnings.post(
        db, c.owner_id, net, earnings.PAYMENT, POUCH, tid, project_id=c.project_id,
        checkout_id=c.id, description=f"Payment for {c.reference}",
        meta={"payer": transfer.get("payer_name"), "bank": transfer.get("payer_bank_name"),
              "gross_kobo": gross})
    if entry is None:
        return False
    fee = min(fee_for(gross), net)
    if fee:
        await earnings.post(db, c.owner_id, -fee, earnings.FEE, "vivid", f"fee:{tid}",
                            project_id=c.project_id, checkout_id=c.id,
                            description=f"Vivid Pay fee on {c.reference}")
    was_open = c.status == "pending" and _aware(c.expires_at) >= _now()
    c.paid_kobo += gross
    c.fee_kobo += fee
    c.credited_kobo += net - fee
    if not was_open and c.status in ("pending", "expired"):
        c.late = True
    c.status = "paid" if c.paid_kobo >= c.amount_kobo else "partial"
    c.paid_at = c.paid_at or _now()
    return True


async def simulate(db: AsyncSession, c: VividPayCheckout) -> VividPayCheckout:
    """A test checkout paid in full, without money. The caller commits."""
    if c.mode != "test":
        raise VividPayError("Only test checkouts can be simulated.", "forbidden", 403)
    c.status, c.paid_kobo, c.paid_at = "paid", c.amount_kobo, _now()
    return c


# ------------------------------------------------------------------- sweep
_BANK_UUIDS: dict[str, str] = {}


async def _bank_uuid(bank_name: str | None) -> str | None:
    if not bank_name:
        return None
    key = bank_name.strip().lower()
    if key not in _BANK_UUIDS:
        for b in await pouch.banks():
            _BANK_UUIDS[b["name"].strip().lower()] = b["uuid"]
    if key in _BANK_UUIDS:
        return _BANK_UUIDS[key]
    return next((u for n, u in _BANK_UUIDS.items() if key in n or n in key), None)


async def sweep(db: AsyncSession, c: VividPayCheckout) -> bool:
    """Move what the owner was credited from the checkout's account to
    their earnings account on Pouch. Vivid's fee stays behind (it covers
    this transfer). Safe to call again: only the unswept part moves, and a
    retry reuses the attempt's reference (Pouch's idempotency key). The
    caller commits."""
    if c.mode != "live" or not c.va_id:
        return False
    owed = c.credited_kobo - c.swept_kobo
    if owed <= 0:
        return False
    account = await db.get(VividPayAccount, c.owner_id)
    if account is None or not account.earnings_va_id or not account.earnings_account_number:
        c.sweep_status = "failed"
        return False
    try:
        bank_uuid = await _bank_uuid(account.earnings_bank_name)
        if not bank_uuid:
            raise pouch.PouchError(f"no bank id for {account.earnings_bank_name}")
        await pouch.create_payout(c.va_id, owed, account.earnings_account_number, bank_uuid,
                                  reference=f"sweep-{c.id.replace('-', '')}-{c.swept_kobo}",
                                  narration=f"Vivid Pay {c.reference}")
    except pouch.PouchError as e:
        log.warning("sweep of checkout %s failed: %s", c.id, e)
        c.sweep_status = "failed"
        return False
    c.swept_kobo += owed
    c.sweep_status = "done"
    return True


# ------------------------------------------------------------ app webhooks
def sign(secret_key: str, body: bytes) -> str:
    return hmac.new(secret_key.encode(), body, hashlib.sha256).hexdigest()


async def notify_app(pay: VividPayProject, c: VividPayCheckout) -> None:
    """Tell the app's server side (an edge function) that a checkout was
    paid, signed with the project's secret key. Best effort: the app can
    always ask for the checkout's status."""
    if not pay.webhook_url or c.status not in ("paid", "partial"):
        return
    body = json.dumps({"event": f"checkout.{c.status}", "data": view(c)},
                      separators=(",", ":")).encode()
    try:
        secret = vault.decrypt(pay.secret_key_enc)
    except Exception:
        return
    headers = {"content-type": "application/json", "x-vivid-pay-signature": sign(secret, body)}
    for attempt in range(3):
        try:
            r = await http.client().post(pay.webhook_url, content=body, headers=headers, timeout=10)
            if r.status_code < 500:
                return
        except Exception as e:
            log.info("app webhook for %s failed (attempt %d): %s", c.id, attempt + 1, e)
        await asyncio.sleep(2 * (attempt + 1))
