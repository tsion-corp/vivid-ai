"use client";

import { reportRequest } from "@/lib/network";
import { getTokens, setTokens } from "./tokens";
import { ApiError, type Tokens } from "./types";

/**
 * Where the builder API is reached.
 *
 * Two modes, and the env var is the switch:
 *
 *  - **Direct** (`NEXT_PUBLIC_VIVID_API_BASE` set): the browser calls the API
 *    itself. This is the one that matters, because it takes our server out of
 *    the path of the 15-25 minute chat stream — and no serverless platform will
 *    hold a response open that long (Vercel caps it at 300s on Hobby, 800s on
 *    Pro, both under a first build).
 *  - **Relayed** (unset, the default): same-origin `/api/vivid/*`, forwarded by
 *    a route handler. Correct anywhere our origin is not on the backend's
 *    `CORS_ORIGINS` allowlist, which is every deployment until someone adds it.
 *
 * Leaving it unset is the safe default deliberately: turning this on before the
 * origin is allow-listed would fail every request in the app, where leaving it
 * off merely costs a hop. The relay maps `/api/vivid/X` onto
 * `${VIVID_API_BASE}/X`, so the paths below are identical either way and
 * nothing but this constant changes.
 *
 * Read as a static member access so Next can inline it at build time.
 */
const DIRECT_BASE = process.env.NEXT_PUBLIC_VIVID_API_BASE?.trim().replace(/\/+$/, "");

export const API = DIRECT_BASE || "/api/vivid";

/** True when a request leaves our origin. Only `/api/auth/*` never does. */
export const CALLING_API_DIRECTLY = Boolean(DIRECT_BASE);

/**
 * One refresh at a time, shared by every caller.
 *
 * Refresh tokens rotate, so two parallel 401s must not both spend the same one —
 * the second would be rejected and sign the user out mid-session.
 */
let inflight: Promise<Tokens | null> | null = null;

async function refreshOnce(): Promise<Tokens | null> {
  if (inflight) return inflight;

  inflight = (async () => {
    const current = getTokens();
    if (!current) return null;

    // No bearer. By the time this runs the access token is expired by
    // definition, and a backend that checks the header before reading the body
    // would reject the refresh on the strength of the very token it is meant to
    // replace.
    const response = await fetch(`${API}/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: current.refresh_token }),
    });

    if (!response.ok) {
      // Only the backend saying "this refresh token is no good" is grounds for
      // signing someone out. A 500, a 502 from the relay, or a dev-server
      // restart mid-request is a transient failure, and clearing the pair there
      // drops the user on the sign-in modal — mid-build, with no way back.
      if (response.status === 401 || response.status === 403) {
        setTokens(null);
        return null;
      }
      console.warn(`[auth] refresh failed with ${response.status}; keeping the session so the caller can retry`);
      return null;
    }

    const next = (await response.json()) as Tokens;
    setTokens(next);
    return next;
  })().finally(() => {
    inflight = null;
  });

  return inflight;
}

/**
 * fetch with the bearer token attached, refreshing once on a 401.
 *
 * Passed to the chat transport too, so the long SSE turn gets the same
 * treatment without a second copy of this logic. Retrying is safe: the body is
 * a string the caller (or the transport) rebuilds.
 */
export const authFetch: typeof fetch = async (input, init) => {
  const attempt = (token: string | undefined) => {
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    if (token) headers.set("authorization", `Bearer ${token}`);
    return fetch(input, { ...init, headers });
  };

  const response = await attempt(getTokens()?.access_token);
  if (response.status !== 401) return response;

  // A tab that already refreshed wins; refreshOnce re-reads storage.
  const refreshed = await refreshOnce();
  if (!refreshed) return response;
  return attempt(refreshed.access_token);
};

type ErrorBody = { error?: { code?: string; message?: string; request_id?: string | null }; detail?: string };

async function toApiError(response: Response): Promise<ApiError> {
  let body: ErrorBody = {};
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    // A non-JSON error page. The status still says enough.
  }
  const code = body.error?.code ?? String(response.status);
  const message = body.error?.message ?? body.detail ?? response.statusText ?? "Request failed.";
  return new ApiError(response.status, code, message, body.error?.request_id ?? null);
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await authFetch(`${API}${path}`, init);
  } catch (error) {
    // An abort is us cancelling, not the network failing, so it tells us
    // nothing either way.
    if ((error as Error).name === "AbortError") throw error;
    reportRequest(false);
    throw new ApiError(0, "offline", "Could not reach the builder. Check your connection.");
  }

  // Any answer at all — including a 500 — means the request got there.
  reportRequest(true);

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  get: <T>(path: string, init?: RequestInit) => send<T>(path, init),
  post: <T>(path: string, body?: unknown, init?: RequestInit) =>
    send<T>(path, { ...json(body ?? {}), ...init }),
  patch: <T>(path: string, body: unknown) => send<T>(path, { ...json(body), method: "PATCH" }),
  del: <T>(path: string) => send<T>(path, { method: "DELETE" }),
  /** multipart: the browser must set its own boundary, so no content-type here. */
  upload: <T>(path: string, form: FormData) => send<T>(path, { method: "POST", body: form }),
};
