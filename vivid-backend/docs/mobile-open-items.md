# Answers to the app team's open items

Google sign-in has its own note: [mobile-google-sign-in.md](mobile-google-sign-in.md).

## What's live

- **API (`https://vivid.tsionark.io`): up to date.** Deployed 2026-09-27 18:27 (WAT).
  `/openapi.json` and `/llms.txt` already include today's changes (for example
  `data_file` and `forget` on `/edits/delete`, and `vivid:forget`). If a check
  looks unchanged, it is probably reading a cached copy or a different host.
- **Website, `preview` branch: up to date**, including the delete-account page
  fix below.
- **Website, `main` branch (the live site): not updated since 2026-09-25.** It
  goes out when the owner approves the merge from `preview`. Until then,
  vividbuild.ai shows the old delete-account text.

## Firebase `google-services.json` (com.tsionark.vividbuild)

It hasn't been created: there is no Firebase project for the app yet. Someone
with access to the Firebase console should:

1. Create (or pick) a Firebase project and add an **Android app** with the
   package name `com.tsionark.vividbuild`.
2. Download `google-services.json` and add it to the app. In app.json:
   `"android": { "googleServicesFile": "./google-services.json" }`.
3. For push notifications on Android, Expo sends through FCM v1, which needs a
   service account key:
   1. In Firebase, go to Project settings, then Service accounts, then
      Generate new private key.
   2. Upload it with `eas credentials`: Android, then Google Service Account,
      then the key for push notifications (FCM V1).
4. Rebuild the Android app. Push tokens only work from a build that includes
   the file.

## Which Expo account

- **Previews inside Vivid's build workspaces** run the Expo dev server without
  signing in to any Expo account. No Expo token ever goes into a project's
  workspace.
- **Cloud (EAS) builds of the apps users make** run under Vivid's Expo account
  **`vivid-apps`**, unless the user has connected their own Expo account. Then
  it builds on theirs.
- **The VividBuild app itself** (com.tsionark.vividbuild) is built from the app
  team's own Expo project. Push notifications to it go through Expo's push
  service, so push tokens must come from that project. If "enhanced push
  security" is on for it, send us its access token to set on the server.

## Public /delete-account page

Fixed on `preview`; live once `main` is updated:

- **How to delete:** "In the VividBuild app, open Account, then Delete account.
  On the web, open Settings, then Privacy & security, and choose Delete your
  account under Data."
- **Kept records:** payment records are kept for 7 years, then removed. They
  no longer carry the profile or sign-in email. They do include the name and
  bank details from the identity check and withdrawals, and the BVN, stored
  encrypted. (The page used to say they weren't linked to a name, which was
  wrong.)

If the app's own delete screen or store listing repeats the old wording,
change it to match.
