"""The only code that changes a wallet.

Every change is a WalletEntry and the new balance, written together while
the wallet row is locked (SELECT ... FOR UPDATE), so two charges racing each
other can never both pass the balance check. (provider, provider_ref) is
unique: crediting the same deposit twice, from a repeated webhook or the
reconciler finding it again, records nothing the second time.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Wallet, WalletEntry

DEPOSIT_BANK, DEPOSIT_CRYPTO = "deposit_bank", "deposit_crypto"
CHARGE, REFUND, TOKEN_PACK, PLAN, ADJUSTMENT = "charge", "refund", "token_pack", "plan", "adjustment"


class InsufficientFunds(Exception):
    def __init__(self, balance_micro: int, needed_micro: int) -> None:
        super().__init__("insufficient funds")
        self.balance_micro = balance_micro
        self.needed_micro = needed_micro


async def wallet_for(db: AsyncSession, user_id: str, lock: bool = False) -> Wallet:
    """The user's wallet, created empty on first use."""
    q = select(Wallet).where(Wallet.user_id == user_id)
    if lock:
        q = q.with_for_update()
    wallet = (await db.execute(q)).scalar_one_or_none()
    if wallet is not None:
        return wallet
    try:
        async with db.begin_nested():
            db.add(Wallet(user_id=user_id, balance_micro=0, extra_tokens=0))
    except IntegrityError:
        pass                                # another request made it first
    return (await db.execute(q)).scalar_one()


async def balance(db: AsyncSession, user_id: str) -> int:
    return (await wallet_for(db, user_id)).balance_micro


async def _already(db: AsyncSession, provider: str, provider_ref: str) -> WalletEntry | None:
    return (await db.execute(select(WalletEntry).where(
        WalletEntry.provider == provider,
        WalletEntry.provider_ref == provider_ref))).scalar_one_or_none()


async def _post(db: AsyncSession, user_id: str, amount_micro: int, kind: str, provider: str,
                provider_ref: str, *, allow_negative: bool = False, **fields) -> WalletEntry | None:
    if await _already(db, provider, provider_ref) is not None:
        return None
    wallet = await wallet_for(db, user_id, lock=True)
    new_balance = wallet.balance_micro + amount_micro
    if new_balance < 0 and not allow_negative:
        raise InsufficientFunds(wallet.balance_micro, -amount_micro)
    entry = WalletEntry(user_id=user_id, kind=kind, amount_micro=amount_micro,
                        balance_after=new_balance, provider=provider,
                        provider_ref=provider_ref, **fields)
    try:
        async with db.begin_nested():
            db.add(entry)
            wallet.balance_micro = new_balance
    except IntegrityError:
        # Recorded by a concurrent request between the check and the insert.
        await db.refresh(wallet)
        return None
    return entry


async def credit(db: AsyncSession, user_id: str, amount_micro: int, kind: str, provider: str,
                 provider_ref: str, **fields) -> WalletEntry | None:
    """Add money. Returns None when this provider_ref was already credited.
    The caller commits."""
    if amount_micro <= 0:
        raise ValueError("a credit must be positive")
    return await _post(db, user_id, amount_micro, kind, provider, provider_ref, **fields)


async def debit(db: AsyncSession, user_id: str, amount_micro: int, kind: str, provider: str,
                provider_ref: str, **fields) -> WalletEntry | None:
    """Take money; InsufficientFunds when the balance is short. Returns None
    when this provider_ref was already charged. The caller commits."""
    if amount_micro <= 0:
        raise ValueError("a debit must be positive")
    return await _post(db, user_id, -amount_micro, kind, provider, provider_ref, **fields)


async def entries(db: AsyncSession, user_id: str, limit: int = 50,
                  before=None) -> list[WalletEntry]:
    q = select(WalletEntry).where(WalletEntry.user_id == user_id)
    if before is not None:
        q = q.where(WalletEntry.created_at < before)
    rows = await db.execute(q.order_by(WalletEntry.created_at.desc()).limit(limit))
    return list(rows.scalars())
