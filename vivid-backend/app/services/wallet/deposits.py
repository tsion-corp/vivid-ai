"""Money coming in: a provider's deposit, as the provider's own API reports
it, becomes a ledger credit on the right user's wallet, once.

Webhooks only say "look now"; the amount and the account always come from
an authenticated API call, and the reconciler finds anything a webhook
never announced. Both end here, and the ledger's unique provider_ref makes
the second arrival of the same deposit a no-op.
"""
import hashlib
import hmac
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import WalletEntry, WalletFunding
from app.services.wallet import MICRO, crypto_options, dextopus, fx, ledger, pouch

log = logging.getLogger("vivid.wallet.deposits")

POUCH, DEXTOPUS = "pouch", "dextopus"


async def _funding(db: AsyncSession, provider: str, external_id: str | None = None,
                   address: str | None = None) -> WalletFunding | None:
    q = select(WalletFunding).where(WalletFunding.provider == provider)
    if external_id:
        q = q.where(WalletFunding.external_id == external_id)
    elif address:
        q = q.where(WalletFunding.address == address)
    else:
        return None
    return (await db.execute(q)).scalars().first()


async def credit_pouch_transfer(db: AsyncSession, transfer: dict) -> WalletEntry | None:
    """A Pouch inbound transfer (from the API) credited in USD. None when it
    is not one of ours, not in NGN, or already credited."""
    funding = await _funding(db, POUCH, external_id=transfer.get("virtual_account_id"))
    if funding is None or not transfer.get("id"):
        return None
    currency = (transfer.get("currency") or "NGN").upper()
    raw = transfer.get("net_amount")
    if raw is None:
        raw = transfer.get("amount")
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        log.warning("pouch transfer %s has no usable amount: %r", transfer.get("id"), raw)
        return None
    minor = int(round(amount if settings.POUCH_AMOUNTS_IN_KOBO else amount * 100))
    if minor <= 0:
        return None
    micro, rate = await fx.minor_to_usd_micro(minor, currency)
    if micro <= 0:
        return None
    entry = await ledger.credit(
        db, funding.user_id, micro, ledger.DEPOSIT_BANK, POUCH, str(transfer["id"]),
        original_amount=str(minor), original_currency=currency, fx_rate=rate,
        description=f"Bank transfer from {transfer.get('payer_name') or 'your bank'}",
        meta={"payer_bank": transfer.get("payer_bank_name"), "fee": transfer.get("fee"),
              "spread_bps": settings.WALLET_FX_SPREAD_BPS})
    if entry is not None:
        log.info("credited %s micro-USD to %s from pouch transfer %s",
                 micro, funding.user_id, transfer["id"])
    return entry


async def credit_dextopus_deposit(db: AsyncSession, deposit: dict) -> WalletEntry | None:
    """A completed Dextopus deposit (from the API) credited by its settled
    USDC. None when not completed, not settled yet, not ours, or done."""
    if str(deposit.get("status") or "").upper() != "COMPLETED":
        return None
    ref = deposit.get("requestId") or deposit.get("id") or deposit.get("depositId")
    raw = deposit.get("settlementAmount")
    try:
        settled = int(str(raw))
    except (TypeError, ValueError):
        settled = 0
    if not ref or settled <= 0:
        return None                     # still settling: the reconciler retries
    funding = await _funding(db, DEXTOPUS, external_id=deposit.get("staticAddressId")) \
        or await _funding(db, DEXTOPUS, address=deposit.get("depositAddress"))
    if funding is None:
        return None
    if deposit.get("userId") and deposit["userId"] != funding.user_id:
        log.warning("dextopus deposit %s names user %s but the address is %s's; skipped",
                    ref, deposit.get("userId"), funding.user_id)
        return None
    micro = settled * MICRO // 10 ** crypto_options.SETTLEMENT_DECIMALS
    option = crypto_options.get(funding.option)
    entry = await ledger.credit(
        db, funding.user_id, micro, ledger.DEPOSIT_CRYPTO, DEXTOPUS, str(ref),
        original_amount=str(deposit.get("originAmountFormatted") or deposit.get("originAmount")),
        original_currency=option.symbol if option else None,
        description=f"{option.symbol} on {option.chain}" if option else "Crypto deposit",
        meta={"origin_tx": deposit.get("originTxHash"),
              "settlement_tx": deposit.get("settlementTxHash"),
              "origin_usd": deposit.get("originAmountUsd")})
    if entry is not None:
        log.info("credited %s micro-USD to %s from dextopus deposit %s", micro, funding.user_id, ref)
    return entry


# ------------------------------------------------------------ reconciling
async def reconcile(db: AsyncSession) -> int:
    """Credit whatever either provider reports that the ledger lacks.
    Returns how many were credited. The caller commits."""
    from app.services.vividpay import events as pay_events
    credited = 0
    if pouch.configured():
        try:
            seen: list[dict] = []
            for page in range(3):
                rows = await pouch.inbound_transfers(skip=page * 100, take=100)
                seen += rows
                for row in rows:
                    if await credit_pouch_transfer(db, row):
                        credited += 1
                if len(rows) < 100:
                    break
            await db.commit()
            # Vivid Pay: order payments the webhooks missed, pending
            # withdrawals and failed sweeps.
            credited += await pay_events.reconcile(db, seen)
        except (pouch.PouchError, fx.RatesUnavailable) as e:
            log.warning("pouch reconcile failed: %s", e)
    if dextopus.configured():
        try:
            for dep in await dextopus.deposits(status="completed", limit=100):
                if await credit_dextopus_deposit(db, dep):
                    credited += 1
        except dextopus.DextopusError as e:
            log.warning("dextopus reconcile failed: %s", e)
    return credited


# ---------------------------------------------------------------- webhooks
def verify_pouch_signature(raw_body: bytes, signature: str | None, secret: str) -> bool:
    """Pouch names the header (X-Liquifia-Signature) but not the scheme; an
    HMAC of the raw body with the webhook secret is accepted as SHA-256 or
    SHA-512 hex, with or without a "sha256=" prefix. The credit never rests
    on it: the transfer is fetched from the API before anything is paid."""
    if not (secret and signature):
        return False
    presented = signature.strip().lower().split("=", 1)[-1]
    for algo in (hashlib.sha256, hashlib.sha512):
        if hmac.compare_digest(presented, hmac.new(secret.encode(), raw_body, algo).hexdigest()):
            return True
    return False


async def on_pouch_event(db: AsyncSession, payload: dict):
    """A transfer into a wallet top-up account credits the wallet; into a
    Vivid Pay checkout's account, pays that order; a payout event settles
    a withdrawal. Anything else (e.g. money arriving in an owner's earnings
    account from a sweep) is ignored."""
    from app.services.vividpay import events as pay_events
    event = payload.get("event") or ""
    if event.startswith("payout."):
        return await pay_events.on_payout_event(db, payload)
    if event != "virtual_account.credited":
        return None
    transfer_id = (payload.get("data") or {}).get("id")
    if not transfer_id:
        return None
    transfer = await pouch.find_transfer(str(transfer_id))
    if transfer is None:
        log.warning("pouch webhook names transfer %s the API does not list", transfer_id)
        return None
    entry = await credit_pouch_transfer(db, transfer)
    if entry is not None:
        return entry
    return await pay_events.on_transfer(db, transfer)


async def on_dextopus_event(db: AsyncSession, payload: dict) -> WalletEntry | None:
    if payload.get("event") != "deposit.completed":
        return None
    request_id = (payload.get("data") or {}).get("requestId")
    if not request_id:
        return None
    deposit = await dextopus.deposit(str(request_id))
    if not deposit:
        log.warning("dextopus webhook names deposit %s the API does not know", request_id)
        return None
    return await credit_dextopus_deposit(db, deposit)


_RECONCILE_LOCK = "wallet:reconcile"


async def reconciler(redis, interval: float | None = None) -> None:
    """Run forever; the app's lifespan owns the task. One process per pass."""
    import asyncio

    from app.db.session import async_session
    interval = interval or settings.WALLET_RECONCILE_SECONDS
    while True:
        await asyncio.sleep(interval)
        if not (pouch.configured() or dextopus.configured()):
            continue
        try:
            if not await redis.set(_RECONCILE_LOCK, "1", nx=True, ex=max(int(interval) - 5, 1)):
                continue
        except Exception:
            pass
        try:
            async with async_session() as db:
                n = await reconcile(db)
                await db.commit()
            if n:
                log.info("reconciler credited %d deposit(s) the webhooks missed", n)
        except Exception as e:
            log.warning("wallet reconcile failed: %s", e)
