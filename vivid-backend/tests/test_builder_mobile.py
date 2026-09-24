"""Mobile projects (Expo, React Native): the target is chosen at creation
and reaches every place the web assumptions used to be hard-coded: the
sandbox template, the prompts and skills, the tools, uploads, hand edits and
the preview. Web projects behave exactly as before."""
from app.api.routes import builder as builder_routes
from app.builder import assets, planning, prompt, skills, targets, tools, visual
from app.db.models import BuilderAsset
from tests.builder_fakes import FakeSandbox
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401

MOBILE = targets.get(targets.MOBILE)
WEB = targets.get(targets.WEB)


def mobile_sandbox(files=None) -> FakeSandbox:
    sb = FakeSandbox(files or {"app/_layout.tsx": "x", "package.json": "{}"})
    sb.target = MOBILE
    return sb


# ---------------------------------------------------------------- targets
def test_web_is_the_default_and_keeps_its_old_values():
    assert targets.get(None) is WEB and targets.get("nonsense") is WEB
    assert FakeSandbox().target is WEB
    assert WEB.key_files == ("src/App.tsx", "src/main.tsx", "package.json")
    assert WEB.typecheck_cmd == "npx tsc --noEmit -p tsconfig.app.json"
    assert WEB.upload_dir == assets.UPLOAD_DIR and WEB.env_prefix == "VITE_"
    assert WEB.e2b_template == "vivid-web" and WEB.port == 5173


def test_mobile_target_is_expo():
    assert MOBILE.is_mobile and MOBILE.e2b_template == "vivid-expo" and MOBILE.port == 8081
    assert MOBILE.env("SUPABASE_URL") == "EXPO_PUBLIC_SUPABASE_URL"
    assert MOBILE.integrations == {"supabase", "vividpay"}


def test_env_names_follow_the_target():
    env = {"VITE_SUPABASE_URL": "u", "VITE_SUPABASE_ANON_KEY": "k", "OTHER": "x"}
    assert builder_routes._prefixed(env, WEB) is env
    assert builder_routes._prefixed(env, MOBILE) == {
        "EXPO_PUBLIC_SUPABASE_URL": "u", "EXPO_PUBLIC_SUPABASE_ANON_KEY": "k", "OTHER": "x"}


# ------------------------------------------------------------------ tools
async def test_mobile_commands_and_packages_are_checked():
    sb = mobile_sandbox()
    for cmd in ("npx expo start", "eas build -p android", "npm install lodash"):
        out = await tools.execute("run_command", {"command": cmd}, sb)
        assert out.text.startswith("error: that command is not allowed"), cmd
    out = await tools.execute("run_command",
                              {"command": "npx expo install react-native-vision-camera"}, sb)
    assert "Expo Go does not include" in out.text and not sb.commands
    out = await tools.execute("run_command",
                              {"command": "npx expo install expo-camera react-native-maps zod"}, sb)
    assert out.text.startswith("[exit code 0]")
    # The same commands are fine on the web.
    web = FakeSandbox({"src/App.tsx": "x"})
    out = await tools.execute("run_command", {"command": "npm install lodash"}, web)
    assert out.text.startswith("[exit code 0]")


async def test_typecheck_uses_the_targets_command():
    sb = mobile_sandbox()
    await tools.typecheck(sb)
    assert sb.commands[-1] == "npx tsc --noEmit"
    web = FakeSandbox({"src/App.tsx": "x"})
    await tools.typecheck(web)
    assert web.commands[-1] == "npx tsc --noEmit -p tsconfig.app.json"


def test_expo_go_problem_reads_scoped_and_versioned_names():
    assert tools.expo_go_problem("npx expo install @expo/vector-icons expo-image@~2") is None
    assert tools.expo_go_problem("npx expo install @react-native-async-storage/async-storage") is None
    assert "react-native-mmkv" in tools.expo_go_problem("npx expo install react-native-mmkv@3 && ls")
    assert tools.expo_go_problem("npm test") is None


# ------------------------------------------------- prompts, skills, plans
def test_prompt_and_skills_for_mobile():
    text = prompt.system_prompt("spec", "ctx", backend_env=True, mobile=True)
    assert "Expo" in text and "Vite" not in text
    assert "EXPO_PUBLIC_SUPABASE_URL" in text and "VITE_" not in text
    assert "Vite" in prompt.system_prompt("spec", "ctx")
    block = skills.ui_block("spec", mobile=True, backend=True, payments="paystack", chain=True)
    assert block.startswith("## Mobile app skill") and "## Design skill" not in block
    assert "Payments skill" not in block and "Web3" not in block
    assert "AsyncStorage" in block and "## Copy skill" in block
    # The kit, the recipe, and the data layer that fits the project.
    shop = skills.ui_block("spec", mobile=True, recipe="shop")
    assert "The component kit" in shop and "# Recipe: shop" in shop and "## The store" in shop
    assert "The auth context" in skills.ui_block("spec", mobile=True, backend=True)
    assert "# Recipe: shop" not in skills.ui_block("spec", mobile=True, recipe="landing")


def test_mobile_plans_have_screens_not_pages():
    schemas = planning.tool_schemas(mobile=True)
    props = schemas[1]["function"]["parameters"]["properties"]
    assert "onchain" not in props
    # Screen recipes, not the website's page recipes.
    assert props["recipe"]["enum"] == skills.recipe_names(mobile=True)
    assert "shop" in props["recipe"]["enum"] and "landing" not in props["recipe"]["enum"]
    assert "Screens" in schemas[1]["function"]["description"]
    spec = "\n".join(f"## {h}\nSomething concrete about {h.lower()} here."
                     for h in planning.MOBILE_SPEC_SECTIONS)
    assert planning.validate_spec(spec, planning.MOBILE_SPEC_SECTIONS)[1] is None
    assert "Pages" in planning.validate_spec(spec)[1]
    runner = planning.PlanRunner([], "a habit tracker", mobile=True)
    assert runner.mobile


# ------------------------------------------------------ uploads and edits
def test_uploads_live_under_assets_in_a_mobile_app():
    a = BuilderAsset(project_id="p", name="logo.png", mime="image/png", size_bytes=10,
                     r2_key="k")
    assert assets.sandbox_path(a, MOBILE) == "assets/uploads/logo.png"
    assert assets.public_path(a, MOBILE) == "assets/uploads/logo.png"
    assert assets.public_path(a) == "/uploads/logo.png"
    text = assets.describe([a], MOBILE)
    assert "require(" in text and "- assets/uploads/logo.png" in text


def test_metro_image_urls_resolve_to_project_files():
    files = ["assets/uploads/hero.png", "app/index.tsx"]
    for src in ("https://h/assets/?unstable_path=.%2Fassets%2Fuploads%2Fhero.png&platform=web",
                "https://h/assets/uploads/hero.png"):
        assert visual.resolve_src(src, "https://h", files, mobile=True).path == "assets/uploads/hero.png"
    remote = visual.resolve_src("https://cdn.x/y.jpg", "https://h", files, mobile=True)
    assert remote.path is None and remote.refs == ["https://cdn.x/y.jpg"]
    sources = {"app/index.tsx": '<Image source={{ uri: "https://cdn.x/y.jpg" }} />'}
    assert visual.relink_uri(sources, "https://cdn.x/y.jpg", "assets/images/y.jpg") == ["app/index.tsx"]
    assert sources["app/index.tsx"] == '<Image source={require("@/assets/images/y.jpg")} />'


async def test_editor_goes_into_the_expo_web_page_once():
    page = "<!DOCTYPE html>\n<html><body><div id=\"root\"></div></body></html>\n"
    sb = mobile_sandbox({visual.MOBILE_HTML: page})
    await visual.ensure_editor(sb)
    placed = sb.files[visual.MOBILE_HTML]
    assert placed.count(visual.EDITOR_START) == 1 and "index.html" not in sb.files
    await visual.ensure_editor(sb)
    assert sb.files[visual.MOBILE_HTML] == placed


async def test_mobile_copy_is_found_in_routes_and_components():
    sb = mobile_sandbox({"app/(tabs)/index.tsx": "<Text>Hi</Text>", "components/Card.tsx": "c",
                         "public/index.html": "<html>", "app.json": "{}", "src/x.tsx": "no"})
    sources = await visual.read_sources(sb, await sb.list_files())
    assert sorted(sources) == ["app/(tabs)/index.tsx", "components/Card.tsx"]


# ----------------------------------------------------------------- routes
def test_a_mobile_project_runs_in_the_expo_sandbox(client, fake_manager):
    r = client.post("/v1/builder/projects", json={"skip_plan": True, "target": "mobile"})
    assert r.status_code == 201 and r.json()["target"] == "mobile"
    pid = r.json()["id"]
    preview = client.get(f"/v1/builder/projects/{pid}/preview").json()
    assert preview["target"] == "mobile" and fake_manager.sandbox.target is MOBILE
    # The fake serves http, like a local sandbox a phone cannot reach.
    assert preview["device_url"] is None
    assert client.post("/v1/builder/projects", json={"target": "desktop"}).status_code == 422
    # The target is fixed for life: PATCH ignores it.
    client.patch(f"/v1/builder/projects/{pid}", json={"target": "web"})
    assert client.get(f"/v1/builder/projects/{pid}").json()["target"] == "mobile"


def test_web_only_integrations_are_refused_for_mobile(client):
    pid = client.post("/v1/builder/projects", json={"target": "mobile"}).json()["id"]
    for path in ("payments", "maps", "chain", "auth"):
        r = client.post(f"/v1/builder/projects/{pid}/{path}")
        assert r.status_code == 400 and r.json()["error"]["code"] == "not_supported", path


def test_device_url_is_exps_for_a_public_sandbox():
    sb = mobile_sandbox()
    sb.preview_url = lambda: "https://8081-abc.e2b.app"
    assert builder_routes._device_url(sb) == "exps://8081-abc.e2b.app"
    web = FakeSandbox()
    web.preview_url = lambda: "https://5173-abc.e2b.app"
    assert builder_routes._device_url(web) is None


def test_device_url_goes_through_the_http_relay_when_configured(monkeypatch):
    """React Native's packager check and live reload speak plain http, which
    E2B refuses; phones go through the relay on our own host instead."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "EXPO_DEVICE_RELAY_DOMAIN", "1-2-3-4.sslip.io")
    sb = mobile_sandbox()
    sb.driver, sb.id = "e2b", "iefv8pn8cautdl4zoxe3b"
    assert builder_routes._device_url(sb) == "exp://iefv8pn8cautdl4zoxe3b.1-2-3-4.sslip.io"
    # A local sandbox is not behind the relay.
    local = mobile_sandbox()
    local.preview_url = lambda: "http://127.0.0.1:8081"
    assert builder_routes._device_url(local) is None


async def test_writing_a_top_level_expo_notifications_import_warns():
    """expo-notifications throws while loading in Expo Go on Android; the
    model hears about it on the write, not from a crashed phone."""
    sb = mobile_sandbox()
    bad = 'import * as Notifications from "expo-notifications";\nexport const x = 1;\n'
    out = await tools.execute("write_file", {"path": "lib/notify.ts", "content": bad}, sb)
    assert "WARNING in lib/notify.ts" in out.text and "lib/notify.ts" in out.text
    good = ('import type * as N from "expo-notifications";\n'
            'export const load = () => require("expo-notifications");\n')
    out = await tools.execute("write_file", {"path": "lib/notify.ts", "content": good}, sb)
    assert "WARNING" not in out.text
    # Websites are not Expo Go.
    web = FakeSandbox({"src/App.tsx": "x"})
    out = await tools.execute("write_file", {"path": "src/n.ts", "content": bad}, web)
    assert "WARNING" not in out.text
