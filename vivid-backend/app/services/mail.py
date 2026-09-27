"""Outgoing email over SMTP: invites, gifts, and form submissions from the
sites people build.

Best effort by design: a failed send is logged and reported as False, never
raised, so an invite or a form submission is never lost to a mail outage.
Credentials never reach a log line.
"""
import asyncio
import html as html_mod
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

from app.core.config import settings

log = logging.getLogger("vivid.mail")


def configured() -> bool:
    return bool(settings.SMTP_HOST)


def valid_address(value: str | None) -> bool:
    _, addr = parseaddr(value or "")
    return bool(addr) and "@" in addr and "." in addr.rsplit("@", 1)[-1] and len(addr) <= 320 \
        and "\n" not in addr and "\r" not in addr


def layout(heading: str, body_html: str, button: tuple[str, str] | None = None) -> str:
    """The one HTML shape every Vivid email has: a heading, a body, and
    maybe a button (label, url)."""
    cta = ""
    if button:
        label, url = button
        cta = (f'<p style="margin:28px 0 8px"><a href="{html_mod.escape(url, quote=True)}" '
               'style="background:#6d4aff;color:#fff;text-decoration:none;padding:12px 20px;'
               f'border-radius:10px;font-weight:600;display:inline-block">{html_mod.escape(label)}</a></p>')
    return ('<!doctype html><html><body style="margin:0;background:#f6f5fb;padding:32px 16px;'
            'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1d1b26">'
            '<div style="max-width:520px;margin:0 auto;background:#fff;border-radius:16px;padding:32px">'
            '<p style="margin:0 0 20px;font-weight:800;font-size:18px;color:#6d4aff">Vivid</p>'
            f'<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3">{html_mod.escape(heading)}</h1>'
            f'<div style="font-size:15px;line-height:1.6">{body_html}</div>{cta}'
            '</div></body></html>')


def _message(to: str, subject: str, text: str, html: str | None, reply_to: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject.replace("\n", " ").replace("\r", " ")[:200]
    msg["Message-ID"] = make_msgid(domain=parseaddr(settings.SMTP_FROM)[1].rsplit("@", 1)[-1] or None)
    if reply_to and valid_address(reply_to):
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _deliver(msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    if settings.SMTP_STARTTLS:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT) as smtp:
            smtp.starttls(context=context)
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context,
                              timeout=settings.SMTP_TIMEOUT) as smtp:
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)


async def send(to: str, subject: str, text: str, html: str | None = None,
               reply_to: str | None = None) -> bool:
    """Send one email. True when the SMTP server accepted it."""
    if not configured():
        log.info("mail not configured; not sending %r", subject)
        return False
    if not valid_address(to):
        log.warning("not sending %r: bad recipient", subject)
        return False
    try:
        await asyncio.to_thread(_deliver, _message(to, subject, text, html, reply_to))
        return True
    except (smtplib.SMTPException, OSError) as e:
        # The exception text can quote the server's reply, never our password.
        log.error("sending %r failed: %s", subject, type(e).__name__)
        return False


def send_later(to: str, subject: str, text: str, html: str | None = None,
               reply_to: str | None = None) -> None:
    """Fire and forget, for a request that should not wait on SMTP."""
    task = asyncio.get_running_loop().create_task(send(to, subject, text, html, reply_to))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


_pending: set[asyncio.Task] = set()

