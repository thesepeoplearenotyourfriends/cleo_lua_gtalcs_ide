#!/usr/bin/env bash
set -euo pipefail

BASE="${1:-http://127.0.0.1:5111}"
ORIGIN="$BASE"

echo "Security smoke test target: $BASE"

expect_status() {
  local expected="$1"
  local label="$2"
  shift 2

  local code
  code="$(curl -sS -o /dev/null -w "%{http_code}" "$@")"
  if [[ "$code" != "$expected" ]]; then
    echo "FAIL: $label expected HTTP $expected, got $code" >&2
    exit 1
  fi
  echo "PASS: $label -> HTTP $code"
}

expect_status 403 "save without token is rejected" \
  -X POST "$BASE/api/save_text" \
  -H "Content-Type: application/json" \
  -d '{"filename":"x.lua","text":"hi"}'

expect_status 403 "save with wrong token is rejected" \
  -X POST "$BASE/api/save_text" \
  -H "X-App-Token: wrong" \
  -H "Content-Type: application/json" \
  -d '{"filename":"x.lua","text":"hi"}'

expect_status 403 "bad Host header is rejected" \
  "$BASE/api/status" \
  -H "Host: evil.example"

page="$(curl -fsS "$BASE/index.html")"
token="$(printf '%s' "$page" | sed -n 's/.*window\.APP_TOKEN = "\([^"]*\)";.*/\1/p' | head -n 1)"
if [[ -z "$token" ]]; then
  echo "FAIL: could not extract injected APP_TOKEN from $BASE/index.html" >&2
  exit 1
fi

echo "PASS: extracted per-run token from served index.html"

expect_status 400 "unsafe save extension is rejected" \
  -X POST "$BASE/api/save_text" \
  -H "Origin: $ORIGIN" \
  -H "X-App-Token: $token" \
  -H "Content-Type: application/json" \
  -d '{"filename":"x.sh","text":"hi"}'

expect_status 200 "tokened save with allowed extension succeeds" \
  -X POST "$BASE/api/save_text" \
  -H "Origin: $ORIGIN" \
  -H "X-App-Token: $token" \
  -H "Content-Type: application/json" \
  -d '{"filename":"security-smoke.lua","text":"thread(\"SCRIPT\")"}'

echo "Security smoke checks passed."
