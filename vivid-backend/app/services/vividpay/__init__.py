"""Vivid Pay: payments for the apps users build.

An app's customer pays by bank transfer into an account number made for
their order (checkouts.py). When Pouch reports the transfer, the money less
Vivid's fee is credited to the app owner's earnings (earnings.py), in naira
kobo and separate from the USD credits wallet, and moved on Pouch from the
order's account to the owner's earnings account. The owner withdraws to a
Nigerian bank after a one-time BVN check (kyc.py, payouts.py).

Webhooks are hints: every credit rests on the transfer as Pouch's API
reports it, and each is recorded once (unique provider reference).
"""
import secrets as pysecrets

from app.core.config import settings


class VividPayError(Exception):
    """A request that cannot be done; str() is safe to show."""

    def __init__(self, message: str, code: str = "bad_request", status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


def fee_for(amount_kobo: int) -> int:
    """Vivid's fee on a payment: basis points between the minimum and the
    cap, never more than the payment."""
    fee = amount_kobo * settings.VIVIDPAY_FEE_BPS // 10_000
    fee = max(fee, settings.VIVIDPAY_MIN_FEE_KOBO)
    fee = min(fee, settings.VIVIDPAY_FEE_CAP_KOBO)
    return max(min(fee, amount_kobo), 0)


def new_key(prefix: str) -> str:
    return f"{prefix}_{pysecrets.token_urlsafe(24)}"


def key_hash(key: str) -> str:
    import hashlib
    return hashlib.sha256(key.encode()).hexdigest()
