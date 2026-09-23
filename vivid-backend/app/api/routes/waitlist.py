"""The waitlist: a public form to join, and an admin view to read it.

Joining needs no account, so it is limited per address instead. Reading
the list is gated by ADMIN_TOKEN rather than a user session: there are no
admin users yet, and the list is people's names, emails and phone numbers.
"""
import csv
import hmac
import io

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.errors import APIError
from app.db.models import WaitlistEntry
from app.schemas.waitlist import WaitlistEntryOut, WaitlistJoin, WaitlistJoined, WaitlistPage
from app.services import rate_limit

router = APIRouter(prefix="/waitlist", tags=["waitlist"])

_CSV_COLUMNS = ("created_at", "first_name", "last_name", "email", "phone_no", "use_case",
                "heard_from")


def _client_ip(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else ""))


def require_admin(request: Request) -> None:
    token = settings.ADMIN_TOKEN
    if not token:
        raise APIError(503, "not_configured", "The waitlist view is not set up on this server.")
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(presented, token):
        raise APIError(401, "unauthorized", "Admin token required")


@router.post("", response_model=WaitlistJoined, status_code=201)
async def join(body: WaitlistJoin, request: Request, response: Response,
               db: AsyncSession = Depends(get_db)):
    redis = getattr(request.app.state, "redis", None)
    if redis is not None and not await rate_limit.check_bucket(
            redis, f"waitlist:{_client_ip(request)}", settings.WAITLIST_PER_MINUTE):
        raise APIError(429, "rate_limited", "Too many sign-ups from this address. Try again in a minute.")

    email = body.email.lower()
    entry = (await db.execute(
        select(WaitlistEntry).where(WaitlistEntry.email == email))).scalar_one_or_none()
    already = entry is not None
    if entry is None:
        entry = WaitlistEntry(email=email)
        db.add(entry)
    entry.first_name = body.first_name
    entry.last_name = body.last_name
    entry.phone_no = body.phone_no
    entry.use_case = body.use_case
    entry.heard_from = body.heard_from
    try:
        await db.commit()
    except IntegrityError:
        # The same email submitted twice at once: the other request won,
        # and this one is a repeat of it.
        await db.rollback()
        already = True
    if already:
        response.status_code = 200
    return WaitlistJoined(already_joined=already)


@router.get("", response_model=WaitlistPage, dependencies=[Depends(require_admin)])
async def list_entries(
        q: str | None = Query(None, max_length=200,
                              description="Match on name, email, phone, use case or source"),
        heard_from: str | None = Query(None, max_length=160),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        format: str = Query("json", pattern="^(json|csv)$"),
        db: AsyncSession = Depends(get_db)):
    """Newest first. `format=csv` returns every matching row as a download,
    ignoring limit and offset."""
    filters = []
    if q:
        like = f"%{q.strip().lower()}%"
        filters.append(or_(*(func.lower(col).like(like) for col in (
            WaitlistEntry.first_name, WaitlistEntry.last_name, WaitlistEntry.email,
            WaitlistEntry.phone_no, WaitlistEntry.use_case, WaitlistEntry.heard_from))))
    if heard_from:
        filters.append(func.lower(WaitlistEntry.heard_from) == heard_from.strip().lower())

    query = select(WaitlistEntry).where(*filters).order_by(WaitlistEntry.created_at.desc())

    if format == "csv":
        rows = (await db.execute(query)).scalars().all()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(_CSV_COLUMNS)
        for row in rows:
            writer.writerow([row.created_at.isoformat() if col == "created_at"
                             else getattr(row, col) or "" for col in _CSV_COLUMNS])
        return Response(out.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="waitlist.csv"'})

    total = (await db.execute(
        select(func.count()).select_from(WaitlistEntry).where(*filters))).scalar_one()
    rows = (await db.execute(query.limit(limit).offset(offset))).scalars().all()
    return WaitlistPage(total=total, entries=[WaitlistEntryOut.model_validate(r) for r in rows])


@router.get("/stats", dependencies=[Depends(require_admin)])
async def stats(db: AsyncSession = Depends(get_db)):
    """The total and a count per source, for a quick look without the list."""
    total = (await db.execute(select(func.count()).select_from(WaitlistEntry))).scalar_one()
    by_source = (await db.execute(
        select(WaitlistEntry.heard_from, func.count())
        .group_by(WaitlistEntry.heard_from)
        .order_by(func.count().desc()))).all()
    return {"total": total, "heard_from": [{"key": k, "count": n} for k, n in by_source]}
