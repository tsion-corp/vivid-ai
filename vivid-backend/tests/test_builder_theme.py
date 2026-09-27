"""The theme by hand: the template's own index.css and index.html are read
and rewritten exactly; an app that keeps its look elsewhere is refused."""
from pathlib import Path

import pytest

from app.builder import theme
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401

TEMPLATE = Path(__file__).resolve().parents[2] / "sandbox-templates/vivid-web"
CSS = (TEMPLATE / "src/index.css").read_text()
HTML = "<!doctype html><html><head><title>x</title></head><body></body></html>"


def test_colours_round_trip():
    L, C, H = theme.hex_to_oklch("#1f6feb")
    assert theme.oklch_to_hex(L, C, H) == "#1f6feb"
    assert theme.foreground_for("oklch(0.3 0.1 260)") == "oklch(0.985 0 0)"
    assert theme.foreground_for("oklch(0.9 0.1 90)") == "oklch(0.205 0 0)"
    with pytest.raises(theme.ThemeError):
        theme.hex_to_oklch("blue")


def test_read_and_write_the_template():
    assert theme.read(CSS, HTML) | {"primary": None} == {
        "supported": True, "primary": None, "radius": 0.625, "font_heading": None, "font_body": None,
        "fonts_link": False}
    css, html = theme.write(CSS, HTML, {"palette": "forest", "radius": 1, "fonts": "editorial"})
    root = theme._block(css, ":root").group("body")
    dark = theme._block(css, ".dark").group("body")
    assert "--primary: oklch(0.42 0.12 150);" in root and "--primary-foreground: oklch(0.985 0 0);" in root
    assert "--primary: oklch(0.72 0.14 150);" in dark and "--radius: 1rem;" in root
    assert css.count("--primary:") == 2 and "--background: oklch(1 0 0);" in css            # the rest untouched
    got = theme.read(css, html)
    assert got["font_heading"] == "Fraunces" and got["font_body"] == "Inter" and got["radius"] == 1
    assert "family=Fraunces:wght@400;500;600;700&family=Inter" in html and html.index("fonts.googleapis") < html.index("</head>")
    again, html2 = theme.write(css, html, {"fonts": "modern"})
    assert html2.count("fonts.googleapis.com/css2") == 1 and "Inter+Tight" in html2
    hexed, _ = theme.write(CSS, HTML, {"primary": "#e11d48"})
    assert theme.read(hexed, HTML)["primary"] == "#e11d48"
    with pytest.raises(theme.ThemeError):
        theme.write("body { color: red }", HTML, {"palette": "forest"})
    with pytest.raises(theme.ThemeError):
        theme.write(CSS, HTML, {"palette": "nope"})


def test_theme_routes(client, fake_manager, fake_blob):  # noqa: F811
    sb = fake_manager.sandbox
    sb.files["src/index.css"] = CSS
    sb.files["index.html"] = HTML
    pid = client.post("/v1/builder/projects", json={"name": "Titi", "skip_plan": True}).json()["id"]
    got = client.get(f"/v1/builder/projects/{pid}/theme").json()
    assert got["supported"] and "forest" in got["palettes"] and got["fonts"]["editorial"] == ["Fraunces", "Inter"]
    assert client.put(f"/v1/builder/projects/{pid}/theme", json={"palette": "ocean"}).status_code == 409  # not built
    assert client.post(f"/v1/builder/projects/{pid}/snapshots").status_code == 200
    r = client.put(f"/v1/builder/projects/{pid}/theme", json={"palette": "ocean"})
    assert r.status_code == 200 and r.json()["snapshot"]["summary"] == "Changed the theme"
    assert "oklch(0.55 0.13 220)" in sb.files["src/index.css"]
    assert client.put(f"/v1/builder/projects/{pid}/theme", json={"primary": "red"}).status_code == 422
    sb.files["src/index.css"] = "body{}"
    r = client.put(f"/v1/builder/projects/{pid}/theme", json={"palette": "ocean"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_supported"
