#!/usr/bin/env bash
set -euo pipefail

# Run from the project root.
# This fetches Ace's prebuilt browser bundle into js/ace/.
#
# If you already have Ace locally, copying src-min-noconflict/* into js/ace/
# is fine too.

mkdir -p js/ace
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

git clone --depth=1 https://github.com/ajaxorg/ace-builds "$tmp/ace-builds"
cp "$tmp/ace-builds/src-min-noconflict/ace.js" js/ace/
cp "$tmp/ace-builds/src-min-noconflict/ext-language_tools.js" js/ace/
cp "$tmp/ace-builds/src-min-noconflict/mode-lua.js" js/ace/
cp "$tmp/ace-builds/src-min-noconflict/theme-monokai.js" js/ace/
cp "$tmp/ace-builds/src-min-noconflict/theme-chrome.js" js/ace/

echo "Ace copied into js/ace/"
