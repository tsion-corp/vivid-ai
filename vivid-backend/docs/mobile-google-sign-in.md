# Google sign-in on mobile (vividbuild://auth)

Two parts: **Part 1** makes Google sign-in return to the app. **Part 2**
(new) joins Google and emailed-code sign-ins for the same person into one
account. Each part stands on its own.

---

# Part 1: Google sign-in returns to the app

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

---
---

# Part 2: One account for Google and the emailed code (new)

**The problem.** Decane gives each sign-in method its own user id, so signing
in with Google and with an emailed code using the same address made two
separate Vivid accounts. The backend now links them. The app needs two
things: a code step during Google sign-in, and a "Sign-in methods" section in
the account screen.

## Why this can't affect anyone else

Linking only ever joins one person's own accounts, and only when that person
proves it:

- **An email the app sends never finds an account.** The Google email reaches
  us through the app or browser and could be typed by anyone, so on its own it
  opens nothing. Only an address proved with an emailed code counts.
- **Joining at sign-in needs the code sent to that address.** A Google
  sign-in that claims someone else's address gets no session. It gets the
  code screen, and the code goes to the real owner's inbox. Without it, the
  only way forward is "Keep a separate account".
- **Merging in settings needs both sign-ins.** You must be signed in to one
  account and complete the other sign-in yourself. Nobody can pull another
  person's account into theirs.
- **Nothing happens automatically to existing accounts.** Accounts that are
  already split stay as they are until their owner connects them. Every
  sign-in with no match works exactly as before.
- **Other people keep what they had.** People a merged project was shared
  with keep their access; the project just moves to the merged account.
- **No money is lost.** A wallet balance is moved with a matching entry on
  both accounts. Accounts with a paid plan or Vivid Pay are never merged:
  that answers `merge_blocked` and changes nothing.

## A. Code step during Google sign-in

Sometimes a Google sign-in claims an address that someone already proved with
an emailed code. Then `POST /v1/auth/decane` answers **409 `link_required`**
instead of a session, and a code has gone to that address:

```json
{"error": {"code": "link_required",
           "message": "You already have a Vivid account with te***@gmail.com. Enter the code we emailed there to use Google with it.",
           "details": {"link_token": "…", "email": "te***@gmail.com", "code_sent": true,
                       "options": ["confirm", "resend", "separate"]}}}
```

Show a screen with the message, a 6-digit code field, and two smaller
actions, "Send another code" and "Keep a separate account":

| Action | Call | Answer |
|---|---|---|
| Enter the code | `POST /v1/auth/link/confirm {link_token, code}` | the usual token pair, for the existing account. Google opens it from then on. |
| Send another code | `POST /v1/auth/link/resend {link_token}` | 202 |
| Keep a separate account | `POST /v1/auth/link/separate {link_token}` | a token pair for a new, separate account |

Errors to handle:
- **400 `invalid_code`:** wrong or expired code. Let them retry.
- **429 `code_just_sent` / `too_many_codes`:** a code went out moments ago, or
  too many this hour.
- **410 `link_expired`:** after 15 minutes. Start Google sign-in again.

```ts
// In signInWithGoogle(), step 4, before `if (!res.ok) throw ...`:
if (res.status === 409) {
  const { error } = await res.json();
  if (error.code === "link_required") {
    return { linkRequired: true, linkToken: error.details.link_token, email: error.details.email };
  }
}

export const confirmLink = (linkToken: string, code: string) =>
  post("/v1/auth/link/confirm", { link_token: linkToken, code });   // -> token pair
export const resendLinkCode = (linkToken: string) =>
  post("/v1/auth/link/resend", { link_token: linkToken });
export const keepSeparate = (linkToken: string) =>
  post("/v1/auth/link/separate", { link_token: linkToken });        // -> token pair
```

## B. "Sign-in methods" in the account screen

This is for people who already have two accounts, and for adding a second
way in. All calls need the signed-in bearer token.

- **List:** `GET /v1/auth/me/identities` returns `{methods: [{method: "email" | "google" | "other", email, created_at}]}`.
  `"other"` is a sign-in from before methods were recorded; show it as "Your
  first sign-in".
- **Connect an email:**
  1. `POST /v1/auth/me/identities/email/start {email}` returns 202. A code
     goes to that address.
  2. `POST /v1/auth/me/identities/email {email, code}` returns `{methods, merged}`.
- **Connect Google:** run the same Google flow as Part 1 while signed in.
  Then, instead of `/v1/auth/decane`, send the `decane_jwt` to
  `POST /v1/auth/me/identities/google {access_token: decane_jwt}`. That
  returns `{methods, merged}`.

If the connected method already had its own Vivid account, that account is
folded into this one: its projects, shares, messages, gifts, chats, API keys,
devices, wallet balance and extra credits move over, and the other account is
closed. `merged` says what moved, as `{projects, wallet_micro?}`. Show
"Connected. 2 projects moved over from the other account."

**409 `merge_blocked`** means that account has a paid plan (`paid_plan`) or
uses Vivid Pay (`vivid_pay`). `error.details.blockers` is a list of
`{code, message}`. Show the message; nothing was changed.

## C. Checking Part 2

1. On a fresh test address: sign in with an emailed code, sign out, then sign
   in with Google on the same address. The code screen appears. Enter the
   code, and you're in the same account (same projects).
2. With two existing accounts: sign in to one, then use "Connect Google" in
   the account screen with the other. Its projects appear in this account.
