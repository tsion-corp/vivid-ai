# Please add the web app's origin to `CORS_ORIGINS`

**One config line.** It removes a serverless function from the path of every
chat turn, and there is no way to fix this from the frontend.

Written for whoever owns `vivid-backend`. Everything below was checked against
the live deployment and the SDK source; the "already fine" section exists so you
do not go chasing things that are not the problem.

---

## The change

**Development** — `vivid-backend/app/core/config.py`:

```diff
 CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000",
-                           "http://localhost:3001"]
+                           "http://localhost:3001", "<the deployed web origin>"]
```

**Production** — `CORS_ORIGINS` in `app.env`, which is what the live deployment
actually reads:

```
CORS_ORIGINS=["https://<the-deployed-web-origin>"]
```

Your own `deploy/README.md` already flags the trap, repeated here because it
costs a boot failure: **the value is parsed as JSON**, because pydantic-settings
treats list fields that way. `["https://app.example.com"]` starts;
`https://app.example.com` fails at boot.

Origin only — scheme and host, no trailing slash, no path.

---

## Why it matters more than it looks

The web app cannot call the API from the browser, so every request is relayed
through a same-origin route on the frontend host. That is merely wasteful for
short requests. For a chat turn it is fatal, because the turn is 15-25 minutes
and a serverless function response has a hard ceiling:

| | response cap | first build |
|---|---|---|
| Vercel Hobby | 5 min | 15-25 min |
| Vercel Pro | 13 min | 15-25 min |

There is no plan to buy: the ceiling is below the floor. Asking for more fails
the deploy outright —

```
Builder returned invalid maxDuration value for Serverless Function
"api/vivid/[...path]". Serverless Functions must have a maxDuration
between 1 and 300 for plan hobby.
```

We have made it survivable, not correct. The turn belongs to you rather than to
the connection, so when the function is cut the client reattaches with
`GET /chat/stream` — which is exactly what that endpoint is for, and it works
well. But a 20-minute build on Hobby now means roughly four severed streams and
four replays, for a turn that would need none of it if the browser could reach
you directly.

---

## What is already fine — no need to change these

Checked so the fix is genuinely one line:

- **`allow_methods=["*"]` and `allow_headers=["*"]`** in `app/main.py` already
  cover the `Authorization` header and the preflight for `POST`/`PATCH`/`DELETE`.
- **`allow_credentials=True`** is compatible with an explicit origin list. (It
  would *not* be with `"*"` — so please keep the list explicit rather than
  reaching for a wildcard.)
- **`expose_headers` needs nothing added.** This one is worth stating because it
  looks like a trap and is not: the AI SDK's `x-vercel-ai-ui-message-stream: v1`
  header is only ever *written* by its server helpers. The client transport
  reads `response.status` and `response.body` and no headers at all, so the
  browser hiding it cross-origin changes nothing. `X-Request-Id` is already
  exposed, which is the one we do read.
- **SSE itself needs no special CORS handling.** A streamed `text/event-stream`
  fetched with `fetch()` is an ordinary CORS request.

---

## How to confirm it landed

The current production response, for comparison — note what is missing:

```
GET /v1/health   Origin: http://localhost:3001
  -> 200
     access-control-allow-credentials: true
     access-control-expose-headers: X-Request-Id
     (no access-control-allow-origin)
```

After the change, the same request from an allow-listed origin should carry:

```
access-control-allow-origin: https://<the-deployed-web-origin>
```

```bash
curl -sI -H "Origin: https://<the-deployed-web-origin>" \
  https://vivid.tsionark.io/v1/health | grep -i access-control-allow-origin
```

And from the browser console on that origin, which is the test that actually
matters:

```js
await fetch('https://vivid.tsionark.io/v1/health')
// currently: TypeError: Failed to fetch
// after:     Response 200
```

---

## What happens on the frontend afterwards

Nothing breaks the moment you deploy this, and nothing improves by itself
either: the web app still routes through its relay, so it keeps working exactly
as it does now.

Taking the function out of the path is a separate, small frontend change — point
the client at the API directly when a public base URL is configured, and keep
the relay as the fallback. It is deliberately not done yet, because shipping it
before the origin is allow-listed would break every request.

**So: land this whenever suits, tell the frontend side, and the follow-up can go
out right after.**

---

The rest of the integration findings, including the ones already fixed, are in
`BACKEND-ISSUES.md` alongside this file.
