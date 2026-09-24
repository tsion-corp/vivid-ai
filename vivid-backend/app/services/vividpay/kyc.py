"""The one-time identity check before an owner's first withdrawal: their
BVN against the registry (through Pouch), and afterwards every bank account
they withdraw to must be in that name."""
import re
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import secrets as vault
from app.db.models import VividPayAccount
from app.services.vividpay import VividPayError, earnings
from app.services.wallet import pouch


def _tokens(name: str | None) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", (name or "").lower()) if len(t) > 1}


def names_match(kyc_name: str | None, bank_name: str | None) -> bool:
    """A bank account's name is the verified person's when it shares at
    least two of their names (banks drop or reorder middle names), or all
    of them when fewer than two are known."""
    a, b = _tokens(kyc_name), _tokens(bank_name)
    if not a or not b:
        return False
    return len(a & b) >= min(2, len(a), len(b))


async def verify(db: AsyncSession, user_id: str, bvn: str, first_name: str, last_name: str,
                 dob: str | None) -> VividPayAccount:
    """Check the BVN; on a match the account is verified in the registry's
    name. The BVN is kept encrypted. The caller commits."""
    bvn = re.sub(r"\D", "", bvn or "")
    if len(bvn) != 11:
        raise VividPayError("A BVN is 11 digits.")
    account = await earnings.account_for(db, user_id, lock=True)
    if account.kyc_status == "verified":
        return account
    try:
        result = await pouch.kyc_bvn(bvn, first_name.strip(), last_name.strip(), dob,
                                     reference=f"kyc-{user_id.replace('-', '')[:24]}-"
                                               f"{int(datetime.now(timezone.utc).timestamp())}")
    except pouch.PouchError as e:
        raise VividPayError(f"Could not check the BVN right now: {e}", "upstream_error", 502)
    if not result.get("verified"):
        account.kyc_status = "failed"
        code = result.get("response_code")
        raise VividPayError("That BVN was not found." if code == "25" else
                            "The BVN did not match that name and date of birth.", "kyc_failed")
    account.kyc_status = "verified"
    account.kyc_name = (result.get("full_name")
                        or " ".join(filter(None, [result.get("first_name"), result.get("middle_name"),
                                                  result.get("last_name")])))[:160]
    account.kyc_bvn_enc = vault.encrypt(bvn) if vault.configured() else None
    account.kyc_at = datetime.now(timezone.utc)
    return account
