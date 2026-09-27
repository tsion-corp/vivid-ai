---
name: auth
description: How the app signs its users in with Decane (Google and emailed codes, no passwords) through decane-connect-kit. Applies when the project has Decane sign-in turned on.
---

# Sign-in with Decane

`VITE_DECANE_APP_ID` and `VITE_DECANE_API_KEY` are set in .env. They belong to this app
alone: its own user pool, nobody else's. Both are browser-public by design (the key is
authorised by the site's hostname, not by secrecy), so read them from `import.meta.env`
and never ask the user for them.

## Setup (once)
- `npm install decane-connect-kit@^2.29` with run_command (React 18+ peer).
- Wrap the app once, in `src/main.tsx` around the router:

      <DecaneKit config={{
        appId: import.meta.env.VITE_DECANE_APP_ID,
        mode: "social",
        theme: "auto",
        social: {
          apiKey: import.meta.env.VITE_DECANE_API_KEY,
          authMethods: ["google", "email"],
          protection: "identity",
          resumeSessionAcrossTabs: true,
        },
      }}>

  `protection: "identity"` is what makes sign-in the whole ceremony: no passkey, PIN or
  password prompt, ever. Leave it out and the first sign-in asks the user to create a
  passkey, which an app that only needs to know who someone is must not do.
  `resumeSessionAcrossTabs` keeps a user signed in when they open a second tab.
- `<DecaneKit>` renders its own modals and its own "setting up your account" overlay
  (the first sign-in takes a few seconds); never render `SocialWalletModal` or
  `WalletSelector` yourself, and do not add a second spinner for that moment.
- A route `/auth/callback` must exist in the SPA router (Google returns there; the kit
  finishes the sign-in by itself on whatever page carries the result). It shows a
  centred spinner and navigates to `/` (or the page the user came from, kept in
  sessionStorage) once `isConnected` is true.

## The hooks
This is all of the kit an app needs: use it as written here, without reading the package's
type definitions or source.
- `useSocialAuth()`: `isConnected`, `isNewUser`, `profile` (`{name?, email?, picture?}`,
  often absent: email sign-in never has a name, and after a reload it is null),
  `sessionExpiresAt`, `needsReconnect`, `phase` (`"creating" | "unlocking" | null`),
  `error`, `clearError()`, `signInWithGoogle()`, `googleLoading`,
  `sendEmailCode(email)`, `confirmEmailCode(email, code)`, `emailLoading`,
  `disconnect()` (sign out; it revokes the session).
- `useSocialWallet().getAccessToken()`: the Decane JWT, for calls to the app's backend.
  Call it for every request rather than storing it: the kit renews it.
- Put them behind one `src/auth/` module like any app: `AuthProvider` (wraps the kit's
  state, caches `profile` in localStorage at sign-in because Decane never returns it
  later), `useAuth()` → `{ user, profile, signedIn, signOut }`, `RequireAuth`.
- The stable identity is the token's `uid` claim (Decane's user id, a UUID); decode the
  JWT payload (base64url, no library) in `AuthProvider` and expose it as `user.id`. Key
  everything a user owns on it, never on an email. `isNewUser` is true only on a
  person's first sign-in: use it for a welcome step, not to create rows (create on
  first write, keyed on `uid`).

## The sign-in screen
- One page, `/sign-in`, and the same form in a dialog when sign-in is asked for mid-flow
  ("Sign in to save this"). "Continue with Google", then an email field that sends a
  6-digit code and a second step with the code input, a resend link (30 s cooldown) and
  "Use a different email". No password fields anywhere, no sign-up page: the first
  sign-in creates the account.
- Loading states on each button; errors in plain words, never the raw error: a wrong
  code is "That code is wrong or has expired"; `WALLET_ENROLMENT_FAILED` or
  `PROVISIONING_RATE_LIMITED` is "Sign-in didn't finish. Please try again in a moment."
- Guests browse freely; sign-in is asked for at the moment it is needed.
- Sessions renew themselves while the user is around: a token lasts eight hours, the kit
  renews it before it runs out, and after seven days the user signs in again. When the
  kit ends a session (`needsReconnect` true, or `isConnected` goes false without the
  user signing out), show "You were signed out. Sign in again to continue." and keep the
  user on the page they were on.
- A user signing in from a new browser gets a short "new sign-in to <app>" email from
  Decane. That is expected; do not mention it in the UI.

## Other sign-in methods
Only when the user asks for them. Add the method to `authMethods` and use its pair:
- Phone: `"phone"`, `sendPhoneCode(phone)` / `confirmPhoneCode(phone, code)` and
  `phoneLoading`, the same two-step form as email. Numbers are E.164 (`+234…`).
- X: `"x"`, `signInWithX()` and `xLoading`. It returns through `/auth/callback` like
  Google and has the same one-host rule (see below). X gives no email; the profile has a
  `username` instead.

## Identity only
- No wallet UI, no balances, no addresses, no "recovery file" copy unless the user asked
  for wallets or crypto. Ignore `addresses` and `hasShare`.
- If the user does ask for a wallet that moves money, drop `protection: "identity"` for
  that app and call `useSocialWallet().protectDevice()` before the first transaction, so
  the passkey is asked at that moment rather than at sign-in. Passkeys are bound to the
  hostname: never promise that a passkey made on the preview works on the published site.

## With a Supabase backend
This rule wins over the app-logic skill's "Supabase auth only": Decane is the identity,
Supabase stays the data. So:
- No Supabase auth calls, no `auth.users`, no `profiles` trigger. A `profiles` table is
  keyed by `decane_user_id text primary key` with `full_name`, `email`, `role`.
- Every row a user owns carries `decane_user_id`. Tables users write have RLS on and no
  anon write policies; public reads (products, services) keep anon select policies.
- Writes and private reads go through one edge function (`api`) that takes
  `Authorization: Bearer <getAccessToken()>`, verifies it with `jose`
  (`createRemoteJWKSet(new URL("https://backend.decane.app/.well-known/jwks.json"))`,
  `jwtVerify` with `algorithms: ["ES256"]`), then refuses unless `payload.project_id`
  equals the app id (set as the function secret `DECANE_APP_ID`) and `payload.scope` is
  absent (a scoped token is a server-to-server credential, never a user's session). It
  then acts with the service role, always filtering on `decane_user_id = payload.uid`.
  Admin checks read `profiles.role` inside the function.
- The first admin: the function's `claim-admin` action makes the caller admin only when
  no admin exists yet; `/admin` offers it once, signed in, with one line saying so.

## Without a backend
Sign-in gates screens and personalises ("Welcome back, Ada"); nothing is stored
server-side. Per-user data that must survive belongs in a backend, so say so in the final
reply rather than faking it in localStorage.

## Errors that are not bugs
`ORIGIN_NOT_ALLOWED` (or a 403) from Decane in the preview means this host is not on the
key yet; Vivid adds it when the workspace starts. Do not change code for it. Google (and
X) sign-in returns to one host at a time (the preview while building, the published site
after publishing); email and phone codes work on both.

## Final reply
Say sign-in is live on the published site once it is published, that users sign in with
Google or an emailed code, and that they are this app's own users.
