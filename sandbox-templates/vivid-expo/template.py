"""Build (or rebuild) the `vivid-expo` E2B template, for mobile projects.

    E2B_API_KEY=... python template.py

An Expo (React Native) app with Expo Router, NativeWind and react-native-web.
The build runs setup.sh (dependencies at the SDK's versions) and makes the
first git commit, so a sandbox boots straight into Metro; the template is
ready when :8081 answers. Metro serves the web preview and Expo Go.

Rebuild after changing package.json, setup.sh or any template file; running
sandboxes keep the old image, new ones get the new one.
"""
import os
import sys
from pathlib import Path

from e2b import Template, default_build_logger, wait_for_port

HERE = Path(__file__).resolve().parent
NAME = os.environ.get("E2B_TEMPLATE", "vivid-expo")
APP = "/home/user/app"

#: Copied into the image. node_modules is installed there, never uploaded.
FILES = ["package.json", "app.json", "eas.json", "babel.config.js", "metro.config.js",
         "tailwind.config.js", "global.css", "nativewind-env.d.ts", "tsconfig.json",
         ".gitignore", "start.sh", "setup.sh"]
DIRS = ["app", "lib", "components", "constants", "assets", "public", "scripts"]


def main() -> int:
    if not os.environ.get("E2B_API_KEY"):
        print("E2B_API_KEY is not set", file=sys.stderr)
        return 2
    os.chdir(HERE)
    template = (
        Template()
        .from_node_image("22")
        # git for snapshots and file listing; chromium so the builder can
        # screenshot the web preview for the design critique.
        .run_cmd("apt-get update && apt-get install -y --no-install-recommends git bash "
                 "chromium fonts-liberation fonts-noto-color-emoji "
                 "&& rm -rf /var/lib/apt/lists/*", user="root")
        # eas-cli for the builds the user starts from Vivid (never the model).
        .run_cmd("npm install -g eas-cli --no-audit --no-fund", user="root")
        .run_cmd(f"mkdir -p {APP} && chown -R user:user /home/user", user="root")
        .set_workdir(APP)
        .copy(FILES, f"{APP}/", user="user")
    )
    for d in DIRS:
        template = template.copy(d, f"{APP}/{d}", user="user")
    template = (
        template
        .run_cmd("bash setup.sh", user="user")
        .run_cmd("git init -q -b main && git config user.name Vivid "
                 "&& git config user.email builder@vivid "
                 "&& git add -A && git commit -q -m template", user="user")
        .set_start_cmd(f"bash {APP}/start.sh", wait_for_port(8081))
    )
    info = Template.build(template, name=NAME, cpu_count=2, memory_mb=4096,
                          on_build_logs=default_build_logger())
    print(f"built template {NAME}: {info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
