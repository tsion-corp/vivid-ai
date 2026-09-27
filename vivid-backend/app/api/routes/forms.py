"""Forms on the sites Vivid builds (contact, booking, quote, newsletter).

The app posts what someone filled in to /v1/forms/<project id>
(VITE_VIVID_FORMS_URL in its .env); it is kept for the owner and emailed to
them. No key: like the pageview beacon, the check is the origin (the
published site, or the builder's preview, which is marked as a test), a
honeypot field, and rate limits per address and per day.
"""
import html
import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.routes.pay import mode_for
from app.core.config import settings
from app.db.models import BuilderFormSubmission, BuilderProject, User
from app.services import mail, rate_limit

log = logging.getLogger("vivid.forms")

router = APIRouter(prefix="/forms", tags=["builder-forms"])

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "content-type"}
MAX_BYTES = 10_000
MAX_FIELDS = 30
HONEYPOT = "_gotcha"


def _answer(status: int, body: dict | None = None) -> Response:
    return Response(json.dumps(body or {"ok": status < 400}), status_code=status,
                    media_type="application/json", headers=CORS)


def _fields(raw: bytes, content_type: str) -> dict | None:
    try:
        if "json" in content_type or raw.lstrip().startswith(b"{"):
            data = json.loads(raw or b"{}")
        else:
            data = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(raw.decode("utf-8")).items()}
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    out = {}
    for k, v in list(data.items())[:MAX_FIELDS]:
        if isinstance(v, (dict, list)):
            v = json.dumps(v)[:2000]
        out[str(k)[:64]] = "" if v is None else str(v)[:5000]
    return out


def _ip(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else ""))


@router.options("/{project_id}")
async def preflight(project_id: str):
    return Response(status_code=204, headers=CORS)


@router.post("/{project_id}")
async def submit(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """{form?: "contact", ...fields}. Answers {ok: true} (also to a bot that
    filled the honeypot, which is dropped), 403 from another site, 429 over
    the limits."""
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        return _answer(413, {"error": {"code": "too_large", "message": "That is too much to send."}})
    project = await db.get(BuilderProject, project_id)
    if project is None or not project.forms_enabled:
        return _answer(404, {"error": {"code": "not_found", "message": "This form is not accepting messages."}})
    mode = mode_for(request.headers.get("origin"), project)
    if mode is None:
        return _answer(403, {"error": {"code": "wrong_origin", "message": "Send this from the site itself."}})
    redis = request.app.state.redis
    if not await rate_limit.check_bucket(redis, f"forms:{project_id}:{_ip(request)}", settings.BUILDER_FORMS_PER_MINUTE):
        return _answer(429, {"error": {"code": "rate_limited", "message": "Please wait a minute and try again."}})
    fields = _fields(raw, request.headers.get("content-type", ""))
    if fields is None:
        return _answer(400, {"error": {"code": "bad_request", "message": "The form could not be read."}})
    if fields.pop(HONEYPOT, ""):
        return _answer(200)                                   # a bot: look accepted, keep nothing
    form = (fields.pop("form", "") or "contact")[:64]
    if not any(v.strip() for v in fields.values()):
        return _answer(400, {"error": {"code": "empty", "message": "Fill in the form first."}})
    since = datetime.now(timezone.utc) - timedelta(days=1)
    today = (await db.execute(select(func.count()).select_from(BuilderFormSubmission).where(
        BuilderFormSubmission.project_id == project_id, BuilderFormSubmission.created_at >= since))).scalar_one()
    if today >= settings.BUILDER_FORMS_PER_DAY:
        return _answer(429, {"error": {"code": "rate_limited", "message": "This site has had a lot of messages today. Try tomorrow."}})

    row = BuilderFormSubmission(project_id=project_id, form=form, fields=fields, test=mode == "test")
    db.add(row)
    await db.flush()
    owner = await db.get(User, project.owner_id)
    to = project.forms_email or (owner.profile_email if owner else None)
    if to:
        row.emailed = await mail.send(to, *_email(project.name, form, fields, row.test),
                                      reply_to=fields.get("email") if mail.valid_address(fields.get("email")) else None)
    await db.commit()
    return _answer(200)


def _email(site: str, form: str, fields: dict, test: bool) -> tuple[str, str, str]:
    label = form.replace("_", " ").replace("-", " ").strip() or "message"
    subject = f"{'[Test] ' if test else ''}New {label} from {site}"
    lines = [f"{k}: {v}" for k, v in fields.items()]
    text = (f"Someone sent the {label} form on {site}:\n\n" + "\n".join(lines)
            + ("\n\n(Sent from the preview, as a test.)" if test else "")
            + "\n\nReply to this email to answer them, when they gave an email address.")
    rows = "".join(f"<tr><td style=\"padding:6px 12px 6px 0;color:#6b6880;vertical-align:top\">{html.escape(k)}</td>"
                   f"<td style=\"padding:6px 0;white-space:pre-wrap\">{html.escape(v)}</td></tr>" for k, v in fields.items())
    page = mail.layout(f"New {label} from {site}",
                       f"<table style=\"border-collapse:collapse;font-size:14px\">{rows}</table>"
                       + ("<p style=\"color:#6b6880;font-size:13px\">Sent from the preview, as a test.</p>" if test else ""))
    return subject, text, page
