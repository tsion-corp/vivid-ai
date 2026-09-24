#!/usr/bin/env bash
# The sandbox's start command. E2B runs it on boot and waits for :8081.
# Metro serves the web preview (react-native-web) and Expo Go from the same
# port. Output goes to the log the builder's get_dev_server_logs tool tails.
#
# Not CI=1: Expo CLI turns file watching (and so fast refresh) off in CI.
export VIVID_SANDBOX=e2b NO_COLOR=1 FORCE_COLOR=0 EXPO_NO_TELEMETRY=1
cd /home/user/app
# The manifest must point phones at the public https host, not localhost:
# E2B exposes the port as <port>-<sandbox id>.<domain>.
if [ -n "${E2B_SANDBOX_ID:-}" ]; then
  export EXPO_PACKAGER_PROXY_URL="https://8081-${E2B_SANDBOX_ID}.${E2B_DOMAIN:-e2b.app}"
fi
exec npx expo start --port 8081 > /tmp/vivid-dev.log 2>&1
