"""What builds cost the user, and whether one may start.

Mobile app builds run on EAS. On the user's own Expo account (the "expo"
connector) they are free here: their quota, their bill with Expo. On Vivid's
account each build is charged at a fixed price per platform, recorded on the
build row (`price`, `charge`) and in the usage ledger, and refunded when the
build fails or is cancelled: nobody pays for an app they did not get.

There is no payment processor behind this yet. `can_start_build` is the one
seam where a balance or plan check plugs in; today it enforces a monthly cap
of charged builds per user.
"""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import usage
from app.core.config import settings
from app.db.models import BuilderAppBuild, BuilderProject, BuilderUsageEvent

VIVID, USER = "vivid", "user"
CHARGED, REFUNDED, NONE = "charged", "refunded", "none"
APP_BUILD = "app_build"


@dataclass
class Decision:
    ok: bool
    #: payment_required | not_configured, when not ok
    code: str = ""
    message: str = ""


def price_for(platform: str, account: str) -> int:
    """In the smallest unit of EAS_BUILD_CURRENCY; 0 on the user's account."""
    if account != VIVID:
        return 0
    return settings.EAS_BUILD_PRICE_IOS if platform == "ios" else settings.EAS_BUILD_PRICE_ANDROID


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
    if cap <= 0 or await vivid_builds_this_month(db, user_id) >= cap:
        return Decision(False, "payment_required",
                        f"You have used this month's {cap} app builds on Vivid. Connect your "
                        "own Expo account to keep building, or wait for next month.")
    return Decision(True)


def charge(db: AsyncSession, build: BuilderAppBuild) -> None:
    """Record the price on the row and a usage event; the caller commits."""
    build.price = price_for(build.platform, build.account)
    build.currency = settings.EAS_BUILD_CURRENCY
    build.charge = CHARGED if build.price else NONE
    db.add(BuilderUsageEvent(project_id=build.project_id, kind=APP_BUILD, quantity=1,
                             unit="builds",
                             meta={"build_id": build.id, "platform": build.platform,
                                   "account": build.account, "price": build.price,
                                   "currency": build.currency}))


def refund(db: AsyncSession, build: BuilderAppBuild) -> None:
    """A failed or cancelled build costs nothing; the ledger keeps both rows."""
    if build.charge != CHARGED:
        return
    build.charge = REFUNDED
    db.add(BuilderUsageEvent(project_id=build.project_id, kind=APP_BUILD, quantity=-1,
                             unit="builds",
                             meta={"build_id": build.id, "refund": True, "price": -build.price,
                                   "currency": build.currency}))
