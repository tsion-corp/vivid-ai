"""Outgoing email: sent over SMTP when configured, never raised, and a
bad recipient or a server failure is reported as False."""
import smtplib

from app.core.config import settings
from app.services import mail


class FakeSMTP:
    sent: list = []
    fail = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise smtplib.SMTPServerDisconnected("gone")
        FakeSMTP.sent.append(msg)


async def test_send(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail = [], False
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert await mail.send("a@b.co", "Hi", "text") is False                  # not configured

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_USER", "u")
    assert await mail.send("a@b.co", "New\nmessage", "Body", mail.layout("Hi", "<p>x</p>", ("Open", "https://x.y")),
                           reply_to="visitor@site.com") is True
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "a@b.co" and msg["Reply-To"] == "visitor@site.com"
    assert "\n" not in msg["Subject"] and msg.is_multipart()

    assert await mail.send("not-an-address", "Hi", "x") is False
    assert await mail.send("a@b.co\nBcc: x@y.z", "Hi", "x") is False
    FakeSMTP.fail = True
    assert await mail.send("a@b.co", "Hi", "x") is False                     # logged, not raised


def test_valid_address():
    assert mail.valid_address("Ada <ada@example.com>")
    assert not mail.valid_address("ada@localhost") and not mail.valid_address("")
