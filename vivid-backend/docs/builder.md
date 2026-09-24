# The app builder

`/v1/builder` is the backend of the prompt-to-app product: a user describes
an app, an agent writes it inside a sandbox, and the user watches the preview.
This document is the contract a client builds against. The code is in
`app/builder/` and `app/api/routes/builder.py`.

## Routes

All routes take the usual bearer token (a session or a `vivid_` key) and
only ever see the caller's own projects.

```
POST   /v1/builder/projects                 {name?, skip_plan?, target?} -> project (mode: plan)
POST   /v1/builder/projects/{id}/build      leave plan mode    -> project (mode: build)
GET    /v1/builder/projects                                    -> [project]
GET    /v1/builder/projects/{id}                               -> project
PATCH  /v1/builder/projects/{id}            {name?, spec_md?, fullstack?}  -> project
DELETE /v1/builder/projects/{id}            kills the sandbox too
GET    /v1/builder/projects/{id}/messages                      -> [message]
POST   /v1/builder/projects/{id}/chat       {text}             -> event stream
POST   /v1/builder/projects/{id}/cancel                        -> {cancelled}
GET    /v1/builder/projects/{id}/preview                       -> {url, sandbox_id, driver, target, device_url}
GET    /v1/builder/projects/{id}/files                         -> {files: [path]}
GET    /v1/builder/projects/{id}/files/{path}                  -> {path, content}
GET    /v1/builder/projects/{id}/snapshots                     -> [snapshot]
POST   /v1/builder/projects/{id}/snapshots/{seq}/restore       -> snapshot
GET    /v1/builder/projects/{id}/usage                         -> usage totals
POST   /v1/builder/projects/{id}/builds     {platform, profile?, account?} -> 202 build (mobile)
GET    /v1/builder/projects/{id}/builds                        -> [build], newest first
GET    /v1/builder/projects/{id}/builds/{build_id}             -> build (refreshed from Expo)
POST   /v1/builder/projects/{id}/builds/{build_id}/cancel      -> build
GET    /v1/builder/app-builds/options                          -> accounts, prices, what is left
```

Errors use the backend's envelope (`{"error": {"code", "message"}}`). Codes a
client should branch on: `busy` (409, a turn is already running), `rate_limited`
(429), `not_configured` (503, no model key), `sandbox_unavailable` (503).

## The chat stream

`POST .../chat` answers `text/event-stream` with the header
`x-vercel-ai-ui-message-stream: v1`. It is the AI SDK UI Message Stream, so a
client using `useChat` with the default transport pointed at this route (or a
route that pipes it through) renders it with no adapter. Each event is
`data: <json>`; the stream ends with `data: [DONE]`.

Parts, in the order a turn produces them:

```
{"type":"start","messageId":"msg_..."}
{"type":"start-step"}
{"type":"text-start","id":"txt_..."}                 the model talking
{"type":"text-delta","id":"txt_...","delta":"..."}
{"type":"text-end","id":"txt_..."}
{"type":"tool-input-available","toolCallId":"...","toolName":"edit_file","input":{...}}
{"type":"tool-output-available","toolCallId":"...","output":"Edited src/App.tsx.\nTypecheck: clean."}
{"type":"tool-output-error","toolCallId":"...","errorText":"error: ..."}
{"type":"finish-step"}
... more steps ...
{"type":"data-notice","data":{"text":"The model connection dropped; retrying.","reason":"stream_retry","attempt":1}}
{"type":"data-notice","data":{"text":"Retrying with a different model.","reason":"step_limit"}}
{"type":"data-usage","data":{"model":"...","steps":7,"tokens_in":..,"tokens_out":..,"reason":"answered"}}
{"type":"data-brief","data":{"markdown":"..."}}      plan mode, first message: the expanded brief
{"type":"data-review","data":{"kind":"completeness","round":1}}   first builds: the spec check
{"type":"data-critique","data":{"round":1,"broken":false,"screenshots":[{"name":"desktop","width":1280,"url":"..."},{"name":"mobile","width":390,"url":"..."}]}}   broken: the page crashed or rendered nothing; the model fixes that first
{"type":"data-snapshot","data":{"id":"...","seq":3}}   after finish, when the turn changed files
{"type":"error","errorText":"..."}                   the turn failed; stream still ends normally
{"type":"abort","reason":"cancelled by the user"}
{"type":"finish"}
```

Tool names: `read_file`, `write_file`, `edit_file`, `list_files`,
`run_command`, `get_dev_server_logs`, `generate_image`, and with a Supabase
backend `apply_migration`, `deploy_edge_function`, `set_secret`. Tool outputs are strings, at most 4,000
characters. A client that wants to show "what the agent is doing" renders the
tool parts; one that wants only the conversation renders the text parts.

The preview is the sandbox's dev server with hot reload: point an iframe at
the `preview` URL and it updates as files are written. Fetch `preview` once
per project and again after a `sandbox_unavailable`; each call also keeps the
sandbox alive (it is killed after ten idle minutes).

## Stored messages

`GET .../messages` returns each message's `parts` exactly as streamed, folded:
text deltas become one `{"type":"text","text"}` part, a tool call becomes one
`{"type":"tool-<name>","toolCallId","state","input","output"|"errorText"}` part,
and `step-start`, `data-*` parts are kept in order. The user's own message is
a single text part. A thread reloaded from here is the same shape a client
holds after watching the stream.

## Uploaded files (logos, product photos, fonts)

```
POST   /v1/builder/projects/{id}/assets            multipart `file` -> asset (201)
GET    /v1/builder/projects/{id}/assets            -> [asset] with `path` and a time-limited `url`
DELETE /v1/builder/projects/{id}/assets/{asset_id}
```

An upload is stored in R2 and copied into the app at `public/uploads/<name>`,
so the preview and the published site serve it at `/uploads/<name>` (the
`path` field). Names are made URL-safe ("Air Max 90.PNG" becomes
`air-max-90.png`); uploading the same name again replaces the file. Types:
PNG, JPEG, WebP, GIF, SVG, AVIF, WOFF/WOFF2/TTF/OTF, PDF, MP4, MP3; 8 MB per
file, 48 MB per project. Uploads ride along in snapshots, and a fresh
sandbox gets any it lacks from the store.

The model is told about uploads in every turn ("Files the user uploaded",
with paths). In plan mode it asks whether the user has a logo and product
photos or wants placeholders, and the uploaded images are passed to the
plan model as pictures so the spec can name them. A client shows the
upload control next to the chat; the user uploads, then answers the
question in text ("uploaded the logo and three photos").

## Design quality

Three things work together so a first build looks designed, on phones and
desktop, without the user knowing any of it exists:

- **The design skill** (`skills/design/`): a written method (type scale,
  spacing rhythm, hierarchy, contrast, imagery, states, mobile first),
  curated palettes and font pairings, and one page recipe (shop, booking,
  landing page, portfolio, dashboard) chosen from the spec. The loader
  attaches it to every build and edit turn's prompt. `BUILDER_DESIGN_SKILL`
  turns it off.
- **The critique round**: after the model answers a turn that changed
  files, the sandbox screenshots the page at 1280px and 390px (Chromium is
  in the template), the pictures go to the model with a critique brief, and
  it fixes what it sees with a few extra steps. The stream carries a
  `data-critique` part with the round number and time-limited screenshot
  URLs, so a client can show "checking how it looks". Settings:
  `BUILDER_DESIGN_CRITIQUE`, `BUILDER_CRITIQUE_ROUNDS`, `BUILDER_CRITIQUE_STEPS`.
- **The copy skill** (`skills/copy/`): how the words on the page are
  written: outcome headlines, verb-plus-object buttons, specific claims,
  formatted prices, a banned list of generated-sounding phrases, Nigerian
  context. Attached with the design skill to every UI turn.
  `BUILDER_COPY_SKILL` turns it off. Adapted from boraoztunc/skills and
  stop-slop; see `skills/copy/NOTICE.md`.
- **The app-logic skill** (`skills/fullstack/`): attached to every turn of a
  project the user asked to be full-stack (`fullstack` on the project, set
  by the plan's `write_spec` or by `PATCH`) once Supabase is linked. A
  site stays a site by default; a full-stack project without a backend gets
  a prompt note to build with local state and ask the user to connect
  Supabase. It fixes the shape of a real app:
  `profiles` with roles filled by a sign-up trigger, `is_admin()` /
  `is_staff()` helpers and a policy set per table, money in kobo, orders
  and bookings as state machines moved by one SQL function that also logs
  events and decrements stock, edge functions for anything with a secret,
  loading/empty/error states, pagination, realtime for the admin table,
  and a definition of done (sign-up to first order works end to end, the
  owner moves it along in /admin, policies stop a customer's admin writes).
  `references/patterns.md` carries the SQL and TypeScript to copy
  (migrations, AuthProvider, route guards, db helpers, edge-function
  skeleton). The completeness review checks that definition of done when
  a backend is linked. `BUILDER_FULLSTACK_SKILL` turns it off.
- **Complete first builds**: a first build has its own step budget
  (`BUILDER_BUILD_MAX_STEPS`, 40) and, after the model answers, one
  completeness review (`data-review` part): the app is compared with the
  spec page by page (every page routed and in the nav, lists seeded with at
  least eight realistic items, every recipe section present, admin
  reachable) and the gaps are built in the same turn, with
  `BUILDER_COMPLETION_STEPS` extra steps. Then the visual critique runs.
  Follow-up edits stay minimal by rule.
- **Generated images**: when the user uploaded nothing, the model has a
  `generate_image(prompt, name, aspect)` tool. The picture is rendered by
  the image model, stored like an upload (R2 and `public/uploads/<name>`),
  listed in `GET .../assets`, and used by path. Logos are not generated; the
  skill sets the brand name as a wordmark. `BUILDER_IMAGES_PER_TURN` caps it.

`python -m app.scripts.design_eval --publish --html design.html` renders
three specs with and without the skill and critique, publishes both, has a
different model score them blind on hierarchy, spacing, consistency,
readability and mobile, and writes a page with every A next to its B.

## Plan mode

A new project starts in `mode: "plan"` (pass `skip_plan: true` to start
building at once). In plan mode a chat turn runs on `PLAN_MODEL` with two
tools and no sandbox, so it costs nothing but tokens:

- `ask_user`: two to six questions, each with two to four options and, by
  default, free text. It ends the turn. Render the `tool-ask_user` part's
  `input.questions` as tappable cards and send the answers as the next user
  message in plain text ("Customers. Yes, sign in. Blue and white.").
- `write_spec`: markdown with the headings Goal, Users, Pages, Data model,
  Integrations, Out of scope. The spec is stored on the project (`spec_md`)
  and the stream carries a `data-spec` part with the markdown.

`POST .../chat` in plan mode accepts `images` (up to four https or data
URLs) as reference screenshots; the plan model reads them. The user edits
the spec with `PATCH {spec_md}` and starts the build with `POST .../build`.
From then on every turn runs on the build or edit model with the spec in
its prompt, and `spec.md` in the sandbox mirrors it.

Plan-mode parts, in order: `start`, `start-step`, optional text,
`tool-input-available` (ask_user or write_spec), `tool-output-available`,
`finish-step`, then for a written spec `data-spec`, then `data-usage` with
`"mode": "plan"`, `finish`, `[DONE]`. Plan turns never produce a snapshot.

## Supabase (the app's data and auth)

A user connects their own Supabase account once, as a connector, and any of
their builder projects can use it:

```
GET    /v1/connectors/supabase/authorize   -> {url}: send the browser there (OAuth app needed)
GET    /v1/connectors/supabase/callback    Supabase returns here; stores the connector
POST   /v1/connectors {provider: "supabase", token: "sbp_..."}   a pasted personal access token
GET    /v1/connectors                       each connector; Supabase rows list `projects`
POST   /v1/builder/projects/{id}/supabase  {project_ref} -> project (backend_mode: byo)
                                            or {project_ref, url?, anon_key} with no connector
                                            + database_url (Postgres DSN): migrations over Postgres, no connector needed
DELETE /v1/builder/projects/{id}/supabase  unlink
```

Linking reads the project's URL and publishable key through the Management
API and keeps them encrypted per project. On every build turn the sandbox's
`.env` is written with `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`; the
template's `src/lib/supabase.ts` reads them. `.env` is git-ignored, so it is
never in a snapshot. With a connector the model also gets three tools:
`apply_migration(name, sql)` (recorded in the project's migration history),
`deploy_edge_function(name, code, verify_jwt?)` and `set_secret(key, value)`,
all through the Management API with the user's token. A link made by
pasting keys gives the app its env but no tools. The system prompt tells the
model to use Supabase auth for login, enable row level security on every
table, and keep the service key inside edge functions.

OAuth tokens expire; the refresh token is stored with the connector and
renewed before use. Connector tokens (GitHub too) are encrypted at rest with
`SECRETS_ENCRYPTION_KEY`; rows written before that stay readable.

## Payments (Paystack)

The user connects their own Paystack account once, as a connector:

```
POST /v1/connectors {provider: "paystack", token: "sk_...", public_key: "pk_..."}
POST   /v1/builder/projects/{id}/payments   -> project (payments_provider: paystack)
DELETE /v1/builder/projects/{id}/payments
POST   /v1/builder/projects/{id}/maps       -> project (maps_provider: google)
POST   /v1/builder/projects/{id}/chain      -> project (chain: ark-devnet, deployer_address); DELETE turns it off
POST   /v1/builder/projects/{id}/chain/faucet
DELETE /v1/builder/projects/{id}/maps
```

Both keys must be test or both live; the secret is verified against
Paystack and stored encrypted. Enabling payments on a project puts the
public key into the app's `.env` as `VITE_PAYSTACK_PUBLIC_KEY` and attaches
the payments skill to every UI turn. With a Supabase backend linked, the
secret key is also stored in that project's edge-function secrets, so the
model builds the verified flow: a pending order row, Paystack's inline
checkout with the order id as reference, a webhook edge function that
checks the signature and marks the order paid. Without a backend the skill
uses the inline checkout only. Amounts are kobo; money goes to the user's
Paystack balance, never through Vivid. The template ships
`@paystack/inline-js`.

## The prompt builder

A project's first message is usually one line. Before any question is
asked, plan mode runs it through a meta-prompt that writes a full brief:
what it is, who it is for, pages and flows, data, content and pictures
needed, look and feel with two alternatives, and assumptions to confirm.
The brief streams as ordinary text, is carried as a `data-brief` part, is
stored on the project (`brief_md`), and the planner's questions and spec
build on it. Reference images on that first message go to the meta-prompt
too. Later turns skip it.

## Publishing

```
POST /v1/builder/projects/{id}/publish              -> 202 publish row (status: pending)
GET  /v1/builder/projects/{id}/publishes            -> newest first
GET  /v1/builder/projects/{id}/publishes/{pub_id}   -> poll until live | failed
```

Publish runs `vite build` in the sandbox, brings `dist/` back to the
backend, and uploads it to Cloudflare Pages with the same direct-upload
protocol Wrangler uses; the Cloudflare token never enters a sandbox. Every
app is a branch alias on one Pages project, so the URL is
`https://<alias>.<CF_PAGES_PROJECT>.pages.dev`, where the alias is the
project's name slug plus six characters of its id. A `_redirects` rule
sends unknown paths to `index.html` for client-side routing. On success
the project's `published_url` is set. A failed build puts the compiler's
last lines in `error`. When a custom domain fronts the Pages project,
`BUILDER_PUBLISH_HOST` changes the pattern and nothing else moves.

## Mobile apps (iOS and Android)

A project is a website or a mobile app, chosen at creation (`target: "web"`
or `"mobile"`, default web) and fixed for life; `app/builder/targets.py`
holds everything that differs. A mobile project is an Expo app (React
Native, Expo Router, NativeWind) in the `vivid-expo` sandbox template:

- Plan mode writes a spec with Screens and Device features instead of Pages,
  and picks a screen recipe from `skills/mobile/references/recipes`.
- Build turns get the mobile prompt and the mobile skill (method, component
  kit, navigation, device APIs, motion, fonts, state or Supabase, the recipe)
  instead of the web design and motion skills.
- The model may only add packages Expo Go can run (`npx expo install`; the
  Expo SDK and pure JavaScript). Other native modules are refused with the
  reason, so the device preview never breaks.
- Uploads live at `assets/uploads/<name>` and are used with `require()`.
  A generated logo becomes the app icon.
- `GET .../preview` returns the web preview (react-native-web) as `url`,
  and `device_url` (`exps://…`) for Expo Go, shown to the user as a QR code.
  It is null for a local sandbox, which a phone cannot reach.
- Payments, maps, on-chain and Decane sign-in are web only for now: their
  routes answer 400 `not_supported` for a mobile project, and so does
  `/publish`. A mobile project ships through builds.

### Builds

```
POST /v1/builder/projects/{id}/builds   {platform: android|ios, profile: preview|production, account: auto|vivid|user}
```

`preview` is an Android APK to install directly (or an iOS simulator build);
`production` is a store build (an Android AAB; iOS only on the user's own
account, where their Apple credentials live). The row comes back `starting`.
Poll `GET .../builds/{build_id}` until `finished` (with `artifact_url`),
`failed` (with `error`) or `canceled`; each GET refreshes a build in flight
from Expo, and a background poller does the same every `EAS_POLL_SECONDS`.

The upload to EAS runs in a throwaway sandbox: the snapshot is restored,
`app.config.*` removed, app.json given the store ids (`app.vivid.<name><id>`,
fixed at the first build) and the Expo account, then `eas init` (first
build on that account) and `eas build --no-wait` run with the token in their
own environment only. The token never enters the project's sandbox.

Accounts: `vivid` builds on Vivid's Expo account (`EXPO_TOKEN`,
`EXPO_OWNER`) and is charged: `price` and `currency` are on the row,
`charge` is `charged`, and a build that fails or is cancelled is
`refunded`. At most `EAS_VIVID_BUILDS_PER_MONTH` charged builds per user a
month; past that the POST answers 402 `payment_required`. `user` builds on
the user's own Expo account, connected as the `expo` connector
(`POST /v1/connectors {provider: "expo", token}`), and costs nothing here.
`auto` picks the user's account when it is connected.

## Wallet and plans

Users pay Vivid from a wallet: a USD balance (integer micro-USD) topped up
by bank transfer into their own Nigerian virtual account (Pouch) or by
crypto to their own deposit addresses (Dextopus, settled as USDC on Base).
Plans, extra tokens and builds on Vivid's Expo account are paid from it.

```
GET    /v1/wallet?currency=NGN          balance in USD and one display currency
GET    /v1/wallet/entries               history
POST   /v1/wallet/bank-account          the user's virtual account (made once)
GET    /v1/wallet/crypto/options        tokens and chains
POST   /v1/wallet/crypto/address        {option} -> the user's address (made once)
POST   /v1/wallet/credit-packs          {credits} buy extra builder credits
GET    /v1/plans                        plans, prices, packs
GET    /v1/me/plan                      plan, 5-hour and monthly meters, extra credits
POST   /v1/me/plan                      {plan, yearly, seats} subscribe or change
DELETE /v1/me/plan                      cancel at the end of the period
GET    /v1/team, POST /v1/team/invites, POST /v1/team/accept, DELETE /v1/team/members/{id}
POST   /v1/webhooks/pouch, /v1/webhooks/dextopus   provider webhooks
GET    /v1/admin/economics?days=30      cost per 1M tokens and plan margins (ADMIN_TOKEN)
```

Money comes in only as the provider's API reports it: a webhook triggers a
fetch of the transfer or deposit, and a reconciler polls both providers
every `WALLET_RECONCILE_SECONDS`, so a lost webhook loses nothing. Each
deposit is credited once (unique provider reference). Bank deposits in NGN
convert at the day's rate less `WALLET_FX_SPREAD_BPS`.

Plans (all `PLAN_*` settings) are counted in credits: one credit is
`PLAN_TOKENS_PER_CREDIT` builder tokens (500,000 by default). Free has 2
apps and 20 credits a month (4 per rolling 5-hour window); Pro 100 a month;
Team 200 a month per seat, pooled. A turn is checked when it starts (429
`limit_reached` with credits and reset times in `error.details`) and always
finishes; usage beyond the allowance comes off extra credits
(`PLAN_CREDIT_PRICE_USD` each, never expiring). Creating a third app on Free is 402 `plan_limit`.
Subscriptions renew from the wallet; an unpaid renewal keeps the plan for
`BILLING_GRACE_DAYS`, then it lapses to Free.

`python -m app.scripts.token_economics` reports what a million tokens costs
from the usage ledger (model, sandbox, images) and each plan's margin.

## Versions

Every turn that changes a file ends with a snapshot: a git commit in the
sandbox, a tarball without node_modules stored in R2, and a row with a
`seq` starting at 1. The stream announces it as a `data-snapshot` part and
`GET .../snapshots` lists them with the turn's summary. The sandbox is
disposable: when it is gone (idle, expired, or the backend restarted past
its lifetime), the next `preview` or `chat` starts a fresh one and restores
the project's current snapshot into it, reinstalling packages only if
package.json changed. `POST .../snapshots/{seq}/restore` makes an older
version current and, if a sandbox is live, puts its files there at once; the
next snapshot continues the sequence, so going back loses nothing.

## Usage

`GET .../usage` totals the project's ledger: model calls and tokens (priced
from OpenRouter's public list; `cost_usd` is the sum of what was priceable),
sandbox seconds (recorded when a sandbox is killed or found dead), and
snapshot bytes. Rows are written per model call, per sandbox session and
per snapshot in `builder_usage_events`.

## Models and configuration

```
OPENROUTER_API_KEY   required
PLAN_MODEL           plan mode (phase 3)             default deepseek/deepseek-v4.1-flash
BUILD_MODEL          first turn on the empty template default deepseek/deepseek-v4.1-flash
EDIT_MODEL           every later turn                 default deepseek/deepseek-v4.1-flash
FALLBACK_MODEL       one retry on step cap / 3 typecheck failures   default z-ai/glm-5.3-flash
SANDBOX_DRIVER       e2b (production) | local (dev)
E2B_API_KEY, E2B_TEMPLATE=vivid-web
BUILDER_TEMPLATE_DIR path to sandbox-templates/vivid-web (local driver, eval)
R2_ENDPOINT or R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PREFIX
                     snapshot store; empty falls back to the S3_* settings (MinIO in dev)
SECRETS_ENCRYPTION_KEY  Fernet key for per-project secrets and connector tokens
SUPABASE_OAUTH_CLIENT_ID, SUPABASE_OAUTH_CLIENT_SECRET   the Connect button (dashboard/org/_/apps)
SUPABASE_OAUTH_REDIRECT_URI   default PUBLIC_BASE_URL + /v1/connectors/supabase/callback
SUPABASE_OAUTH_RETURN_URL     where the browser goes after connecting (default: a plain page)
PUBLIC_BASE_URL               this backend's public origin
CF_API_TOKEN (Cloudflare Pages: Edit), CF_ACCOUNT_ID, CF_PAGES_PROJECT   publishing
BUILDER_PUBLISH_HOST          default {alias}.{project}.pages.dev
E2B_MOBILE_TEMPLATE=vivid-expo, BUILDER_MOBILE_TEMPLATE_DIR   mobile projects' template
EXPO_TOKEN, EXPO_OWNER        Vivid's Expo account for charged builds (a robot token)
EAS_BUILD_PRICE_ANDROID, EAS_BUILD_PRICE_IOS, EAS_BUILD_CURRENCY   price per build
EAS_VIVID_BUILDS_PER_MONTH    charged builds per user per month (default 5)
```

A turn is capped at `BUILDER_MAX_STEPS` (20) tool calls. A model call whose
stream breaks is restarted up to `CODE_STREAM_RETRIES` times (a `data-notice`
with reason `stream_retry`; the half-streamed text is closed and the
conversation keeps only completed calls). If the primary model hits the step
cap, fails the typecheck `BUILDER_TYPECHECK_STRIKES` (3) times in a row, or
cannot be reached at all, the turn is retried once on `FALLBACK_MODEL`, and
the stream says so with a `data-notice` part and a line of text.

## The sandbox

The template `sandbox-templates/vivid-web` is Vite, React 19, TypeScript,
Tailwind v4 and shadcn/ui with node_modules installed and git initialised;
the dev server runs on port 5173. On E2B it is a custom template built with
`python sandbox-templates/vivid-web/template.py`. Locally
(`SANDBOX_DRIVER=local`) the same directory is copied per project and
`npm run dev` started as a child process; run `npm install` in the template
directory once first.

Mobile projects use `sandbox-templates/vivid-expo` (Expo SDK 57, Metro on
port 8081, serving the web preview and Expo Go). Build it with its
`template.py`; for the local driver run its `setup.sh` once.

Phones need a relay. React Native's dev tooling in Expo Go talks plain http
to the dev server (the packager `/status` check, live reload), and E2B only
answers https, so `EXPO_DEVICE_RELAY_DOMAIN` names a domain whose
subdomains a proxy on our host forwards to the sandbox. With
`EXPO_DEVICE_RELAY_DOMAIN=170-75-171-250.sslip.io` (no DNS to set up: sslip.io
resolves the name to that IP) the QR code is `exp://<sandbox id>.<domain>`,
Metro advertises `http://<sandbox id>.<domain>`, and the host's Caddy has:

```
http://*.170-75-171-250.sslip.io {
	@sandbox header_regexp Host ^[a-z0-9]{12,40}\.170-75-171-250\.sslip\.io(:80)?$
	# Expo's JS-debugger endpoint fetches /json/list through this proxy, gets
	# the app's HTML (Metro answers it for localhost only), throws and takes
	# Metro down. Phones never need it.
	handle /_expo/debugger* {
		respond "Not found" 404
	}
	handle @sandbox {
		reverse_proxy 8081-{labels.3}.e2b.app:443 {
			header_up Host 8081-{labels.3}.e2b.app
			transport http {
				tls
				tls_server_name 8081-{labels.3}.e2b.app
			}
			flush_interval -1
		}
	}
	handle {
		respond "Not found" 404
	}
}
```

With your own domain instead, point a wildcard DNS record at the host, use
it in the block (`{labels.N}` counts from the right, so adjust N) and in
the setting. It must stay plain http (no Cloudflare proxying).

## Evaluating models

```
python -m app.scripts.builder_eval --out baseline.json
python -m app.scripts.builder_eval --build anthropic/claude-sonnet-5 --edit anthropic/claude-sonnet-5 --out sonnet.json
```

Five build prompts and five edit prompts on the local driver; reports steps,
typecheck failures, tokens and cost per prompt, and totals. It calls the real
models and costs money.
