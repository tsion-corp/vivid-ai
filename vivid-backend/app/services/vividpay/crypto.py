"""Paying a checkout in crypto.

Pouch gives the order's own virtual account a deposit address; whatever
arrives there (USDC, USDT, on any chain its routing takes) is converted and
credited to that account in naira, as an inbound transfer. From there the
payment is recorded exactly like a bank transfer (checkouts.record_transfer
via events.on_transfer), so the owner is paid in naira, less Vivid's fee.

Pouch has no rate endpoint, so the amount the customer is asked to send is
an estimate: the rate of Pouch's last conversion for us (from its webhook,
kept only if it is near the configured rate, since that body is not
authenticated), else VIVIDPAY_CRYPTO_NGN_RATE, plus a small buffer. The
owner is always credited what Pouch actually credited.
"""
import logging
import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import VividPayCheckout
from app.services.vividpay import VividPayError
from app.services.vividpay.checkouts import _aware, _now
from app.services.wallet import pouch

log = logging.getLogger("vivid.pay.crypto")

#: Network type -> (a chain Pouch opens the address for, what the customer
#: is told). One EVM address takes deposits on every EVM chain.
NETWORKS = {
    "evm": (8453, "USDC or USDT on Base, BNB Chain, Polygon, Arbitrum or Ethereum"),
}
TEST_ADDRESS = "0x0000000000000000000000000000000000vivid0"

_last_rate: float | None = None


def enabled() -> bool:
    return settings.VIVIDPAY_CRYPTO_ENABLED


def rate() -> float:
    """Naira per USDC for estimates."""
    return _last_rate or settings.VIVIDPAY_CRYPTO_NGN_RATE


def note_rate(fill: dict) -> None:
    """Keep the rate of a conversion Pouch reported, if it is plausible."""
    global _last_rate
    try:
        crypto = float(fill.get("crypto_amount") or 0)
        local = float(fill.get("local_amount_final") or fill.get("local_amount_estimated") or 0)
    except (TypeError, ValueError):
        return
    if crypto <= 0 or local <= 0 or str(fill.get("crypto_currency", "")).upper() not in ("USDC", "USDT"):
        return
    r = local / 100 / crypto                        # webhook amounts are kobo
    base = settings.VIVIDPAY_CRYPTO_NGN_RATE
    if base * 0.75 <= r <= base * 1.25:
        _last_rate = r


def due(c: VividPayCheckout) -> str:
    """What is left to pay, in USDC, rounded up to the cent, with the buffer."""
    left = max(c.amount_kobo - c.paid_kobo, 0)
    usdc = left / 100 / (c.crypto_rate or rate()) * (1 + settings.VIVIDPAY_CRYPTO_BUFFER_BPS / 10_000)
    return f"{math.ceil(usdc * 100) / 100:.2f}"


def view(c: VividPayCheckout) -> dict | None:
    if not c.crypto_address:
        return None
    return {"address": c.crypto_address, "network": c.crypto_network,
            "accepts": NETWORKS.get(c.crypto_network or "", (0, ""))[1],
            "due_usdc": due(c), "rate": round(c.crypto_rate or rate(), 2), "estimate": True}


def _payer(payer: dict | None) -> dict:
    """Pouch's KYC for the depositor: name, email, phone and address."""
    p = {k: str(v).strip()[:160] for k, v in (payer or {}).items() if v}
    missing = [k for k in ("name", "email", "phone", "address") if not p.get(k)]
    if missing:
        raise VividPayError("To pay in crypto we need the payer's " + ", ".join(missing) + ".")
    if "@" not in p["email"]:
        raise VividPayError("That email address does not look right.")
    return {"full_name": p["name"], "email": p["email"], "phone": p["phone"], "address": p["address"]}


async def open_address(db: AsyncSession, c: VividPayCheckout, network: str,
                       payer: dict | None) -> VividPayCheckout:
    """Give the checkout a crypto address (once). The caller commits."""
    if not enabled():
        raise VividPayError("Crypto payments are not available yet.", "unavailable", 403)
    if network not in NETWORKS:
        raise VividPayError("Choose a network: " + ", ".join(NETWORKS) + ".")
    if c.status == "paid":
        raise VividPayError("This order is already paid.", "conflict", 409)
    if c.status == "pending" and _aware(c.expires_at) < _now():
        raise VividPayError("This checkout has expired; start a new one.", "expired", 410)
    if c.crypto_address:
        return c
    kyc = _payer(payer)
    if c.mode == "test":
        c.crypto_address, c.crypto_network, c.crypto_rate = TEST_ADDRESS, network, rate()
        return c
    refund = settings.DEXTOPUS_SETTLEMENT_ADDRESS
    if not (c.va_id and refund):
        raise VividPayError("Crypto payments are not set up on this server.", "unavailable", 503)
    try:
        out = await pouch.create_static_address(c.va_id, NETWORKS[network][0], refund, kyc)
    except pouch.PouchError as e:
        raise VividPayError(f"Could not open a crypto address: {e}", "upstream_error", 502)
    if not out.get("deposit_address"):
        raise VividPayError("The crypto partner returned no address.", "upstream_error", 502)
    c.crypto_address = out["deposit_address"]
    c.crypto_network = network
    c.crypto_rate = rate()
    return c
