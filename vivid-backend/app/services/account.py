"""Deleting an account.

The stores require it, and the rules the user agreed:
- refused while a withdrawal is pending or earnings are unwithdrawn (the
  person withdraws first), so nobody deletes money they are owed;
- a wallet balance under ACCOUNT_DELETE_FORFEIT_MICRO is forfeited; at or
  above it, it stays on the row for support to refund by hand;
- projects, files, keys, phones, connectors and chats go at once;
- the money and KYC records (wallet ledger, Vivid Pay checkouts, entries,
  payouts, the KYC name and encrypted BVN) are kept for seven years, keyed
  to the anonymised user row; purge_expired() removes them after that.

The user row itself is never deleted (every money table cascades from it):
it is anonymised and stamped deleted_at, which every credential check
refuses from then on.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (ApiKey, Attachment, BuilderProject, Chat, Connector, MediaJob,
                           ModelUsage, PushDevice, Subscription, User, VividPayAccount,
                           VividPayBankAccount, VividPayCheckout, VividPayEntry, VividPayPayout,
                           Wallet, WalletEntry, WalletFunding)
from app.services.wallet import ledger

log = logging.getLogger("vivid.account")

RETENTION = timedelta(days=7 * 365)
DELETED_PASSWORD = "!deleted"


def anonymous_email(user_id: str) -> str:
    return f"deleted_{user_id}@users.vivid"


async def blockers(db: AsyncSession, user: User) -> list[dict]:
    """Why the account cannot be deleted yet, each with a code and a line
    to show. Empty when it can."""
    out = []
    pending = (await db.execute(select(VividPayPayout).where(
        VividPayPayout.owner_id == user.id, VividPayPayout.status == "pending"))).scalars().first()
    if pending is not None:
        out.append({"code": "pending_withdrawal",
                    "message": "A withdrawal is still on its way to your bank. Wait for it to arrive, then try again."})
    account = await db.get(VividPayAccount, user.id)
    if account is not None and account.balance_kobo > 0:
        out.append({"code": "earnings_unwithdrawn",
                    "message": f"You have ₦{account.balance_kobo / 100:,.2f} of earnings. Withdraw them first.",
                    "amount_kobo": account.balance_kobo})
    return out


async def preview(db: AsyncSession, user: User) -> dict:
    """What deleting would do, for the confirmation screen."""
    wallet = await db.get(Wallet, user.id)
    balance = wallet.balance_micro if wallet else 0
    projects = int(len((await db.execute(select(BuilderProject.id).where(
        BuilderProject.owner_id == user.id))).all()))
    return {"blockers": await blockers(db, user),
            "projects": projects,
            "wallet_balance_micro": balance,
            "wallet_outcome": ("none" if balance <= 0 else
                               "forfeited" if balance < settings.ACCOUNT_DELETE_FORFEIT_MICRO
                               else "refund_by_support"),
            "forfeit_below_micro": settings.ACCOUNT_DELETE_FORFEIT_MICRO,
            "records_kept_days": RETENTION.days}


async def delete_account(db: AsyncSession, user: User, delete_project) -> dict:
    """Do it. `delete_project(project)` is the builder's own project
    deletion (sandbox, Decane client, snapshots), awaited per project.
    Raises ValueError with the blockers when it cannot. The caller commits."""
    stuck = await blockers(db, user)
    if stuck:
        raise ValueError(stuck)
    projects = list((await db.execute(select(BuilderProject).where(
        BuilderProject.owner_id == user.id))).scalars())
    for project in projects:
        await delete_project(project)

    wallet = await db.get(Wallet, user.id)
    outcome = "none"
    if wallet is not None and 0 < wallet.balance_micro < settings.ACCOUNT_DELETE_FORFEIT_MICRO:
        await ledger.debit(db, user.id, wallet.balance_micro, ledger.ADJUSTMENT, "vivid",
                           f"forfeit:{user.id}", description="Forfeited when the account was deleted")
        outcome = "forfeited"
    elif wallet is not None and wallet.balance_micro > 0:
        outcome = "refund_by_support"
        log.warning("account %s deleted with a wallet balance of %d micro-USD to refund",
                    user.id, wallet.balance_micro)

    # Everything that is the person's, not a money record.
    for model, col in ((ApiKey, ApiKey.user_id), (ApiKey, ApiKey.owner_user_id),
                       (PushDevice, PushDevice.user_id), (Connector, Connector.user_id),
                       (Chat, Chat.user_id), (Attachment, Attachment.user_id),
                       (MediaJob, MediaJob.user_id), (ModelUsage, ModelUsage.user_id),
                       (VividPayBankAccount, VividPayBankAccount.user_id),
                       (Subscription, Subscription.user_id)):
        await db.execute(delete(model).where(col == user.id))

    now = datetime.now(timezone.utc)
    user.email = anonymous_email(user.id)
    user.name, user.avatar_url, user.profile_email = None, None, None
    user.password_hash = DELETED_PASSWORD
    user.deleted_at = now
    await db.flush()
    log.info("account %s deleted (%d projects, wallet %s)", user.id, len(projects), outcome)
    return {"projects_deleted": len(projects), "wallet_outcome": outcome}


async def purge_expired(db: AsyncSession, now: datetime | None = None) -> int:
    """Remove the money and KYC records of accounts deleted longer ago than
    RETENTION, then the rows themselves. Returns how many accounts. The
    caller commits."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - RETENTION
    users = list((await db.execute(select(User).where(
        User.deleted_at.is_not(None), User.deleted_at < cutoff))).scalars())
    for u in users:
        for model, col in ((VividPayEntry, VividPayEntry.owner_id),
                           (VividPayPayout, VividPayPayout.owner_id),
                           (VividPayCheckout, VividPayCheckout.owner_id),
                           (VividPayAccount, VividPayAccount.user_id),
                           (WalletEntry, WalletEntry.user_id), (WalletFunding, WalletFunding.user_id),
                           (Wallet, Wallet.user_id)):
            await db.execute(delete(model).where(col == u.id))
        await db.delete(u)
    return len(users)
