# Vivid Builder API — issues found integrating a web client

Found while wiring a Next.js client to `https://vivid.tsionark.io` against
`llms.txt`. **Nearly all of the first round is fixed** — this file has been cut
back to what is still open, with the closed items listed at the bottom so the
history is not lost.

Re-checked against the `llms.txt` of 2026-09-13 and the live production
deployment.

---

## Still open

### 1. CORS is still closed to us in production  ·  config

The new endpoint index says:

> browsers may call every route directly, including the SSE stream, from the
> origins in the backend's CORS_ORIGINS setting (dev default: localhost 5173,
> 3000, 3001)

That is not true of the deployment we talk to. Verified twice, from the browser
and from curl, against `https://vivid.tsionark.io` (which reports
`env: "production"`):

```js
await fetch('https://vivid.tsionark.io/v1/health')
// TypeError: Failed to fetch          (origin http://localhost:3001)
```

```
GET /v1/health   Origin: http://localhost:3001
  -> 200, access-control-allow-credentials: true
         access-control-expose-headers: X-Request-Id
     (still no access-control-allow-origin)
```

The dev default presumably applies to a dev deployment; production has its own
`CORS_ORIGINS` and we are not in it. So every call still goes through our
same-origin relay, including the 25-minute chat stream — which the guide now
explicitly warns against doing on a serverless host.

**This is now blocking a real deploy, not theoretical.** Vercel refuses the
build outright:

```
Builder returned invalid maxDuration value for Serverless Function
"api/vivid/[...path]". Serverless Functions must have a maxDuration
between 1 and 300 for plan hobby.
```

300s is five minutes against a first build of 15-25. Pro raises it to 800s,
which is still short. There is no number that makes relaying a build turn
through a serverless function work — the ceiling is below the floor.

We have made it survivable rather than correct: the turn belongs to you, not to
the connection, so when the function is cut we reattach with
`GET /chat/stream`, which is exactly what that endpoint is for and it does the
job well. But every first build on a deployed instance now takes at least three
reconnects, each one a fresh function invocation replaying the stream from the
beginning, for a turn that would need none of it if the browser could talk to
you directly.

**Ask:** add our production origin to `CORS_ORIGINS`. The exact change, the
JSON-parsing trap in `app.env`, and how to verify it landed are written up on
their own in `BACKEND-CORS-FIX.md` next to this file. It is one config line and
it removes the function from the path entirely. Failing that, please say plainly
in the guide that the direct-from-browser path is dev-only — as written, a
client reading that paragraph would delete its relay and break.

---

### 2. `GET /keys` returns revoked keys  ·  bug, small

Revocation itself works — this is only about the list. Verified end to end by
creating a key, using it, revoking it, and using it again:

| step | result |
|---|---|
| key on `GET /builder/projects` before revoke | **200** |
| `DELETE /keys/{id}` | **204** |
| same key on `GET /builder/projects` after revoke | **401** ✓ |
| key still in `GET /keys` | **yes** ✗ |

So the key is properly dead, but it keeps appearing in the list. A user who
clicks Revoke and sees the row still there concludes that revoking failed — the
worst possible misreading for a credential.

The rows do carry a `revoked_at` timestamp, which is **not in the guide**. We
now filter on it.

**Ask:** either omit revoked keys from `GET /keys`, or document `revoked_at`
(and ideally both — a `?include_revoked=1` for anyone who wants the audit
trail).

---

### 3. `POST /builder/projects/{id}/publish` is implicit  ·  question, not a bug

A project that has only ever been planned already has a `published_url`, and
the URL serves a real page. We never called `/publish` on it. That makes
`published_url` unusable as "this project is live", which is what a project card
naturally wants to show — ours briefly badged an unbuilt project as "Live".

**Ask:** confirm whether `published_url` is reserved at creation or populated on
first build. If it is reserved, a separate `published_at` (or reusing
`turn_status`-style honesty) would let a client tell "has a URL" from "is live".

---

## Fixed since the last round — thank you

Every one of these is confirmed working against production unless noted.

| was | now |
|---|---|
| **Turn state was unknowable.** A turn that ended without persisting a message pinned our "Still working on this" banner up forever, with no way to clear it. | `Project.turn_status` and `turn_started_at`. We deleted the whole polling-and-inference workaround and the banner is now driven by the real flag, with "building for 6 minutes" from the timestamp. |
| **No way to rejoin a running turn.** Reloading mid-build lost 20 minutes of live activity. | `GET /chat/stream` replays then follows, and answers 204 when nothing is running — which is exactly the contract the AI SDK's `reconnectToStream` expects, so it was a two-line wiring change. |
| **`data-usage.reason` had no closed set.** We guessed, and mislabelled `asked` and `spec_written` — the two commonest *successful* plan endings — as failures, directly beneath the question card that had just worked. | `ok: boolean` plus a documented closed set. We branch on `ok` and no longer have to guess. `no_changes` also replaces a heuristic we had built to catch a build turn that wrote nothing. |
| **Malformed tool arguments were swallowed**, and a turn built on a file that was never written. | `failed_tools` names them, and the backend retries each one. We now tell the user *which file* is missing. |
| **Binary files came back as a UTF-8 decode** — thousands of replacement characters where a JPEG should be. | `{binary, content_base64, content_type}` and `?raw=1`. We deleted our extension-guessing module and the assets cross-reference it needed. |
| **No `Project.thumbnail_url`.** Project cards were seeded gradients. | Real desktop screenshots on the cards. |
| **`POST /keys` was referenced but never specified**, so the API-keys page was a placeholder. | Fully specified; the page is real. (See open issue 2 for the one remaining wrinkle.) |
| **`/auth/refresh` and a stale bearer.** We sent the expired access token alongside the refresh token and sessions silently died at the 30-minute mark. | Documented: send no `Authorization`, and a 401 from that route carries `refresh_expired`. Matches what we had already worked out the hard way. |
| **Truncated project names** like "A delivery tracking page for a", because the client had to invent one at creation. | Create with no name and the plan fills in the app's own, with the published slug following it. |
| **No endpoint index**, which is why we shipped without Google Maps and without the full-stack toggle despite wiring everything else. | There is one now, and it is the first thing in the file. This was the single most useful change for us. |
| **Wire-versus-folded part names** were mixed in §3, and `POST /build` read as though it started a turn. | Both called out explicitly. |
| **`vivid:error` snippet had no origin check** — any page could post a fake error and get its text into a chat turn. | The check is in the snippet. |

Also new and welcome, not previously asked for: visitor analytics
(`GET /analytics`, with the reporter injected at publish time rather than sitting
in the source), and `motion` in the skills list.

---

## Small notes

- **`POST /connectors` errors are excellent.** A deliberately bad Google Maps key
  came back `422 invalid_request` carrying Google's own sentence — *"Google
  rejected the key: The provided API key is invalid."* We show it verbatim. More
  endpoints answering like this would be welcome.
- **`current_snapshot_id` was `null`** on a project that had built and published
  (`48077a0a-3ead-4905-aab0-d61fa2d9bb58`). We do not rely on the field; flagging
  in case something else does.
- **Supabase OAuth is still off** on this deployment (`supabase_oauth: false`), so
  `GET /connectors/supabase/authorize` answers `503 not_configured`. The pasted
  personal-access-token fallback works and is what our UI leads with. Only worth
  mentioning in case the OAuth app was meant to be live here.
