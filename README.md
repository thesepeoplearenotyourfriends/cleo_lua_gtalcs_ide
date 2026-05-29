# CLEO Lua Editor WebUI

This is the `bootstrap-webui` idea shaped into a CLEO Lua authoring app.

![CLEO Lua Editor showing the Ace editor, autocomplete vocabulary, and opcode dictionary panels.](docs/screenshots/editor-main.svg)

## Why this matters

The central experiment here is not just a nice editor shell: this project can compile CLEO script outside of Sanny Builder. The current workflow is still split in two parts — write/edit in the GTK/WebKit Ace UI, then run the standalone compiler from the command line — but the compiler path is real and produces `.csi` output. A GUI "Compile" button is future wiring, not the missing core feature.

## Project tour

This repository is split into a small desktop wrapper, a browser-based editor UI, a working compile-time Lua-to-CLEO compiler path, and example data/scripts. If you are new to the project, start with these pieces:

- `webkit-ui.py` is the desktop shell. It starts a local Flask server, serves the app from this directory, opens `index.html` in a GTK/WebKit2 window, exposes simple backend health/test routes, and provides `/api/save_text` so the WebKit wrapper can save files into `exports/`.
- `index.html` is the editor application. It loads Bootstrap, jQuery, and Ace from local files, builds the toolbar/sidebar/status UI, loads opcode dictionaries, provides autocomplete/checking helpers, and falls back to browser Blob downloads when it is opened outside the GTK wrapper.
- `compiler_with_lua.py` is the standalone compiler path and the main technical payoff. It runs user `.lua` files through a compile-time Lua prelude that emits CLEO-style source lines, then the Python compiler backend parses labels, opcodes, operands, and writes `.csi` bytecode.
- `opcodes.dict.txt` is the main opcode dictionary consumed by the editor and compiler. The browser UI uses it for autocomplete/checking, while the compiler uses it to map emitted opcode names to numeric opcodes and operand definitions.
- `examples/` contains starter material: a teleport Lua example, a generated CLEO-text version, a compiled `.csi`, and a smaller sample dictionary for experimentation.
- `js/ace/`, `js/`, and `css/` contain vendored browser assets so the editor can run locally without a CDN.
- `download_ace.sh` is a helper for refreshing the local Ace files when needed.

## How the pieces fit together

1. `python3 webkit-ui.py` starts Flask on `127.0.0.1:5111` and opens a GTK/WebKit2 window.
2. WebKit loads `index.html` from the local Flask server.
3. The editor initializes Ace in Lua mode, loads local UI assets, and can load an opcode dictionary.
4. Dictionary names become autocomplete suggestions and can be checked against uppercase Lua calls or explicit `OP("...")` calls.
5. Save/export actions call the wrapper backend when available, writing files to `exports/`; outside the wrapper, the UI uses normal browser downloads.
6. Compilation works today through the separate command-line flow in `compiler_with_lua.py`; the UI just does not have a button wired to that backend yet.

## Dependencies

The imports from `json`, `os`, `re`, `sys`, `threading`, and `pathlib` are Python standard library modules. The non-stdlib runtime pieces are:

- **Flask**: third-party Python web framework used by `webkit-ui.py` to serve the local app and backend routes.
- **PyGObject / `gi`**: Python bindings for GObject-introspection libraries. This is what makes `from gi.repository import Gtk, WebKit2, GLib` work.
- **GTK 3 and WebKitGTK 2 GIR packages**: native system packages required by PyGObject at runtime.
- **Lua executable**: required only for the standalone Lua compiler frontend in `compiler_with_lua.py`.

`requirements.txt` lists the Python packages, but PyGObject/WebKitGTK are often smoother to install from your OS package manager because they depend on native libraries.

## What it does

- Opens as a GTK/WebKit desktop app with `webkit-ui.py`
- Serves `index.html` from Flask on `127.0.0.1:5111`
- Uses Ace Editor for Lua highlighting, indentation, snippets, and autocomplete
- Loads your existing `opcodes.dict.txt` / JSON dictionary in the browser
- Generates autocomplete from dictionary names
- Saves `.lua` files with browser Blob downloads
- Exports a project JSON bundle containing the current source + loaded opcode dict
- Compiles Lua-authored CLEO scripts to `.csi` through `compiler_with_lua.py`
- Keeps compilation as a command-line step for now; the editor UI does not yet have a compile button

## Install runtime deps

Debian/Ubuntu-ish system packages:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.0 python3-flask lua5.4
```

Or install the Python packages from `requirements.txt` when your system already has the native GTK/WebKit development/runtime libraries available:

```bash
python3 -m pip install -r requirements.txt
```

## Ace editor assets

The Ace files needed by the editor are already vendored in `js/ace/`, so no download is required for a normal checkout. The important files are:

```text
js/ace/ace.js
js/ace/ext-language_tools.js
js/ace/mode-lua.js
js/ace/theme-monokai.js
js/ace/theme-chrome.js
```

Refreshing Ace is optional and mostly a matter of user discretion. If you do want newer Ace files, use `download_ace.sh` or copy the matching files from an Ace release package's `src-min-noconflict/` directory.

## Run

```bash
python3 webkit-ui.py
```

For normal use, prefer the wrapper. Opening `index.html` directly is only a static UI/development preview and does not use the intended backend trust boundary.

## Compile a script

```bash
python3 compiler_with_lua.py my_script.lua opcodes.dict.txt
```

This command writes a generated CLEO-text file next to the Lua source and emits the compiled `.csi` next to the input script. The editor is currently the authoring surface, while the command-line compiler is the working compilation path.

## Release/security posture

This is a local desktop WebKit app with local filesystem/compiler capabilities. Treat the Flask backend as a private app backend for the bundled UI, not as a general-purpose web service.

- Launch the app through the wrapper with `python3 webkit-ui.py`.
- Do **not** open `index.html` directly in your everyday browser for normal use. The app is designed to run inside its local WebKit window, with a local backend and restricted navigation. Opening it in a normal browser mixes the app with browser extensions, cookies, tabs, download behavior, and other ambient web state.
- The backend binds only to `127.0.0.1`; do not change it to `0.0.0.0` for a release build.
- Privileged backend routes require a random per-run `X-App-Token`, reject non-JSON action requests, and only accept local origins.
- File writes are resolved by Python and contained inside known app folders such as `exports/`; user-provided filenames are sanitized and cannot choose arbitrary absolute or parent paths.
- The WebKit window blocks navigation away from the local app. Developer extras and the right-click context menu are disabled by default; use `python3 webkit-ui.py --dev` when you intentionally want inspector/debug behavior.
- Do not add remote scripts/CDNs or load untrusted web pages into the app window. Ace is vendored locally under `js/ace/`.
- Do not add a generic `/api/run` or pass user-provided strings to `shell=True`. Future compile/ADB actions should stay as narrow, tokened routes with known paths, explicit argument lists, timeouts, and returned stdout/stderr.

A quick network-call audit before release is useful:

```bash
rg -n "https?://|wss?://|fetch\(|XMLHttpRequest|sendBeacon|new WebSocket|importScripts|createElement\(['\"]script" index.html js css
```

## Saving files

Inside the GTK/WebKit wrapper, **Save .lua** and **Export Project** write to:

```text
exports/
```

This is intentional. WebKitGTK may not show a normal browser "Save As" dialog for
Blob downloads unless native download handling is wired into the wrapper, so the
app uses a small Flask `/api/save_text` route and writes to a predictable local
folder. If you open `index.html` directly as a static development preview,
the backend token is unavailable and save actions fall back to browser Blob download behavior.
