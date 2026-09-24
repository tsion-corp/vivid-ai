"""Pouch (Liquifia fiat API): each Vivid user's Nigerian bank virtual
account. A transfer into it credits their wallet.

Accounts are created with settlement_mode "held", so the money lands in
Vivid's Pouch wallet; the user's Vivid balance is our own ledger, never
Pouch's per-account balance. Amounts on Pouch are in kobo.
"""
import logging
import uuid

import httpx

from app.core.config import settings
from app.services.models_gateway import http

log = logging.getLogger("vivid.wallet.pouch")

#: uuid5 namespace for idempotency keys: one key per user, so a retried
#: request can never open a second account.
_NS = uuid.UUID("8b7f0f5e-2c1d-4f8e-9a51-6d1d2b3c4e5f")


class PouchError(Exception):
    """Pouch refused or could not be reached; str() is safe to show.
    `unreachable`: no answer, so whether it acted is unknown."""

    def __init__(self, message: str, unreachable: bool = False):
        super().__init__(message)
        self.unreachable = unreachable


def configured() -> bool:
    return bool(settings.POUCH_API_KEY)


def _url(path: str) -> str:
    return f"{settings.POUCH_BASE_URL.rstrip('/')}/api/v1{path}"


async def _call(method: str, path: str, *, json: dict | None = None, params: dict | None = None,
                headers: dict | None = None) -> dict:
    if not configured():
        raise PouchError("bank transfers are not set up on this server")
    try:
        r = await http.client().request(
            method, _url(path), json=json, params=params,
            headers={"Authorization": f"Bearer {settings.POUCH_API_KEY}", **(headers or {})},
            timeout=settings.PAYMENTS_API_TIMEOUT)
    except httpx.HTTPError as e:
        raise PouchError(f"could not reach the bank partner ({e.__class__.__name__})",
                         unreachable=True)
    body = r.json() if r.content else {}
    if r.status_code >= 400 or body.get("success") is False:
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        message = err.get("message") or body.get("message") or f"HTTP {r.status_code}"
        raise PouchError(f"bank partner: {message}")
    return body


def customer_reference(user_id: str) -> str:
    """Alphanumeric, underscore and hyphen only, per Pouch."""
    return "vivid_" + user_id.replace("-", "")


def _names(name: str | None, email: str | None) -> tuple[str, str]:
    parts = (name or "").split()
    if len(parts) >= 2:
        return parts[0][:60], " ".join(parts[1:])[:60]
    first = parts[0] if parts else ((email or "Vivid").split("@")[0] or "Vivid")
    return first[:60], "Vivid"


async def ensure_customer(user_id: str, name: str | None, email: str | None,
                          phone: str | None = None, bvn: str | None = None) -> str:
    """The Pouch customer id for this user, found by reference or created."""
    ref = customer_reference(user_id)
    found = await _call("GET", "/customers", params={"search": ref, "take": 5})
    for c in found.get("data") or []:
        if c.get("customer_reference") == ref:
            return c["id"]
    first, last = _names(name, email)
    body = {"customer_reference": ref, "first_name": first, "last_name": last}
    if email and "@" in email:
        body["email"] = email
    if phone:
        body["phone_number"] = phone
    if bvn:
        body["bvn"] = bvn
    created = await _call("POST", "/customers", json=body)
    return created["data"]["id"]


async def create_virtual_account(user_id: str, customer_id: str) -> dict:
    """A naira account whose money settles to Vivid ("held")."""
    key = str(uuid.uuid5(_NS, user_id))
    out = await _call("POST", f"/customers/{customer_id}/virtual-accounts",
                      json={"country": "NG", "currency": "NGN", "settlement_mode": "held"},
                      headers={"X-Idempotency-Key": key})
    return out["data"]


async def inbound_transfers(skip: int = 0, take: int = 100) -> list[dict]:
    out = await _call("GET", "/inbound-transfers", params={"skip": skip, "take": take})
    return out.get("data") or []


async def find_transfer(transfer_id: str, pages: int = 5) -> dict | None:
    """A transfer by id, from the newest pages (no single-transfer route)."""
    for page in range(pages):
        rows = await inbound_transfers(skip=page * 100, take=100)
        for row in rows:
            if row.get("id") == transfer_id:
                return row
        if len(rows) < 100:
            break
    return None


async def integrator() -> dict:
    """Vivid's Pouch profile. The docs list /integrator too, but only its
    alias /me answers."""
    return (await _call("GET", "/me")).get("data") or {}


async def set_webhook(url: str) -> dict:
    """Register the webhook URL. The docs name /me/webhook but not its
    method or body, so the common shapes are tried in turn."""
    last: PouchError | None = None
    for method in ("PUT", "POST", "PATCH"):
        for body in ({"webhook_url": url}, {"url": url}):
            try:
                return await _call(method, "/me/webhook", json=body)
            except PouchError as e:
                last = e
    raise last or PouchError("could not set the webhook")


# ---------------------------------------------------------------- vivid pay
# Accounts for payments to the apps users build (app/services/vividpay):
# one per order, one per app owner to gather earnings in, and payouts from
# it to the owner's bank. Pouch takes payout amounts in naira and reports
# amounts in kobo; the two helpers below are the only conversions.

def naira(kobo: int) -> float:
    """A kobo amount as the naira figure Pouch's payout requests take."""
    return round(kobo / 100, 2)


def kobo_of(value) -> int:
    """An amount Pouch reported, as kobo (POUCH_AMOUNTS_IN_KOBO decides)."""
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return int(round(amount if settings.POUCH_AMOUNTS_IN_KOBO else amount * 100))


async def ensure_customer_ref(ref: str, first_name: str, last_name: str,
                              email: str | None = None, phone: str | None = None) -> str:
    """A Pouch customer by our own reference (found, or created)."""
    found = await _call("GET", "/customers", params={"search": ref, "take": 5})
    for c in found.get("data") or []:
        if c.get("customer_reference") == ref:
            return c["id"]
    body = {"customer_reference": ref, "first_name": first_name[:60] or "Vivid",
            "last_name": last_name[:60] or "Pay"}
    if email and "@" in email:
        body["email"] = email
    if phone:
        body["phone_number"] = phone
    return (await _call("POST", "/customers", json=body))["data"]["id"]


async def open_account(customer_id: str, idempotency_key: str,
                       funding_limit_kobo: int | None = None) -> dict:
    """A naira virtual account held for Vivid. With a funding limit it
    refuses transfers beyond that total (an order's exact amount)."""
    body: dict = {"country": "NG", "currency": "NGN", "settlement_mode": "held"}
    if funding_limit_kobo:
        body["funding_limit"] = int(funding_limit_kobo)
    out = await _call("POST", f"/customers/{customer_id}/virtual-accounts", json=body,
                      headers={"X-Idempotency-Key": idempotency_key})
    return out["data"]


def idempotency_key(kind: str, ident: str) -> str:
    return str(uuid.uuid5(_NS, f"{kind}:{ident}"))


async def account_balance(va_id: str) -> int:
    """What a virtual account holds, in kobo."""
    data = (await _call("GET", f"/virtual-accounts/{va_id}/balance")).get("data") or {}
    return kobo_of(data.get("balance"))


async def banks() -> list[dict]:
    data = (await _call("GET", "/banks", params={"country": "NG", "currency": "NGN"})).get("data")
    if isinstance(data, dict):
        data = data.get("banks")
    return [b for b in (data or []) if b.get("uuid") and b.get("name")]


async def validate_account(account_number: str, bank_uuid: str) -> dict:
    """The name the bank holds for an account: {account_name, bank_name}."""
    return (await _call("POST", "/payouts/validate", json={
        "account_number": account_number, "bank_uuid": bank_uuid,
        "country": "NG", "currency": "NGN"})).get("data") or {}


async def payout_quote(amount_kobo: int) -> tuple[int, int]:
    """(fee, stamp duty) in kobo for a payout of this size. Pouch's quote
    route is not fully documented; when it does not answer, the configured
    fee and the published stamp duty rule (₦50 from ₦10,000) are used."""
    stamp = 5_000 if amount_kobo >= 1_000_000 else 0
    try:
        data = (await _call("POST", "/payouts/fee", json={
            "amount": naira(amount_kobo), "country": "NG", "currency": "NGN"})).get("data") or {}
    except PouchError:
        return settings.VIVIDPAY_PAYOUT_FEE_KOBO, stamp
    fee = data.get("fee")
    fee_kobo = kobo_of(fee) if fee is not None else settings.VIVIDPAY_PAYOUT_FEE_KOBO
    if data.get("stamp_duty") is not None:
        # Documented as naira.
        stamp = int(round(float(data["stamp_duty"]) * 100))
    return fee_kobo, stamp


async def create_payout(va_id: str, amount_kobo: int, account_number: str, bank_uuid: str,
                        reference: str, narration: str) -> dict:
    """Send money from one of our virtual accounts to a bank account (or to
    another of our accounts). The reference doubles as the idempotency key."""
    out = await _call("POST", "/payouts", json={
        "virtual_account_id": va_id, "reference": reference, "amount": naira(amount_kobo),
        "destination_account": account_number, "destination_bank_uuid": bank_uuid,
        "country": "NG", "currency": "NGN", "narration": narration[:100]},
        headers={"X-Idempotency-Key": idempotency_key("payout", reference)})
    return out.get("data") or {}


async def get_payout(payout_id: str) -> dict:
    return (await _call("GET", f"/payouts/{payout_id}")).get("data") or {}


async def find_payout(reference: str, pages: int = 3) -> dict | None:
    """A payout by our reference, from the newest pages."""
    for page in range(pages):
        rows = (await _call("GET", "/payouts", params={"skip": page * 100, "take": 100})).get("data") or []
        for row in rows:
            if row.get("reference") == reference:
                return row
        if len(rows) < 100:
            break
    return None


async def create_static_address(va_id: str, chain_id: int, refund_address: str,
                                kyc: dict) -> dict:
    """A crypto deposit address on a virtual account: what arrives is
    converted and credited to the account in naira. Pouch returns the
    account's existing address for the same network type."""
    return (await _call("POST", "/static-addresses", json={
        "virtual_account_id": va_id, "chain_id": chain_id,
        "evm_refund_address": refund_address, "user_kyc": kyc})).get("data") or {}


async def kyc_bvn(bvn: str, first_name: str, last_name: str, dob: str | None,
                  reference: str) -> dict:
    """A BVN checked against the registry (billable to Vivid)."""
    body = {"bvn": bvn, "first_name": first_name, "last_name": last_name, "reference": reference}
    if dob:
        body["dob"] = dob
    return (await _call("POST", "/kyc/bvn", json=body)).get("data") or {}
