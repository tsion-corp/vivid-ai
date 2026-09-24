#!/usr/bin/env bash
# Install the template's dependencies. The core Expo packages are pinned in
# package.json (the same SDK as vivid-mobile); the rest are added with
# `expo install`, which picks the version that matches the SDK, so nothing
# here is a guessed version. Run by template.py for the E2B image, and once
# by hand for the backend's local driver.
set -euo pipefail
cd "$(dirname "$0")"
npm install --no-audit --no-fund
npx expo install \
  react-dom react-native-web @expo/metro-runtime \
  expo-image @expo/vector-icons expo-linear-gradient expo-blur \
  react-native-url-polyfill @supabase/supabase-js \
  nativewind react-native-css-interop
# babel.config.js names the Expo preset (NativeWind needs its jsxImportSource).
npx expo install -- --save-dev babel-preset-expo
# NativeWind 4 compiles with Tailwind CSS 3.
npm install --no-audit --no-fund --save-dev "tailwindcss@^3.4" prettier-plugin-tailwindcss
npx tsc --noEmit
