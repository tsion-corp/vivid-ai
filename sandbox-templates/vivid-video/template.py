"""Build (or rebuild) the `vivid-video` E2B template: where launch videos are
made (vivid-backend/app/builder/video.py).

    E2B_API_KEY=... python template.py

A throwaway sandbox per video: the project's files are copied in, an agent
writes a Hyperframes composition from them, and hyperframes renders it with
headless Chromium and ffmpeg. The image carries those, hyperframes itself,
and brag's music and sound effects (brag-assets/), pinned so every video is
made with the same tools. No dev server runs here.
"""
import os
import sys

from e2b import Template, default_build_logger

NAME = os.environ.get("E2B_VIDEO_TEMPLATE", "vivid-video")
APP = "/home/user/app"
#: Keep in step with vivid-backend/skills/video (see its README).
HYPERFRAMES_VERSION = "0.8.91"
BRAG_REPO = "https://github.com/latent-spaces/brag.git"
BRAG_COMMIT = "c893c5ed52aed84e3e2ee56787de869fccdae6b0"


def main() -> int:
    if not os.environ.get("E2B_API_KEY"):
        print("E2B_API_KEY is not set", file=sys.stderr)
        return 2
    template = (
        Template()
        .from_node_image("22")
        .run_cmd("apt-get update && apt-get install -y --no-install-recommends git bash "
                 "chromium ffmpeg fonts-liberation fonts-noto fonts-noto-color-emoji "
                 "fonts-noto-cjk python3 "
                 "&& rm -rf /var/lib/apt/lists/*", user="root")
        # hyperframes finds Chromium through these; the check/render gate
        # needs no download at run time.
        .set_envs({"PUPPETEER_EXECUTABLE_PATH": "/usr/bin/chromium",
                   "CHROME_PATH": "/usr/bin/chromium",
                   "PUPPETEER_SKIP_DOWNLOAD": "true"})
        .run_cmd(f"npm install -g hyperframes@{HYPERFRAMES_VERSION} && npm cache clean --force",
                 user="root")
        .run_cmd(f"mkdir -p {APP} && chown -R user:user /home/user", user="root")
        .set_workdir(APP)
        # brag's assets (music, sound effects, cue presets) at a pinned commit.
        .run_cmd(f"git clone -q {BRAG_REPO} /tmp/brag && git -C /tmp/brag checkout -q {BRAG_COMMIT} "
                 f"&& cp -R /tmp/brag/skills/brag/assets {APP}/brag-assets && rm -rf /tmp/brag",
                 user="user")
        # A first run caches whatever hyperframes fetches on first use.
        .run_cmd("npx hyperframes --version", user="user")
    )
    info = Template.build(template, name=NAME, cpu_count=4, memory_mb=4096,
                          on_build_logs=default_build_logger())
    print(f"built template {NAME}: {info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
