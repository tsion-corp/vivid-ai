"""An app owner's earnings: a naira balance in kobo, changed only together
with an entry, under a row lock. Mirrors the credits wallet's ledger
(app/services/wallet/ledger.py) and never goes below zero."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VividPayAccount, VividPayEntry
from app.services.vividpay import VividPayError

PAYMENT, FEE, WITHDRAWAL, WITHDRAWAL_FEE, REVERSAL, ADJUSTMENT = (
    "payment", "fee", "withdrawal", "withdrawal_fee", "reversal", "adjustment")


class InsufficientEarnings(VividPayError):
    def __init__(self, balance: int, needed: int):
        super().__init__(f"Your earnings are ₦{balance / 100:,.2f}; this needs ₦{needed / 100:,.2f}.",
                         "insufficient_funds", 402)
        self.balance, self.needed = balance, needed


async def account_for(db: AsyncSession, user_id: str, lock: bool = False) -> VividPayAccount:
    q = select(VividPayAccount).where(VividPayAccount.user_id == user_id)
    if lock:
        q = q.with_for_update()
    account = (await db.execute(q)).scalar_one_or_none()
    if account is None:
        try:
            async with db.begin_nested():
                db.add(VividPayAccount(user_id=user_id))
        except IntegrityError:
            pass
        account = (await db.execute(q)).scalar_one()
    return account


async def _already(db: AsyncSession, provider: str, provider_ref: str) -> bool:
    return (await db.execute(select(VividPayEntry.id).where(
        VividPayEntry.provider == provider,
        VividPayEntry.provider_ref == provider_ref))).first() is not None


async def post(db: AsyncSession, owner_id: str, amount_kobo: int, kind: str, provider: str,
               provider_ref: str, **fields) -> VividPayEntry | None:
    """Add a signed amount; None if this provider_ref is already recorded.
    Raises InsufficientEarnings rather than go below zero. The caller commits."""
    if amount_kobo == 0 or await _already(db, provider, provider_ref):
        return None
    account = await account_for(db, owner_id, lock=True)
    after = account.balance_kobo + amount_kobo
    if after < 0:
        raise InsufficientEarnings(account.balance_kobo, -amount_kobo)
    entry = VividPayEntry(owner_id=owner_id, kind=kind, amount_kobo=amount_kobo,
                          balance_after=after, provider=provider, provider_ref=provider_ref,
                          **fields)
    try:
        async with db.begin_nested():
            db.add(entry)
            account.balance_kobo = after
    except IntegrityError:
        return None
    return entry


async def entries(db: AsyncSession, owner_id: str, limit: int = 50) -> list[VividPayEntry]:
    rows = await db.execute(select(VividPayEntry).where(VividPayEntry.owner_id == owner_id)
                            .order_by(VividPayEntry.created_at.desc()).limit(limit))
    return list(rows.scalars())
