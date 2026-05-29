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

import hmac
import json
import os
import secrets
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.0")
from gi.repository import Gtk, WebKit2, GLib

from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = BASE_DIR / "exports"
PORT = int(os.environ.get("CLEO_LUA_WEBUI_PORT", "5111"))
APP_TOKEN = secrets.token_urlsafe(32)
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
ALLOWED_NAV_HOSTS = {"127.0.0.1", "localhost"}
DEV_MODE = "--dev" in sys.argv

app = Flask(__name__)
web_view = None


def run_js(js_source):
    """Safely schedule WebKit JS execution from non-GTK threads."""
    def _run():
        if web_view is not None:
            web_view.run_javascript(js_source, None, None, None)
        return False

    GLib.idle_add(_run)


def inject_app_token(html):
    """Inject the per-run backend token into the served app page."""
    token_script = (
        "<script>"
        f"window.APP_TOKEN = {json.dumps(APP_TOKEN)};"
        "</script>"
    )
    return html.replace("</head>", f"  {token_script}\n</head>", 1)


def require_local_origin():
    """Reject state-changing requests from non-local browser origins."""
    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS:
        abort(403)


def require_token():
    """Require the random per-run token for privileged backend routes."""
    supplied = request.headers.get("X-App-Token", "")
    if not hmac.compare_digest(supplied, APP_TOKEN):
        abort(403)


def require_json():
    """Require JSON for action routes before reading request payloads."""
    if not request.is_json:
        abort(415)


def require_privileged_json_request():
    require_local_origin()
    require_token()
    require_json()


@app.route("/")
def index():
    return serve_index()


@app.route("/index.html")
def serve_index():
    html = (BASE_DIR / "index.html").read_text(encoding="utf-8")
    return inject_app_token(html)


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

    require_privileged_json_request()
    payload = request.get_json() or {}
    print(f"flask received event: {payload.get('event', '')}")

    # Keep this intentionally boring. It is a comms smoke-test, not a compiler.
    if payload.get("event") == "testing":
        run_js(
            """
            window.CLEO_UI_STATUS &&
            window.CLEO_UI_STATUS("Backend round-trip OK");
            """
        )

    return jsonify({"ok": True}), 201



def safe_export_path(name, fallback="script.lua"):
    """Return a contained path inside exports/ for app-managed writes."""
    raw = str(name or fallback).replace("\\", "/").split("/")[-1]
    filename = secure_filename(raw) or fallback
    if filename in {".", ".."}:
        abort(400)

    base = EXPORT_DIR.resolve()
    path = (base / filename).resolve()
    if base != path and base not in path.parents:
        abort(400)
    return path


@app.route("/api/save_text", methods=["POST"])
def save_text():
    """Save editor text into a predictable local exports/ directory.

    Browser Blob downloads are unreliable in WebKitGTK unless download
    handling is wired up explicitly, so the desktop wrapper gets a boring
    local-save endpoint.
    """
    require_privileged_json_request()
    payload = request.get_json() or {}

    out_path = safe_export_path(payload.get("filename"))
    filename = out_path.name
    text = str(payload.get("text", ""))

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
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
        threaded=False,
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


def on_context_menu(view, context_menu, event, hit_test_result):
    """Disable the right-click context menu unless dev mode is requested."""
    return not DEV_MODE


def is_allowed_navigation(uri):
    parsed = urlparse(uri)
    if parsed.scheme == "http":
        return parsed.hostname in ALLOWED_NAV_HOSTS and parsed.port == PORT
    if parsed.scheme == "blob":
        return uri.startswith(tuple(f"blob:{origin}" for origin in ALLOWED_ORIGINS))
    if parsed.scheme == "about" and uri == "about:blank":
        return True
    return False


def on_decide_policy(view, decision, decision_type):
    """Keep the app window from navigating away from the local UI."""
    if decision_type != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
        return False

    action = decision.get_navigation_action()
    uri = action.get_request().get_uri()
    if is_allowed_navigation(uri):
        return False

    print(f"BLOCKED NAVIGATION: {uri}")
    decision.ignore()
    return True


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
    web_view.connect("context-menu", on_context_menu)
    web_view.connect("decide-policy", on_decide_policy)
    window.connect("destroy", on_window_destroy)

    settings = web_view.get_settings()
    settings.set_property("enable-javascript", True)
    settings.set_property("enable-plugins", False)
    settings.set_property("enable-developer-extras", DEV_MODE)
    settings.set_property("enable_write_console_messages_to_stdout", DEV_MODE)
    settings.set_default_font_size(12)

    web_view.load_uri(f"http://127.0.0.1:{PORT}/index.html")
    window.add(web_view)
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
