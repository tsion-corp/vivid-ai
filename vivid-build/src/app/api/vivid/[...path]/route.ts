import { vividApiBase } from "@/lib/server/env";

/**
 * Same-origin relay to the Vivid Builder API.
 *
 * The backend's CORS middleware has an origin allowlist that this app is not on
 * (verified: /v1/health answers 200 but sends no access-control-allow-origin),
 * so the browser cannot call it directly. This forwards verbatim, including the
 * 15-25 minute SSE chat stream, which must reach the client unbuffered.
 *
 * It holds no session of its own: the Authorization header is read off the
 * incoming request and passed along, so this is never an open relay.
 */

/**
 * A build turn runs 15-25 minutes; no serverless platform will hold a response
 * open that long. 300s is the ceiling Vercel's Hobby plan accepts (Pro allows
 * 800, which is still short of a first build), and asking for more fails the
 * build outright rather than degrading:
 *
 *   Builder returned invalid maxDuration value for Serverless Function
 *   "api/vivid/[...path]". Serverless Functions must have a maxDuration
 *   between 1 and 300 for plan hobby.
 *
 * So the stream *will* be cut mid-turn when deployed here. That is survivable
 * rather than fatal only because the turn belongs to the backend, not to this
 * connection: `turn_status` says it is still running and `GET /chat/stream`
 * replays and reattaches, which the client does on a stream error.
 *
 * The real fix is not a bigger number — it is this app's origin on the
 * backend's CORS allowlist, so the browser streams from the API directly and
 * no function is in the path at all. See BACKEND-ISSUES.md.
 */
export const maxDuration = 300;

/** Sent upstream. `host` and `content-length` would describe the wrong request. */
const FORWARD_REQUEST = ["authorization", "content-type", "accept"];

/**
 * Sent back down. Everything else is dropped on purpose:
 * `content-encoding` most of all — fetch has already decompressed the body, and
 * a surviving header makes the browser try to gunzip plain bytes, which kills
 * the stream with no error.
 */
const FORWARD_RESPONSE = ["content-type", "x-vercel-ai-ui-message-stream", "x-request-id"];

function errorResponse(status: number, code: string, message: string) {
  return Response.json({ error: { code, message, request_id: null }, detail: message }, { status });
}

async function forward(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;

  // The gate that stops this being an open relay. `/auth/*` is exempt because
  // those are the endpoints that exist precisely when there is no usable token:
  // the Decane exchange has none yet, and `/auth/refresh` is reached *because*
  // the access token has expired. Requiring a header there forced the client to
  // send a dead bearer alongside the refresh token, which the backend rejects —
  // so a session that had simply passed its 30-minute mark could never renew
  // itself and the user was dropped on the sign-in modal mid-build.
  const isAuthEndpoint = path[0] === "auth" && path[1] !== "me";
  if (!isAuthEndpoint && !request.headers.get("authorization")) {
    return errorResponse(401, "unauthorized", "Missing Authorization header.");
  }

  const headers = new Headers();
  for (const name of FORWARD_REQUEST) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Ask for an identity encoding so nothing in the chain has a reason to buffer
  // the stream in order to compress it.
  headers.set("accept-encoding", "identity");

  const target = `${vividApiBase()}/${path.map(encodeURIComponent).join("/")}${new URL(request.url).search}`;
  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  // A chat turn runs for up to 25 minutes and belongs to the project, not to
  // the tab that started it. Forwarding the client's abort would mean closing a
  // tab silently kills a build — cancelling is an explicit POST /cancel, and
  // nothing else should do it. Every other route still aborts with the client.
  const isTurn = path.at(-1) === "chat";

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      // Streams the request body instead of buffering it, which matters for
      // multipart asset uploads. Not in the RequestInit type yet.
      ...(hasBody ? { duplex: "half" } : {}),
      signal: isTurn ? undefined : request.signal,
      redirect: "manual",
    } as RequestInit);
  } catch (error) {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    const message = error instanceof Error ? error.message : "Upstream request failed.";
    return errorResponse(502, "upstream_unreachable", message);
  }

  const responseHeaders = new Headers();
  for (const name of FORWARD_RESPONSE) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  // `no-transform` is what stops an intermediary from re-buffering the SSE body
  // to recompress it; `x-accel-buffering` is the nginx-family equivalent.
  responseHeaders.set("cache-control", "no-cache, no-transform");
  responseHeaders.set("x-accel-buffering", "no");

  // The body is piped through untouched — never read it here, on any path,
  // including errors: one stray .json() would buffer every stream.
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export {
  forward as GET,
  forward as POST,
  forward as PATCH,
  forward as PUT,
  forward as DELETE,
};
