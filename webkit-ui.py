#!/usr/bin/python3
"""
CLEO Lua Editor - GTK/WebKit wrapper.

This keeps the bootstrap-webui shape:
- Flask serves the current app directory.
- WebKit2 opens index.html.
- /api/data remains available for simple fetch() round-trips.

The editor itself still saves via browser Blob downloads, so there is no
direct compiler pipeline hiding in the backend yet.
"""

import json
import os
import re
import sys
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.0")
from gi.repository import Gtk, WebKit2, GLib

from flask import Flask, request, send_from_directory, jsonify


BASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = BASE_DIR / "exports"
PORT = int(os.environ.get("CLEO_LUA_WEBUI_PORT", "5111"))

app = Flask(__name__)
web_view = None


def run_js(js_source):
    """Safely schedule WebKit JS execution from non-GTK threads."""
    def _run():
        if web_view is not None:
            web_view.run_javascript(js_source, None, None, None)
        return False

    GLib.idle_add(_run)


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def serve_file(filename):
    return send_from_directory(BASE_DIR, filename)


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({
        "ok": True,
        "app": "cleo-lua-editor",
        "port": PORT,
    })


@app.route("/api/data", methods=["GET", "POST"])
def data():
    if request.method == "GET":
        return jsonify({"message": "GET request received"})

    raw = request.data.decode("utf-8", errors="replace")
    print(f'flask received: "{raw}"')

    # Keep this intentionally boring. It is a comms smoke-test, not a compiler.
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {"event": raw}

    if payload.get("event") == "testing":
        run_js(
            """
            window.CLEO_UI_STATUS &&
            window.CLEO_UI_STATUS("Backend round-trip OK");
            """
        )

    return jsonify({"ok": True}), 201



def safe_export_name(name, fallback="script.lua"):
    """Return a safe leaf filename for app-managed exports."""
    raw = str(name or fallback).strip()
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = re.sub(r"[^A-Za-z0-9._ -]+", "_", raw).strip(" .")
    return raw or fallback


@app.route("/api/save_text", methods=["POST"])
def save_text():
    """Save editor text into a predictable local exports/ directory.

    Browser Blob downloads are unreliable in WebKitGTK unless download
    handling is wired up explicitly, so the desktop wrapper gets a boring
    local-save endpoint.
    """
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "Expected JSON body"}), 400

    filename = safe_export_name(payload.get("filename"))
    text = str(payload.get("text", ""))

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPORT_DIR / filename
    out_path.write_text(text, encoding="utf-8")

    print(f"saved export: {out_path}")
    return jsonify({
        "ok": True,
        "filename": filename,
        "path": str(out_path),
        "relative_path": f"exports/{filename}",
        "bytes": len(text.encode("utf-8")),
    })


def start_flask():
    app.run(
        use_reloader=False,
        host="127.0.0.1",
        port=PORT,
        threaded=True,
    )


def on_load_changed(view, load_event):
    if load_event == WebKit2.LoadEvent.FINISHED:
        print("Page loaded successfully.")
        run_js(
            """
            window.CLEO_UI_STATUS &&
            window.CLEO_UI_STATUS("GTK/WebKit wrapper connected");
            """
        )


def on_window_destroy(widget, data=None):
    print("Window closing...")
    Gtk.main_quit()
    os._exit(0)


def main():
    global web_view

    thread_flask = threading.Thread(target=start_flask, daemon=True)
    thread_flask.start()

    window = Gtk.Window(title="CLEO Lua Editor")
    window.set_default_size(1100, 720)

    local_cache_dir = BASE_DIR / ".cache"
    print(f"CACHE DIR SET TO: {local_cache_dir}")

    data_manager = WebKit2.WebsiteDataManager(
        base_data_directory=str(local_cache_dir)
    )
    context = WebKit2.WebContext(website_data_manager=data_manager)
    web_view = WebKit2.WebView.new_with_context(context)

    web_view.connect("load-changed", on_load_changed)
    window.connect("destroy", on_window_destroy)

    settings = web_view.get_settings()
    settings.set_property("enable-javascript", True)
    settings.set_property("enable-developer-extras", True)
    settings.set_property("enable_write_console_messages_to_stdout", True)
    settings.set_default_font_size(12)

    web_view.load_uri(f"http://127.0.0.1:{PORT}/index.html")
    window.add(web_view)
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
