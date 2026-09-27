# Google sign-in on mobile (vividbuild://auth)

Google sign-in on the app should come back to the app, not to the website. Our
backend asks Decane for the Google consent URL. Decane then chooses which of its
registered callbacks to return to, based on the `Origin` of the request. The
web sends its own host as the origin. The app has to send its own too.

No backend change is needed: `GET /v1/auth/google/start` already forwards
`Origin` (or `Referer`) to Decane unchanged.

## 1. Decane dashboard (once)

On Vivid's Decane key (App ID `70cad8bc-c917-49b2-9253-b1777d41dab3`), add
`vividbuild://auth` as a callback URL.

- **Keep the web callbacks.** The web keeps using them.
- **Order doesn't matter if Decane matches the app's origin.** A request with
  no match falls back to the *first* callback. If a test sign-in lands on the
  website instead of the app, move `vividbuild://auth` to the top.
- **The URL may be refused.** If the dashboard rejects a custom-scheme
  callback, tell us. The workaround is an `https://` page on our site that
  forwards to `vividbuild://auth`.

## 2. The app

The app scheme must be `vividbuild` (`"scheme": "vividbuild"` in app.json).

```ts
import * as WebBrowser from "expo-web-browser";

const REDIRECT = "vividbuild://auth";

export async function signInWithGoogle() {
  // 1. Ask our API for the consent URL, sending the app's own origin.
  //    This has to be fetch: the app can't set headers on a URL opened in a browser.
  const start = await fetch(`${API}/v1/auth/google/start`, {
    headers: { Origin: REDIRECT },
  });
  if (!start.ok) throw await apiError(start);              // 503 not_configured, 502 sign_in_unavailable
  const { url } = await start.json();

  // 2. Google's consent screen, in an auth session that ends at our scheme.
  const result = await WebBrowser.openAuthSessionAsync(url, REDIRECT);
  if (result.type !== "success") return null;              // cancelled or dismissed

  // 3. What Decane put on the callback URL. Depending on Decane, the fields
  //    may be in the query or the fragment, so read both.
  const back = new URL(result.url);
  const params = new URLSearchParams(back.search || back.hash.replace(/^#/, ""));
  const failure = params.get("decane_error");
  const jwt = params.get("decane_jwt");
  if (failure || !jwt) throw new Error(failure ?? "Google sign-in did not finish.");

  // 4. Trade Decane's token for a Vivid session.
  const res = await fetch(`${API}/v1/auth/decane`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      access_token: jwt,
      // Display only, never used to find the account; send them if present.
      name: params.get("decane_name") ?? undefined,
      email: params.get("decane_email") ?? undefined,
      picture: params.get("decane_picture") ?? undefined,
    }),
  });
  if (!res.ok) throw await apiError(res);
  return res.json();   // { access_token, refresh_token, token_type, user }: store like the email-code sign-in
}
```

Notes:
- **Treat `decane_jwt` as a password.** Don't log it, and don't keep it after
  step 4.
- **The web build of the app doesn't get this.** In Expo web the browser sets
  `Origin` itself and ignores ours, so it uses the normal web sign-in.
- **`decane_is_new_user=true`** on the callback means the account was just
  created. Use it only if the app shows onboarding.

## 3. Checking it

1. Sign in with Google on a real phone (iOS and Android). The auth session
   should close and the app should be signed in.
2. Sign in with Google on the website. It should still land on the site's
   `/auth/callback`.
3. If step 1 opens the website instead, see step 1 of the dashboard section.
