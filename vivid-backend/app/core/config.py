from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Where chat completions may be sent. "runpod" is our own vLLM pods;
#: "openrouter" is the hosted fallback for the hours a GPU is down.
LLM_PROVIDERS = ("runpod", "openrouter")


class Settings(BaseSettings):
    APP_NAME: str = "Vivid AI"
    APP_VERSION: str = "0.1.0"
    ENV: str = "development"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000",
                               "http://localhost:3001"]

    # Infra
    DATABASE_URL: str = "postgresql+asyncpg://vivid:vivid@localhost:5432/vivid"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth
    JWT_SECRET: str = "change-me-in-prod"
    # Identity is Decane's job: Google and emailed codes, no passwords. The
    # email+password endpoints remain only so automated tests can mint a
    # session without a real inbox. Never enable this in production.
    ALLOW_PASSWORD_AUTH: bool = False
    # Decane Connect (handles "Continue with Google" — no Google Cloud
    # registration needed). App/project id from the Decane dashboard; empty
    # disables the social login endpoint.
    DECANE_APP_ID: str = ""
    # Optional ES256 public key (SPKI PEM) from the dashboard for offline
    # verification; empty = fetch Decane's JWKS instead.
    DECANE_VERIFICATION_KEY: str = ""
    DECANE_API_BASE: str = "https://backend.decane.app"
    # Decane sign-in for the apps the builder makes: the organization token
    # (dck_org_...) that provisions one Decane client per project. Not the
    # values above, which are Vivid's own sign-in. Server-only; empty turns
    # the feature off.
    DECANE_PARTNER_TOKEN: str = ""
    DECANE_CONNECT_BASE: str = "https://backend.decane.app"
    DECANE_CONNECT_TIMEOUT: float = 10.0
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Object storage (S3-compatible; MinIO in dev)
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    # Endpoint baked into presigned URLs the browser fetches. Inside docker the
    # backend reaches MinIO as http://minio:9000, which the browser cannot
    # resolve — so URLs are signed against this address instead when set.
    S3_PUBLIC_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "vivid"
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
    # Which storage backend serves attachments: "s3" (MinIO, or real S3) or
    # "cloudinary". Cloudinary puts a CDN in front, which is the reason to
    # move: MinIO answers every image from the one VPS with nothing cached in
    # front of it. Switching does NOT move existing objects.
    STORAGE_DRIVER: str = "s3"
    # Was hardcoded. Real S3 and DO Spaces need their actual region; MinIO and
    # R2 ignore it, so the old constant worked by luck rather than design.
    S3_REGION: str = "us-east-1"

    # --- Cloudinary (STORAGE_DRIVER=cloudinary) --------------------------
    # Secrets, so they belong in app.env and never in git.
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    # Keeps Vivid's objects out of anything else the account holds.
    CLOUDINARY_FOLDER: str = "vivid"
    # Where the browser fetches from. Empty means res.cloudinary.com direct;
    # set it to a CDN host pointed at res.cloudinary.com as origin, and only
    # this line changes if the CDN does. Include the cloud name, exclude the
    # resource type — the driver appends /image/upload/... itself:
    #   direct:  https://res.cloudinary.com/<cloud-name>
    #   Fastly:  https://cdn.example.com/<cloud-name>
    CLOUDINARY_MEDIA_BASE_URL: str = ""
    CLOUDINARY_TIMEOUT: int = 60

    # --- Model provider switch ------------------------------------------
    # The one knob to flip when the GPUs are down. "runpod" (default) sends
    # every model call to our own pods below; "openrouter" sends the chat
    # assistant, the coding agent, speech-to-text and text-to-speech to
    # OpenRouter instead. Everything above services/models_gateway/provider.py
    # — the chat pipeline, history and token budgets, the /v1 proxy and its
    # `vivid-*` aliases, the frontend — is the same either way, so failing
    # over is an env change and a restart, not a client release.
    # Not moved: translation (MADLAD, on the ASR pod; yo/ig replies fall back
    # to English when it is down, as they already do), embeddings, reranker.
    MODEL_PROVIDER: str = "runpod"
    # Per-service overrides for a partial outage: one pod can fail over while
    # the rest stay home. Empty = follow MODEL_PROVIDER.
    LLM_PROVIDER: str = ""       # the chat assistant
    CODE_LLM_PROVIDER: str = ""  # the coding agent
    ASR_PROVIDER: str = ""       # speech-to-text
    TTS_PROVIDER: str = ""       # text-to-speech
    OPENROUTER_API_KEY: str = ""  # required whenever a provider above says openrouter
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # OpenRouter's ids for the same LLMs the pods serve, so a bare flip keeps
    # the product's behaviour. Empty code model falls back to the chat one,
    # mirroring CODE_LLM_BASE_URL -> LLM_BASE_URL below.
    OPENROUTER_CHAT_MODEL: str = "google/gemma-3-27b-it"
    OPENROUTER_CODE_MODEL: str = "mistralai/devstral-2512"
    # The windows those models serve there. The backend clamps history to the
    # live window and advertises it on /v1/models, so these must be real.
    OPENROUTER_CHAT_CONTEXT_TOKENS: int = 131_072
    OPENROUTER_CODE_CONTEXT_TOKENS: int = 262_144
    # How OpenRouter picks among the hosts serving a model. Its default
    # (price-weighted) landed the chat model on a host with 1-4s to first
    # token; "latency" measured 0.7-1.3s on the same afternoon. A voice
    # assistant wants the fast one. Empty = OpenRouter's default routing.
    OPENROUTER_PROVIDER_SORT: str = "latency"  # "latency" | "throughput" | "price" | ""
    # Voice on OpenRouter: /audio/transcriptions and /audio/speech. Neither
    # has a Nigerian voice; this is degraded service, not parity. Pick from
    # /models?output_modalities=transcription and =speech.
    OPENROUTER_STT_MODEL: str = "openai/whisper-large-v3"
    # Language codes forwarded to the transcriber as a hint. Anything else
    # (Igbo and Pidgin, which Whisper does not know) is left to auto-detect —
    # sending an unknown code is a 400, not a shrug.
    OPENROUTER_STT_LANGUAGES: list[str] = ["en", "yo", "ha", "fr"]
    OPENROUTER_TTS_MODEL: str = "hexgrad/kokoro-82m"
    OPENROUTER_TTS_VOICE: str = "af_heart"
    # OpenRouter returns raw 16-bit mono PCM; the clients play WAV, so the
    # backend adds the header and needs the rate. 24 kHz is what kokoro, the
    # OpenAI voices and MAI-Voice produce; change it with the model.
    OPENROUTER_TTS_SAMPLE_RATE: int = 24_000
    # OpenRouter refuses audio (transcription) requests unless the account
    # holds at least this much credit, whatever the request would cost. It is
    # their rule, not ours; /health/models reports `audio_ready` against it so
    # an empty balance shows up before the first voice turn fails.
    OPENROUTER_AUDIO_MIN_BALANCE: float = 0.50
    # --- Image and video generation --------------------------------------
    # The pods serve no image or video model, so these go to OpenRouter
    # whatever MODEL_PROVIDER says, and the generate_image / generate_video
    # tools exist only while OPENROUTER_API_KEY is set. Nothing there makes
    # pictures for free: flux.2 klein is about $0.003 an image at 1K; video
    # is priced per clip and the cost is only known when the clip is done.
    # Pick from /models?output_modalities=image and =video.
    OPENROUTER_IMAGE_MODEL: str = "black-forest-labs/flux.2-klein-4b"
    # EMPTY by default and only sent when set. Most image models — the
    # default flux.2-klein-4b included — do not accept a `resolution`
    # parameter at all, and OpenRouter 400s the whole request for an
    # unsupported field. Check /api/v1/images/models for a model's
    # supported_parameters before setting this.
    OPENROUTER_IMAGE_RESOLUTION: str = ""  # e.g. 512 | 1K | 2K | 4K, model permitting
    OPENROUTER_IMAGE_TIMEOUT: int = 120
    OPENROUTER_VIDEO_MODEL: str = "google/veo-3.1-fast"
    # Clip length ceiling; the model can ask for less. Longer clips cost more
    # and render longer, and a chat turn is waiting.
    # Video models take DISCRETE durations, not a range: veo-3.1-fast accepts
    # 4, 6 or 8 and rejects anything else. The old default of 5 was therefore
    # never valid and 400d every call. Requests are snapped to the nearest
    # allowed value at or below the ceiling.
    OPENROUTER_VIDEO_DURATIONS: list[int] = [4, 6, 8]
    OPENROUTER_VIDEO_MAX_SECONDS: int = 8
    # A clip renders asynchronously for minutes. The turn polls this often and
    # gives up after this long, so a stuck job cannot hold a user's only
    # generation slot forever.
    OPENROUTER_VIDEO_POLL_SECONDS: int = 5
    OPENROUTER_VIDEO_TIMEOUT: int = 300
    # Attribution headers OpenRouter shows on its rankings. Optional.
    OPENROUTER_SITE_URL: str = ""
    OPENROUTER_APP_NAME: str = "Vivid AI"

    # Model services on RunPod. Nothing else in the codebase may know these.
    LLM_BASE_URL: str = ""    # OpenAI-compatible root incl. /v1, e.g. https://<pod>-8000.proxy.runpod.net/v1
    LLM_MODEL: str = "RedHatAI/gemma-3-27b-it-quantized.w4a16"
    ASR_BASE_URL: str = ""        # STT server: /transcribe /health
    TTS_BASE_URL: str = ""        # TTS server: /speak /health (falls back to ASR_BASE_URL)
    TRANSLATE_BASE_URL: str = ""  # MADLAD server: /translate (falls back to ASR_BASE_URL)
    EMBEDDINGS_URL: str = ""  # optional; empty disables vector search (full-text still works)
    EMBEDDING_DIM: int = 768

    # --- Coding model (Devstral on RunPod) -------------------------------
    # Serves the /ws/code agent, which is a different animal from the chat
    # assistant: native tool calling, long loops, 100k context. Kept on its own
    # endpoint so the two never contend for the same GPU. Empty falls back to
    # LLM_BASE_URL, which will work but will be slow and share capacity.
    # vLLM MUST be started with --enable-auto-tool-choice --tool-call-parser
    # mistral; /v1/health/code reports it when it was not.
    CODE_LLM_BASE_URL: str = ""
    CODE_LLM_MODEL: str = "cyankiwi/Devstral-Small-2-24B-Instruct-2512-AWQ-4bit"
    CODE_LLM_TEMPERATURE: float = 0.15  # agentic edits want determinism, not variety
    CODE_LLM_TOP_P: float = 0.95
    CODE_LLM_TIMEOUT: int = 180
    CODE_MAX_REPLY_TOKENS: int = 4096
    # Served max_model_len is 100k; the loop budgets below it so a long tool
    # result cannot push a request over the served limit mid-session.
    CODE_CONTEXT_TOKENS: int = 90000
    # The served window itself, as advertised to clients through /v1/models.
    # Distinct from CODE_CONTEXT_TOKENS above: that is the loop's self-imposed
    # budget, this is what the pod will actually accept, and a client sizing
    # its own context needs the real number.
    CODE_LLM_CONTEXT_TOKENS: int = 100_000
    # Tool calls per user turn. Real refactors run 20-40; the cap is a runaway
    # guard, and hitting it ends the turn cleanly rather than erroring.
    CODE_MAX_STEPS: int = 50
    # Whole-turn restarts when the stream breaks mid-flight. The RunPod proxy
    # drops long streams; without this a twelve-step session dies at step
    # twelve. Safe because a half-streamed turn leaves the conversation
    # untouched (see code_agent._turn).
    CODE_STREAM_RETRIES: int = 3
    # One tool result's ceiling. A 4000-line file read whole would otherwise
    # evict everything the model has learned so far.
    CODE_MAX_TOOL_RESULT_CHARS: int = 60000

    # Tool loop (runs in the backend, never on the pod)
    TOOLS_ENABLED: bool = True
    TAVILY_API_KEY: str = ""  # empty disables web_search/news; other tools still work
    # Web search quality (services/search.py). Tavily credits per web_search
    # call = SEARCH_QUERY_VARIANTS x (2 if advanced else 1); news always runs
    # basic. Dial these down first if the Tavily budget bites.
    TAVILY_SEARCH_DEPTH: str = "advanced"  # "basic" (1 credit) | "advanced" (2, better extraction)
    SEARCH_QUERY_VARIANTS: int = 3  # rewritten queries searched in parallel; 1 = single rewrite
    SEARCH_TOP_K: int = 3  # snippets handed to the model after reranking
    # Cross-encoder reranker (BGE-reranker-v2-m3 behind TEI: {url}/rerank).
    # Empty keeps Tavily's ordering. Shared with RAG once that exists.
    RERANKER_URL: str = ""
    # Code-execution sandbox (its own locked-down container — model-generated
    # code must NEVER run in this process; empty disables the run_code tool)
    SANDBOX_URL: str = ""
    SANDBOX_RUN_TIMEOUT: int = 12  # seconds per program
    # vivid-tools browser service (Playwright); empty disables browse_page
    VIVID_TOOLS_URL: str = ""
    VIVID_TOOLS_TOKEN: str = ""
    # --- partner browsing API (/v1/browser) ---
    # Concurrent browser sessions one API key may hold. The tier's own ceiling
    # is BROWSER_max_sessions in vivid-tools; this stops a single partner
    # taking all of it. Overridable per key on the api_keys row.
    BROWSER_SESSIONS_PER_KEY: int = 3
    # Seconds a session may sit idle before it is reaped. Longer than
    # vivid-tools' own default because an authenticated session is expensive
    # to rebuild — losing one means redoing a login.
    BROWSER_SESSION_TTL: int = 900
    BROWSER_SESSION_TTL_MAX: int = 3600
    # Steps a managed browsing task may take. The chat tool keeps its own,
    # tighter budget (a chat turn cannot wait for 20 page loads).
    BROWSER_TASK_MAX_STEPS: int = 30
    BROWSER_TASK_DEFAULT_STEPS: int = 8
    # WORKAROUND, not a design rule: tools are skipped for these languages
    # while MADLAD translation is unreliable — the answer falls back to
    # English anyway, so the planner call buys nothing visible.
    # TODO: empty this once translation is fixed. A tool-free answer to a
    # factual question is a HALLUCINATED answer.
    NO_TOOLS_LANGS: list[str] = ["yo", "ig"]

    # Interim, deliberately: speech normalization (clean_for_tts) runs in the
    # backend before calling TTS. Its better home is the TTS server itself —
    # the last stop before audio, so every caller benefits and the wav cache
    # keys on normalized text. Flip to False once the pod TTS applies it
    # server-side (patch: docs/tts-server-normalization.md).
    TTS_CLEAN_IN_BACKEND: bool = True

    # Generation
    LLM_CONTEXT_TOKENS: int = 8192  # served model's max_model_len
    HISTORY_TOKEN_BUDGET: int = 5500  # upper bound; the context clamp may lower it
    MAX_REPLY_TOKENS: int = 4096
    MAX_CONTINUATIONS: int = 2  # extra rounds when a reply hits the token cap
    LLM_TEMPERATURE: float = 1.0
    LLM_TOP_P: float = 0.95
    # Languages whose voice replies stream clause-by-clause into TTS (Piper is
    # ~0.2s/clip; WazobiaVoice is ~6s/clip regardless of length, and yo/ig
    # must translate the full text first — those get one clip at the end).
    TTS_STREAM_LANGS: list[str] = ["en"]

    # --- /v1 model proxy (Vivid Code, the VS Code extension, the editor) ---
    # Developer tools speak OpenAI over /v1/chat/completions. They point here
    # rather than at a pod so every call carries a Vivid identity. Turning this
    # off leaves those clients with nowhere to go — it is not a safe default.
    MODEL_PROXY_ENABLED: bool = True
    # Ceiling on max_tokens for one proxied reply. A tool-calling agent asks
    # for a lot; this stops a single client reserving the whole KV cache.
    MODEL_PROXY_MAX_TOKENS: int = 16384
    # Proxy calls a minute, per credential. Separate from RATE_LIMIT_PER_MINUTE
    # because an agent loop makes many small calls per human action, where a
    # chat turn makes one.
    MODEL_PROXY_RATE_LIMIT_PER_MINUTE: int = 120

    # Live API keys one account may hold. A ceiling, not a quota: a developer
    # needs a handful (per environment, plus one being rotated in), and an
    # unbounded list is how a compromised session mints keys unnoticed.
    API_KEYS_PER_USER: int = 10

    # Generation and tool calls through the API, per credential per minute.
    # Their own buckets because they are priced per call by an upstream, where
    # a chat turn is one request no matter how much it does. Low on purpose:
    # a partner asking for more is a conversation, a runaway loop billing us
    # for a thousand images is not.
    GENERATION_RATE_LIMIT_PER_MINUTE: int = 20
    TOOL_RATE_LIMIT_PER_MINUTE: int = 60

    # --- The app builder (app/builder) ----------------------------------
    # Models are routed by STAGE, not by role: planning writes the spec,
    # build is the first pass over an empty template, edit is every turn
    # after that. One model owns a whole turn. All four are OpenRouter slugs
    # and the builder always goes to OpenRouter, whatever MODEL_PROVIDER says,
    # because no pod serves a tool-calling model with a million-token window.
    # Slugs verified against openrouter.ai/api/v1/models on 2026-09-12.
    PLAN_MODEL: str = "deepseek/deepseek-v4.1-flash"
    BUILD_MODEL: str = "deepseek/deepseek-v4.1-flash"
    EDIT_MODEL: str = "deepseek/deepseek-v4.1-flash"
    # Takes over for one retry when a turn hits the step cap or fails the
    # typecheck three times in a row. Different vendor on purpose: a model
    # that keeps making the same mistake is not helped by more of itself.
    FALLBACK_MODEL: str = "z-ai/glm-5.3-flash"
    BUILDER_CONTEXT_TOKENS: int = 200_000
    BUILDER_MAX_REPLY_TOKENS: int = 8192
    BUILDER_TEMPERATURE: float = 0.2
    # Tool calls per turn. The brief's cap; hitting it triggers the fallback.
    BUILDER_MAX_STEPS: int = 20
    # A first build writes a whole app and gets its own, larger cap.
    BUILDER_BUILD_MAX_STEPS: int = 40
    # Once, when a first build reaches the cap while still typecheck-clean.
    BUILDER_BUILD_EXTENSION_STEPS: int = 20
    # The same for an edit turn that is still writing clean files at its cap.
    BUILDER_EDIT_EXTENSION_STEPS: int = 15
    # Seconds allowed for one file write into the sandbox (images are ~1 MB).
    BUILDER_SANDBOX_WRITE_TIMEOUT: float = 120.0
    # After a first build answers, one review compares the app with the spec
    # (pages, nav, seeded data, sections) and fills the gaps, with this many
    # extra steps. Runs before the visual critique.
    BUILDER_COMPLETION_ROUNDS: int = 1
    BUILDER_COMPLETION_STEPS: int = 14
    # Consecutive typecheck failures after write_file/edit_file before the
    # turn is handed to FALLBACK_MODEL.
    BUILDER_TYPECHECK_STRIKES: int = 3
    BUILDER_TOOL_RESULT_CHARS: int = 4000
    BUILDER_TYPECHECK_ERROR_LINES: int = 40
    # Chars of file tree + key files + recently touched files injected into
    # the system prompt each turn.
    BUILDER_CONTEXT_CHARS: int = 12_000
    BUILDER_COMMAND_TIMEOUT: int = 60
    BUILDER_TYPECHECK_TIMEOUT: int = 90
    BUILDER_RATE_LIMIT_PER_MINUTE: int = 10

    # Where the user's app runs. "e2b" is production; "local" runs the same
    # template in a temp directory on this host (dev and tests only: it is
    # not isolated from the backend process).
    SANDBOX_DRIVER: str = "e2b"
    E2B_API_KEY: str = ""
    E2B_TEMPLATE: str = "vivid-web"
    # Idle sandboxes are killed after this long without a turn or a preview
    # request. E2B's own timeout is kept a little above it as a backstop for
    # a backend that dies without sweeping.
    BUILDER_SANDBOX_IDLE_SECONDS: int = 600
    BUILDER_SANDBOX_TIMEOUT_SECONDS: int = 900
    BUILDER_DEV_PORT: int = 5173
    # Kill live sandboxes when this process stops. Off: a restart or deploy
    # leaves them running, the next process reconnects through Redis, and
    # E2B's own timeout reaps the ones nobody comes back for. On (dev only)
    # a stop kills them, and unsnapshotted work in them is lost.
    BUILDER_KILL_SANDBOXES_ON_SHUTDOWN: bool = False
    # How long get_or_create waits for the dev server to answer.
    BUILDER_DEV_SERVER_WAIT_SECONDS: int = 60
    # The template's source on disk, for the local driver and the eval.
    # Relative paths resolve from the backend's working directory.
    BUILDER_TEMPLATE_DIR: str = "../sandbox-templates/vivid-web"
    # Mobile projects (Expo, React Native) run in their own template. Metro
    # serves the web preview and Expo Go from the same port.
    E2B_MOBILE_TEMPLATE: str = "vivid-expo"
    BUILDER_MOBILE_DEV_PORT: int = 8081
    BUILDER_MOBILE_TEMPLATE_DIR: str = "../sandbox-templates/vivid-expo"
    # Expo Go on phones. React Native's dev tooling speaks plain http to the
    # dev server (packager /status, live reload) and E2B only answers https,
    # so phones go through a relay on our own host that answers http:
    # http://<sandbox id>.<this domain> -> https://8081-<sandbox id>.e2b.app
    # (a Caddy block; see docs/builder.md). Empty: exps:// straight to E2B,
    # which loads the manifest but fails React Native's packager check.
    EXPO_DEVICE_RELAY_DOMAIN: str = ""
    # Where the local driver puts project directories.
    BUILDER_LOCAL_ROOT: str = "/tmp/vivid-builder"

    # Snapshots: one tarball per turn in Cloudflare R2 (S3-compatible). Empty
    # R2 settings fall back to the S3_* storage above (MinIO in dev), so the
    # builder works on a laptop with no Cloudflare account. The endpoint can
    # be given outright or derived from the account id.
    R2_ENDPOINT: str = ""
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = ""
    # Key prefix inside the bucket, so a bucket shared with anything else
    # keeps the builder's objects in one folder.
    R2_PREFIX: str = "vivid-builder/"
    # Snapshot tarballs above this are refused (node_modules leaking in, or
    # a user uploading media into src). 64 MB.
    BUILDER_SNAPSHOT_MAX_BYTES: int = 64 * 1024 * 1024
    # `npm install` inside the sandbox after a restore whose package.json
    # differs from the template's.
    BUILDER_INSTALL_TIMEOUT: int = 180
    # Fernet key (44 url-safe base64 chars) for per-project secrets at rest:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Empty disables everything that stores a secret.
    SECRETS_ENCRYPTION_KEY: str = ""

    # --- Supabase (the builder's data and auth backend) ------------------
    # Users connect their own account (phase 4). The OAuth app is registered
    # once under our Supabase organisation at dashboard/org/_/apps; empty
    # client id disables the OAuth button, and a pasted personal access
    # token still works through POST /v1/connectors.
    SUPABASE_OAUTH_CLIENT_ID: str = ""
    SUPABASE_OAUTH_CLIENT_SECRET: str = ""
    # Must match the app registration exactly. Empty = PUBLIC_BASE_URL +
    # /v1/connectors/supabase/callback.
    SUPABASE_OAUTH_REDIRECT_URI: str = ""
    # Where the browser goes after the callback stored the connection.
    # Empty = a plain "connected, close this window" page.
    SUPABASE_OAUTH_RETURN_URL: str = ""
    SUPABASE_API_BASE: str = "https://api.supabase.com"
    SUPABASE_API_TIMEOUT: int = 60
    # This backend's public origin, for OAuth redirect URIs.
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # --- Publishing (Cloudflare Pages) -----------------------------------
    # One Pages project holds every published app, one branch alias each:
    # https://<app>.<CF_PAGES_PROJECT>.pages.dev. The token needs
    # "Cloudflare Pages: Edit" on the account and never enters a sandbox:
    # the sandbox builds, the backend uploads. Empty token disables publish.
    CF_API_TOKEN: str = ""
    CF_ACCOUNT_ID: str = ""
    CF_PAGES_PROJECT: str = "vivid-apps"
    CF_API_BASE: str = "https://api.cloudflare.com/client/v4"
    # The public hostname pattern, {alias} being the app's branch alias.
    # Change it once a custom domain fronts the project.
    BUILDER_PUBLISH_HOST: str = "{alias}.{project}.pages.dev"
    BUILDER_BUILD_TIMEOUT: int = 300
    # A built site above this is refused (a stray video in public/).
    # Cloudflare caps a single file at 25 MiB, not the site; generated
    # pictures are about a megabyte each, so a real catalogue needs room.
    BUILDER_PUBLISH_MAX_BYTES: int = 120 * 1024 * 1024

    # User-uploaded assets for the builder (logos, product photos, fonts).
    BUILDER_ASSET_MAX_BYTES: int = 8 * 1024 * 1024
    BUILDER_ASSETS_MAX_TOTAL_BYTES: int = 48 * 1024 * 1024
    BUILDER_ASSETS_PER_PROJECT: int = 60

    # --- Design quality -----------------------------------------------
    # Skills are folders of packaged expertise (SKILL.md + references) the
    # orchestrator attaches to a turn by stage and project; users never see
    # them. Relative paths resolve from the backend's working directory.
    BUILDER_SKILLS_DIR: str = "skills"
    BUILDER_DESIGN_SKILL: bool = True
    BUILDER_COPY_SKILL: bool = True
    # The app-logic skill (accounts, roles and policies, data, lifecycles,
    # edge functions) rides with every turn of a project that has Supabase.
    BUILDER_FULLSTACK_SKILL: bool = True
    # Motion (GSAP, Framer Motion, parallax, shaders) for pages with a hero
    # and for any request about animation.
    BUILDER_MOTION_SKILL: bool = True
    # Web3 (wallet, viem, Solidity patterns) for on-chain projects.
    BUILDER_WEB3_SKILL: bool = True
    # Pageviews accepted per visitor address per project per minute.
    BUILDER_ANALYTICS_PER_MINUTE: int = 60
    # After a build or edit turn that changed UI, screenshot the page at
    # desktop and phone widths and let the model critique and fix it.
    BUILDER_DESIGN_CRITIQUE: bool = True
    BUILDER_CRITIQUE_ROUNDS: int = 1
    # Edit turns get the screenshot critique only when the request is about
    # looks or at least this many files changed; first builds always do.
    BUILDER_CRITIQUE_MIN_FILES: int = 3
    # Extra steps the critique may spend beyond BUILDER_MAX_STEPS.
    BUILDER_CRITIQUE_STEPS: int = 6
    BUILDER_SCREENSHOT_TIMEOUT: int = 90
    # Metro bundles a mobile app's web preview on the first request, which
    # takes longer than Vite; its screenshots get more time.
    BUILDER_MOBILE_SCREENSHOT_TIMEOUT: int = 180
    # Scores screenshots in the design eval. A different vendor from the
    # builder, so it is not grading its own work. Must take image input.
    DESIGN_JUDGE_MODEL: str = "z-ai/glm-5.3-flash"

    # Pictures the builder generates for a project with no uploads, per
    # turn. Each costs about a third of a cent on the default image model.
    # A first build seeds eight to twelve products and needs one each plus
    # a hero; an edit rarely needs more than a few.
    BUILDER_IMAGES_PER_TURN: int = 6
    BUILDER_IMAGES_FIRST_BUILD: int = 16

    # Mobile app builds on EAS (Expo's cloud). Vivid's own Expo account
    # builds for users who have not connected theirs, and those builds are
    # charged; a user's connected account (the "expo" connector) builds on
    # their own quota for free. EXPO_TOKEN is a robot token of EXPO_OWNER's.
    # It never enters a project's sandbox: builds start in a throwaway one.
    EXPO_TOKEN: str = ""
    EXPO_OWNER: str = ""
    EXPO_API_TIMEOUT: int = 20
    # What a build on Vivid's account costs the user, in USD, debited from
    # their wallet. Launch price while payments are being tested, below what
    # EAS charges us ($1 Android / $2 iOS on a medium worker, after the free
    # tier); the intended prices are $2 and $4. Set in app.env to change.
    EAS_BUILD_PRICE_ANDROID_USD: float = 0.20
    EAS_BUILD_PRICE_IOS_USD: float = 0.20
    # Builds on Vivid's account per user per calendar month, an abuse cap
    # on top of the wallet; 0 = no cap.
    EAS_VIVID_BUILDS_PER_MONTH: int = 0
    # How long starting a build (restore, install, upload) may take, and how
    # often unfinished builds are polled.
    EAS_START_TIMEOUT: int = 600
    EAS_POLL_SECONDS: int = 30

    # ------------------------------------------------------------- wallet
    # A user's balance with Vivid, in USD, topped up by bank transfer or
    # crypto and spent on plans, extra tokens and paid builds.
    # Pouch (Liquifia fiat API): one Nigerian virtual account per user.
    POUCH_API_KEY: str = ""
    POUCH_BASE_URL: str = "https://fiat-api.pouchfinance.xyz"
    POUCH_WEBHOOK_SECRET: str = ""
    # Pouch reports transfer amounts in kobo (as its other amounts are).
    # Flip to false if a live transfer shows naira; nothing else changes.
    POUCH_AMOUNTS_IN_KOBO: bool = True
    # Dextopus: static crypto deposit addresses per user, every deposit
    # settled as USDC on Base to Vivid's treasury address.
    DEXTOPUS_API_KEY: str = ""
    DEXTOPUS_BASE_URL: str = "https://swap-api.dextopus.com"
    DEXTOPUS_WEBHOOK_SECRET: str = ""
    DEXTOPUS_SETTLEMENT_ADDRESS: str = ""
    PAYMENTS_API_TIMEOUT: int = 20
    # Bank deposits in NGN are converted to USD at the day's rate minus
    # this spread (basis points), which covers FX risk.
    WALLET_FX_SPREAD_BPS: int = 150
    # Currencies the balance can be shown in (converted at live rates).
    WALLET_DISPLAY_CURRENCIES: list[str] = ["USD", "NGN", "GHS", "KES", "ZAR", "EUR", "GBP"]
    # How often deposits are fetched from both providers, in case a webhook
    # never arrived. Webhooks only make crediting faster.
    WALLET_RECONCILE_SECONDS: int = 300
    # Smallest crypto deposit worth crediting, in USD (below it the bridging
    # fees eat most of it; Dextopus still settles it).
    WALLET_CRYPTO_MIN_USD: float = 2.0

    # ------------------------------------------------------------ vivid pay
    # Payments for the apps users build: a customer pays by bank transfer
    # into an account number made for their order (a Pouch virtual
    # account); the money, less Vivid's fee, lands in the app owner's
    # earnings (naira, separate from the credits wallet) and is withdrawn
    # to a Nigerian bank after a one-time BVN check.
    VIVIDPAY_ENABLED: bool = True
    # Vivid's fee per payment: basis points, never below the minimum (which
    # covers moving the money to the owner's earnings account) nor above
    # the cap. Kobo.
    VIVIDPAY_FEE_BPS: int = 150
    VIVIDPAY_MIN_FEE_KOBO: int = 10_000
    VIVIDPAY_FEE_CAP_KOBO: int = 200_000
    VIVIDPAY_CHECKOUT_MINUTES: int = 30
    VIVIDPAY_MIN_CHECKOUT_KOBO: int = 10_000
    VIVIDPAY_MAX_CHECKOUT_KOBO: int = 500_000_000
    # Checkouts a project may open per minute, and per payer address.
    VIVIDPAY_CHECKOUTS_PER_MINUTE: int = 30
    VIVIDPAY_CHECKOUTS_PER_IP_MINUTE: int = 6
    VIVIDPAY_MIN_WITHDRAWAL_KOBO: int = 100_000
    VIVIDPAY_DAILY_WITHDRAWAL_KOBO: int = 500_000_000
    # What a payout costs when Pouch's quote is unavailable (fee only; the
    # ₦50 stamp duty on ₦10,000 and above is added on top).
    VIVIDPAY_PAYOUT_FEE_KOBO: int = 5_000
    # Where the apps call from, for the account on a checkout's receipts.
    VIVIDPAY_API_BASE: str = ""

    # -------------------------------------------------------------- plans
    # Free / Pro / Max for the app builder, counted in credits. A credit is
    # PLAN_TOKENS_PER_CREDIT builder tokens (plan, build, edit, critique, as
    # recorded in builder_usage_events); allowances are credits per month and
    # per rolling PLAN_WINDOW_HOURS window. At ~$0.20 of cost per 1M tokens a
    # credit costs us ~$0.10; re-tune from `python -m app.scripts.token_economics`.
    PLAN_TOKENS_PER_CREDIT: int = 500_000
    PLAN_WINDOW_HOURS: int = 5
    PLAN_FREE_APPS: int = 2
    PLAN_FREE_WINDOW_CREDITS: float = 4
    PLAN_FREE_MONTH_CREDITS: float = 20
    # Launch prices while payments are being tested; the intended prices are
    # Pro $32 ($26/mo yearly) and Max $78 ($62/mo yearly). Set these in
    # app.env to change them without a deploy.
    PLAN_PRO_PRICE_USD: float = 0.50
    PLAN_PRO_YEARLY_PRICE_USD: float = 0.40
    PLAN_PRO_WINDOW_CREDITS: float = 16
    PLAN_PRO_MONTH_CREDITS: float = 100
    PLAN_MAX_PRICE_USD: float = 1.00
    PLAN_MAX_YEARLY_PRICE_USD: float = 0.80
    PLAN_MAX_WINDOW_CREDITS: float = 24
    PLAN_MAX_MONTH_CREDITS: float = 200
    # Extra credits bought from the wallet once the plan is used up; they
    # never expire.
    PLAN_CREDIT_PRICE_USD: float = 0.30
    PLAN_CREDIT_PACKS: list[int] = [10, 50, 200]
    # A generated image counts as this many tokens against the allowance.
    PLAN_IMAGE_TOKEN_EQUIVALENT: int = 20_000
    # A renewal the wallet cannot pay keeps the plan this many days.
    BILLING_GRACE_DAYS: int = 3

    # What our providers charge us, for the economics report and to price
    # sandbox seconds in the usage ledger. E2B: per vCPU-second and per
    # GiB-second (confirm on the E2B dashboard).
    E2B_COST_PER_VCPU_SECOND: float = 0.000014
    E2B_COST_PER_GIB_SECOND: float = 0.0000045
    IMAGE_COST_USD: float = 0.003
    EAS_COST_ANDROID_USD: float = 1.0
    EAS_COST_IOS_USD: float = 2.0

    # Limits
    RATE_LIMIT_PER_MINUTE: int = 20
    DEFAULT_CLIENT_ID: str = "vivid_web"

    # Operator view of /v1/health/models and /v1/health/code: which provider
    # and model serve each role, the OpenRouter balance and key expiry. The
    # routes are public for the app's sake, so this bearer token gates the
    # detail. Empty = the detail is never shown. Generate: openssl rand -hex 24
    HEALTH_TOKEN: str = ""

    # Reads the waitlist (GET /v1/waitlist): Authorization: Bearer <ADMIN_TOKEN>.
    # Separate from HEALTH_TOKEN because the list is people's names and
    # emails. Empty = nobody can read it. Generate: openssl rand -hex 24
    ADMIN_TOKEN: str = ""
    # Sign-ups per minute from one address; the form is public.
    WAITLIST_PER_MINUTE: int = 5

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("MODEL_PROVIDER", "LLM_PROVIDER", "CODE_LLM_PROVIDER",
                     "ASR_PROVIDER", "TTS_PROVIDER")
    @classmethod
    def _known_provider(cls, value: str, info) -> str:
        """Refuse to boot on a misspelt provider. This switch gets flipped in
        a hurry, at the moment a GPU dies; a typo must fail at startup, not
        on the first chat turn after the restart."""
        value = value.strip().lower()
        if value == "" and info.field_name != "MODEL_PROVIDER":
            return value  # an override left empty follows the master switch
        if value not in LLM_PROVIDERS:
            raise ValueError(
                f"{info.field_name} must be one of {', '.join(LLM_PROVIDERS)}, "
                f"not {value!r}")
        return value


settings = Settings()
