"""Pouch's news for Vivid Pay, from its webhook and from the reconciler.

`on_transfer` takes a transfer as Pouch's API reports it (never as a
webhook claims it) and, when it went into a checkout's account, records it.
`on_payout_event` settles a withdrawal after re-reading it from the API.
`reconcile` catches whatever a webhook missed: transfers into checkout
accounts, pending withdrawals, and sweeps that failed.
"""
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VividPayCheckout, VividPayPayout, VividPayProject
from app.services.vividpay import checkouts, payouts
from app.services.wallet import pouch

log = logging.getLogger("vivid.pay.events")


async def checkout_for_account(db: AsyncSession, va_id: str | None) -> VividPayCheckout | None:
    if not va_id:
        return None
    return (await db.execute(select(VividPayCheckout).where(
        VividPayCheckout.va_id == va_id, VividPayCheckout.mode == "live"))).scalar_one_or_none()


async def on_transfer(db: AsyncSession, transfer: dict) -> VividPayCheckout | None:
    """Record a transfer into a checkout's account, move the money to the
    owner's earnings account and tell the app. None when the transfer is
    not a checkout's, or was recorded before. Commits."""
    c = await checkout_for_account(db, transfer.get("virtual_account_id"))
    if c is None:
        return None
    if not await checkouts.record_transfer(db, c, transfer):
        return None
    await db.commit()
    await checkouts.sweep(db, c)
    await db.commit()
    pay = await db.get(VividPayProject, c.project_id)
    if pay is not None:
        asyncio.create_task(checkouts.notify_app(pay, c))
    log.info("checkout %s %s (%s kobo)", c.id, c.status, c.paid_kobo)
    return c


async def on_payout_event(db: AsyncSession, payload: dict) -> VividPayPayout | None:
    data = payload.get("data") or {}
    pid = data.get("id")
    if not pid:
        return None
    payout = (await db.execute(select(VividPayPayout).where(
        VividPayPayout.pouch_payout_id == str(pid)))).scalar_one_or_none()
    if payout is None and data.get("reference"):
        payout = (await db.execute(select(VividPayPayout).where(
            VividPayPayout.id.in_(_ids_from_reference(str(data["reference"])))))).scalar_one_or_none()
    if payout is None:
        return None
    await payouts.refresh(db, payout)
    await db.commit()
    return payout


def _ids_from_reference(reference: str) -> list[str]:
    """wd-<32 hex> back to the payout's uuid."""
    if not reference.startswith("wd-") or len(reference) != 35:
        return []
    h = reference[3:]
    return [f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"]


async def reconcile(db: AsyncSession, transfers: list[dict] | None = None) -> int:
    """One pass. `transfers` are recent inbound transfers when the caller
    already fetched them (the wallet reconciler does). Commits."""
    done = 0
    for t in transfers or []:
        if await on_transfer(db, t):
            done += 1
    pending = (await db.execute(select(VividPayPayout).where(
        VividPayPayout.status == "pending"))).scalars()
    for p in list(pending):
        await payouts.refresh(db, p)
    await db.commit()
    stuck = (await db.execute(select(VividPayCheckout).where(
        VividPayCheckout.mode == "live", VividPayCheckout.sweep_status == "failed"))).scalars()
    for c in list(stuck):
        await checkouts.sweep(db, c)
    await db.commit()
    return done


def configured() -> bool:
    return pouch.configured()
