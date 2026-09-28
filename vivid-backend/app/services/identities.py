"""One account, several ways to sign in to it.

Decane gives each sign-in method its own user id: the same person signing in
with an emailed code and with Google gets two ids, and so, before this, two
Vivid accounts. `user_identities` maps each Decane id to an account, and an
account can hold several.

Linking always needs proof on both sides. An emailed code proves its address
(`User.verified_email`); a Google sign-in's email reaches us through the
browser and proves nothing, so it is never enough on its own:

- At sign-in: a Google id we have not seen, whose (claimed) email is an
  existing account's verified address, is not signed in. The person gets a
  code at that address instead; entering it joins Google to that account.
- In the account settings: signed in to one account, the person signs in
  with the other method, which proves they hold it too. The other account's
  projects and the rest move over (`merge`), unless money makes that unsafe.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (ApiKey, Attachment, BuilderMember, BuilderMessage, BuilderProject, Chat,
                           Connector, Gift, MediaJob, ModelUsage, PushDevice, Subscription, User,
                           UserIdentity, VividPayAccount, VividPayBankAccount, VividPayCheckout,
                           VividPayPayout, VividPayProject, Wallet)
from app.services import account as account_svc
from app.services.plans import usage
from app.services.wallet import ledger

log = logging.getLogger("vivid.identities")


def legacy_email(uid: str) -> str:
    """How accounts were keyed before identities: a synthetic address."""
    return f"decane_{uid}@users.vivid"


async def resolve(db: AsyncSession, uid: str) -> User | None:
    """The account this Decane id signs in to, if any (older accounts are
    found by their synthetic address and get an identity row)."""
    row = await db.get(UserIdentity, uid)
    if row is not None:
        return await db.get(User, row.user_id)
    user = (await db.execute(select(User).where(User.email == legacy_email(uid)))).scalar_one_or_none()
    if user is not None:
        db.add(UserIdentity(decane_uid=uid, user_id=user.id, method="other"))
        await db.flush()
    return user


async def attach(db: AsyncSession, uid: str, user: User, method: str, email: str | None = None) -> None:
    row = await db.get(UserIdentity, uid)
    if row is None:
        db.add(UserIdentity(decane_uid=uid, user_id=user.id, method=method, email=email))
    else:
        row.user_id, row.method = user.id, method
        row.email = email or row.email
    if method == "email" and email and not user.verified_email:
        user.verified_email = email
    await db.flush()


async def by_verified_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(
        User.verified_email == email.lower(), User.deleted_at.is_(None)))).scalars().first()


async def methods(db: AsyncSession, user: User) -> list[UserIdentity]:
    return list((await db.execute(select(UserIdentity).where(UserIdentity.user_id == user.id)
                                  .order_by(UserIdentity.created_at))).scalars())


# ------------------------------------------------------------------- merge
async def merge_blockers(db: AsyncSession, other: User) -> list[dict]:
    """Why `other` cannot be folded into another account. Money that cannot
    move by a simple transfer blocks: a paid plan, and anything Vivid Pay
    (earnings, the identity check, a bank account, payouts)."""
    out = []
    sub = await usage.active_subscription(db, other.id)
    if sub is not None:
        out.append({"code": "paid_plan", "message": "That account has a paid plan. Let it end (cancel it there), "
                    "then connect it."})
    vivid_pay = any([
        await db.get(VividPayAccount, other.id),
        (await db.execute(select(VividPayProject.project_id).where(VividPayProject.owner_id == other.id))).first(),
        (await db.execute(select(VividPayCheckout.id).where(VividPayCheckout.owner_id == other.id))).first(),
        (await db.execute(select(VividPayPayout.id).where(VividPayPayout.owner_id == other.id))).first(),
        (await db.execute(select(VividPayBankAccount.id).where(VividPayBankAccount.user_id == other.id))).first(),
    ])
    if vivid_pay:
        out.append({"code": "vivid_pay", "message": "That account takes payments with Vivid Pay, so it can't be "
                    "merged. Write to support and we'll combine them."})
    return out


async def merge(db: AsyncSession, keep: User, other: User) -> dict:
    """Fold `other` into `keep`: its projects, shares, messages, gifts, chats,
    keys, devices and connections move; its wallet balance and extra credits
    transfer; its sign-in methods now open `keep`; `other` is closed. Raises
    ValueError(blockers) when it cannot. The caller commits."""
    stuck = await merge_blockers(db, other)
    if stuck:
        raise ValueError(stuck)
    moved = {"projects": 0}

    projects = (await db.execute(select(BuilderProject).where(BuilderProject.owner_id == other.id))).scalars()
    for project in list(projects):
        project.owner_id = keep.id
        moved["projects"] += 1
    # Memberships: a project `keep` already owns or is in keeps that; others move.
    owned = set((await db.execute(select(BuilderProject.id).where(BuilderProject.owner_id == keep.id))).scalars())
    mine = set((await db.execute(select(BuilderMember.project_id).where(BuilderMember.user_id == keep.id))).scalars())
    for member in list((await db.execute(select(BuilderMember).where(BuilderMember.user_id == other.id))).scalars()):
        if member.project_id in owned or member.project_id in mine:
            await db.delete(member)
        else:
            member.user_id = keep.id
    await db.execute(update(BuilderMessage).where(BuilderMessage.user_id == other.id).values(user_id=keep.id))
    await db.execute(update(Gift).where(Gift.from_user == other.id).values(from_user=keep.id))
    await db.execute(update(Gift).where(Gift.claimed_by == other.id).values(claimed_by=keep.id))
    for model, col in ((Chat, Chat.user_id), (Attachment, Attachment.user_id), (MediaJob, MediaJob.user_id),
                       (ModelUsage, ModelUsage.user_id), (PushDevice, PushDevice.user_id),
                       (ApiKey, ApiKey.user_id), (ApiKey, ApiKey.owner_user_id)):
        await db.execute(update(model).where(col == other.id).values({col.key: keep.id}))
    # One connection per provider: keep's wins.
    have = set((await db.execute(select(Connector.provider).where(Connector.user_id == keep.id))).scalars())
    for connector in list((await db.execute(select(Connector).where(Connector.user_id == other.id))).scalars()):
        if connector.provider in have:
            await db.delete(connector)
        else:
            connector.user_id = keep.id

    wallet = await db.get(Wallet, other.id)
    if wallet is not None:
        if wallet.balance_micro > 0:
            amount = wallet.balance_micro
            await ledger.debit(db, other.id, amount, ledger.ADJUSTMENT, "vivid", f"merge-out:{other.id}",
                               description="Moved to your other account")
            await ledger.credit(db, keep.id, amount, ledger.ADJUSTMENT, "vivid", f"merge-in:{other.id}",
                                description="From your other account")
            moved["wallet_micro"] = amount
        if wallet.extra_tokens > 0:
            mine_wallet = await ledger.wallet_for(db, keep.id, lock=True)
            mine_wallet.extra_tokens += wallet.extra_tokens
            wallet.extra_tokens = 0
    await db.execute(delete(Subscription).where(Subscription.user_id == other.id))

    for row in await methods(db, other):
        row.user_id = keep.id
    legacy = other.email if other.email.startswith("decane_") else None
    if legacy:
        # Its sign-in id as a row, so it still opens `keep` once `other` is closed.
        uid = legacy.removeprefix("decane_").removesuffix("@users.vivid")
        if await db.get(UserIdentity, uid) is None:
            db.add(UserIdentity(decane_uid=uid, user_id=keep.id, method="other"))
    if other.verified_email and not keep.verified_email:
        keep.verified_email = other.verified_email
    if not keep.name and other.name:
        keep.name = other.name

    other.email = account_svc.anonymous_email(other.id)
    other.name = other.avatar_url = other.profile_email = other.verified_email = None
    other.password_hash = account_svc.DELETED_PASSWORD
    other.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    log.info("account %s merged into %s: %s", other.id, keep.id, moved)
    return moved
