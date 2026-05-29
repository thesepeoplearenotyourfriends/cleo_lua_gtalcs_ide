#!/usr/bin/env bash
set -euo pipefail

# Scan local UI assets for network-capable APIs or remote URL references.
# This is intentionally noisy: review hits before cutting a release.
rg -n -I --with-filename --max-columns=240 "https?://|wss?://|fetch\(|XMLHttpRequest|sendBeacon|new WebSocket|importScripts|createElement\(['\"]script" \
  index.html js css
