"""Operator views, gated by ADMIN_TOKEN (there are no admin users yet).

    GET /v1/admin/economics?days=30   cost per 1M tokens and plan margins
"""
import hmac

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.errors import APIError
from app.services import economics

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(request: Request) -> None:
    token = settings.ADMIN_TOKEN
    if not token:
        raise APIError(503, "not_configured", "Admin views are not set up on this server.")
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(presented, token):
        raise APIError(401, "unauthorized", "Admin token required")


@router.get("/economics", dependencies=[Depends(require_admin)])
async def get_economics(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db)):
    return await economics.report(db, days)
