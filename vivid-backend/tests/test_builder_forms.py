"""Forms on built sites: accepted from the site itself (the preview marks a
test), dropped for bots, limited, stored, emailed to the owner, listed and
exported for them."""
from app.api.routes.forms import router as forms_router
from app.builder import skills
from app.core.config import settings
from app.services import mail
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401

PREVIEW = "https://5173-abc.e2b.app"


def test_forms(client, fake_manager, fake_blob, monkeypatch):  # noqa: F811
    client.app.include_router(forms_router, prefix="/v1")
    sent = []

    async def send(to, subject, text, html=None, reply_to=None):
        sent.append({"to": to, "subject": subject, "text": text, "reply_to": reply_to})
        return True
    monkeypatch.setattr(mail, "send", send)
    monkeypatch.setattr(mail, "configured", lambda: True)
    pid = client.post("/v1/builder/projects", json={"name": "Titi", "skip_plan": True}).json()["id"]
    url = f"/v1/forms/{pid}"

    assert client.post(url, json={"name": "Ada"}, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post(url, json={"name": "Ada"}).status_code == 403                       # no origin
    ok = client.post(url, json={"form": "booking", "name": "Ada", "email": "ada@example.com", "guests": 4},
                     headers={"origin": PREVIEW})
    assert ok.status_code == 200 and ok.json() == {"ok": True} and ok.headers["access-control-allow-origin"] == "*"
    # No owner email on file and none set: stored, not emailed.
    assert sent == []

    client.put(f"/v1/builder/projects/{pid}/forms", json={"enabled": True, "email": "owner@titi.ng"})
    r = client.post(url, content="name=Bo&message=Hello%20there&email=bo%40x.co",
                    headers={"origin": PREVIEW, "content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200
    assert sent[-1]["to"] == "owner@titi.ng" and sent[-1]["subject"] == "[Test] New contact from Titi"
    assert "message: Hello there" in sent[-1]["text"] and sent[-1]["reply_to"] == "bo@x.co"

    # A bot fills the honeypot: looks accepted, nothing kept or sent.
    assert client.post(url, json={"name": "x", "_gotcha": "spam"}, headers={"origin": PREVIEW}).status_code == 200
    assert client.post(url, json={"name": " "}, headers={"origin": PREVIEW}).status_code == 400   # empty
    assert client.post(url, content=b"x" * 10_001, headers={"origin": PREVIEW}).status_code == 413
    assert len(sent) == 1

    rows = client.get(f"/v1/builder/projects/{pid}/forms/submissions").json()
    assert [(r["form"], r["test"]) for r in rows] == [("contact", True), ("booking", True)]
    assert rows[1]["fields"] == {"name": "Ada", "email": "ada@example.com", "guests": "4"}
    csv = client.get(f"/v1/builder/projects/{pid}/forms/submissions.csv")
    assert csv.headers["content-type"].startswith("text/csv") and "sent_at,form,test,name" in csv.text

    # Per-address rate limit, then switched off entirely.
    monkeypatch.setattr(settings, "BUILDER_FORMS_PER_MINUTE", 0)
    assert client.post(url, json={"name": "Cy"}, headers={"origin": PREVIEW}).status_code == 429
    monkeypatch.setattr(settings, "BUILDER_FORMS_PER_MINUTE", 5)
    settings_now = client.put(f"/v1/builder/projects/{pid}/forms", json={"enabled": False}).json()
    assert settings_now["enabled"] is False and settings_now["email_ready"] is True
    assert client.post(url, json={"name": "Cy"}, headers={"origin": PREVIEW}).status_code == 404
    assert client.put(f"/v1/builder/projects/{pid}/forms", json={"email": "nope"}).status_code == 400
    client.as_user("u2")
    assert client.get(f"/v1/builder/projects/{pid}/forms/submissions").status_code == 404


def test_forms_skill_is_offered_when_it_fits():
    assert "Forms skill" in skills.forms_block(None, "add a contact form", backend=False)
    assert "Forms skill" in skills.forms_block("# Spec\\nA bakery with a booking page", "", backend=False)
    assert skills.forms_block("# Spec\\nA calculator", "make it blue", backend=False) == ""
    assert skills.forms_block(None, "add dark mode", backend=True) == ""
