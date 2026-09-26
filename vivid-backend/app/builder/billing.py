"""What builds cost the user, and whether one may start.

Mobile app builds run on EAS. On the user's own Expo account (the "expo"
connector) they are free here: their quota, their bill with Expo. On Vivid's
account each build costs a fixed USD price per platform, debited from the
user's wallet when the build starts and credited back if it fails or is
cancelled: nobody pays for an app they did not get. The price and whether
it was charged or refunded are also kept on the build row.
"""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import usage
from app.core.config import settings
from app.db.models import BuilderAppBuild, BuilderProject, BuilderUsageEvent
from app.services.wallet import ledger, to_micro

VIVID, USER = "vivid", "user"
CHARGED, REFUNDED, NONE = "charged", "refunded", "none"
APP_BUILD = "app_build"


@dataclass
class Decision:
    ok: bool
    #: insufficient_funds | payment_required | not_configured, when not ok.
    #: `details` carries the numbers and `options` (top_up, own_expo_account,
    #: wait); the message says only what happened.
    code: str = ""
    message: str = ""
    details: dict | None = None


def price_for(platform: str, account: str) -> int:
    """In micro-USD; 0 on the user's own account."""
    if account != VIVID:
        return 0
    return to_micro(settings.EAS_BUILD_PRICE_IOS_USD if platform == "ios"
                    else settings.EAS_BUILD_PRICE_ANDROID_USD)


async def vivid_builds_this_month(db: AsyncSession, user_id: str) -> int:
    """Charged builds on Vivid's account since the 1st; refunds do not count."""
    q = (select(func.count()).select_from(BuilderAppBuild)
         .join(BuilderProject, BuilderProject.id == BuilderAppBuild.project_id)
         .where(BuilderProject.owner_id == user_id, BuilderAppBuild.account == VIVID,
                BuilderAppBuild.charge == CHARGED,
                BuilderAppBuild.created_at >= usage.month_start()))
    return int((await db.execute(q)).scalar_one())


async def can_start_build(db: AsyncSession, user_id: str, platform: str,
                          account: str) -> Decision:
    if account == USER:
        return Decision(True)
    if not settings.EXPO_TOKEN or not settings.EXPO_OWNER:
        return Decision(False, "not_configured",
                        "Vivid's build service is not set up here. Connect your own Expo "
                        "account to build.")
    cap = settings.EAS_VIVID_BUILDS_PER_MONTH
    if cap > 0 and await vivid_builds_this_month(db, user_id) >= cap:
        return Decision(False, "payment_required",
                        f"You have used this month's {cap} app builds on Vivid.",
                        {"cap": cap, "options": ["own_expo_account", "wait"]})
    price = price_for(platform, account)
    have = await ledger.balance(db, user_id)
    if have < price:
        return Decision(False, "insufficient_funds",
                        f"A {platform} build costs ${price / 1e6:,.2f} and your wallet has "
                        f"${have / 1e6:,.2f}.",
                        {"price_micro": price, "balance_micro": have, "short_micro": price - have,
                         "options": ["top_up", "own_expo_account"]})
    return Decision(True)


async def charge(db: AsyncSession, build: BuilderAppBuild, user_id: str) -> None:
    """Debit the wallet and record the price on the row; the caller commits.
    Raises ledger.InsufficientFunds if the balance fell in the meantime."""
    build.price = price_for(build.platform, build.account)
    build.currency = "USD"
    build.charge = CHARGED if build.price else NONE
    if build.price:
        await ledger.debit(db, user_id, build.price, ledger.CHARGE, VIVID, f"build:{build.id}",
                           ref=build.id, original_amount=str(build.price / 1e6),
                           original_currency="USD",
                           description=f"{'iOS' if build.platform == 'ios' else 'Android'} "
                                       f"{build.profile} build")
    db.add(BuilderUsageEvent(project_id=build.project_id, kind=APP_BUILD, quantity=1,
                             unit="builds",
                             meta={"build_id": build.id, "platform": build.platform,
                                   "account": build.account, "price_micro_usd": build.price}))


async def refund(db: AsyncSession, build: BuilderAppBuild) -> None:
    """A failed or cancelled build costs nothing. Idempotent: the credit's
    provider_ref is the build, so a second refund records nothing."""
    if build.charge != CHARGED:
        return
    build.charge = REFUNDED
    owner = (await db.execute(select(BuilderProject.owner_id).where(
        BuilderProject.id == build.project_id))).scalar_one_or_none()
    if owner and build.price:
        await ledger.credit(db, owner, build.price, ledger.REFUND, VIVID, f"refund:{build.id}",
                            ref=build.id, description="Refund: the build did not finish")
    db.add(BuilderUsageEvent(project_id=build.project_id, kind=APP_BUILD, quantity=-1,
                             unit="builds", meta={"build_id": build.id, "refund": True}))
