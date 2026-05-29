# CLEO Lua Editor WebUI

This is the `bootstrap-webui` idea shaped into a CLEO Lua authoring app.

## What it does

- Opens as a GTK/WebKit desktop app with `webkit-ui.py`
- Serves `index.html` from Flask on `127.0.0.1:5111`
- Uses Ace Editor for Lua highlighting, indentation, snippets, and autocomplete
- Loads your existing `opcodes.dict.txt` / JSON dictionary in the browser
- Generates autocomplete from dictionary names
- Saves `.lua` files with browser Blob downloads
- Exports a project JSON bundle containing the current source + loaded opcode dict
- Does **not** compile `.csi` yet

## Install runtime deps

Debian/Ubuntu-ish:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.0 python3-flask
```

## Add Ace locally

Download/build Ace and put these files here:

```text
js/ace/ace.js
js/ace/ext-language_tools.js
js/ace/mode-lua.js
js/ace/theme-monokai.js
js/ace/theme-chrome.js
```

One easy way from an existing Ace checkout or release package is to copy from `src-min-noconflict/`.

## Run

```bash
python3 webkit-ui.py
```

Or just open `index.html` in a browser tab if local Ace files are present.

## Intended compiler flow

```bash
python3 compiler_with_lua.py my_script.lua opcodes.dict.txt
```

The editor is only the authoring surface. The compiler stays separate for now.


## Saving files

Inside the GTK/WebKit wrapper, **Save .lua** and **Export Project** write to:

```text
exports/
```

This is intentional. WebKitGTK may not show a normal browser "Save As" dialog for
Blob downloads unless native download handling is wired into the wrapper, so the
app uses a small Flask `/api/save_text` route and writes to a predictable local
folder. If you open `index.html` in a regular browser without the Python wrapper,
it falls back to the browser Blob download behavior.
