# vivid-expo

The app template the builder starts every **mobile** project from: Expo SDK 57
(React Native 0.86), Expo Router (tabs), TypeScript, NativeWind 4 (Tailwind
classes through `className`), react-native-web for the browser preview, and a
Supabase client (`lib/supabase.ts`) that keeps its session in AsyncStorage.

Metro runs on port 8081 and serves both previews:
- the web preview at `https://<host>/` (the builder's phone-framed iframe);
- Expo Go at `exps://<host>` (the QR code). `start.sh` sets
  `EXPO_PACKAGER_PROXY_URL` to the public E2B host so the manifest points phones
  there instead of at localhost.

The web preview's HTML is `public/index.html` (Expo's single-page template); the
builder keeps its click-to-edit script there between `vivid:editor` markers.

Files:
- `template.py` builds the E2B template (`E2B_API_KEY=... python template.py`).
- `setup.sh` installs dependencies: the core packages are pinned in
  package.json, the rest are added with `npx expo install` so their versions
  match the SDK. For the backend's local sandbox driver, run it here once; the
  driver copies this directory, node_modules included, per project.
- `start.sh` is what the sandbox runs on boot. It must not set `CI=1`: Expo CLI
  turns file watching off in CI, and the preview would stop updating.
- `eas.json` has the build profiles the builder uses: `preview` (Android APK,
  iOS simulator), `device` (Android APK) and `production` (store builds).
- `scripts/screenshot.mjs` captures `iphone.jpg` (390pt) and `android.jpg`
  (412dp) for the design critique.

Generated apps may use only what Expo Go ships (Expo SDK modules and pure
JavaScript packages); the builder refuses other native modules.
