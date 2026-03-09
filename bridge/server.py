"""HTTP server on daemon thread with main-thread dispatch via bpy.app.timers."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import bpy

from ..core.constants import BRIDGE_PORT

_server = None
_server_thread = None


class BridgeRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests and dispatches to main thread."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _send_error(self, message, status=400):
        self._send_json({"success": False, "error": message}, status)

    def _read_body(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            body = self.rfile.read(content_length)
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return None
        return {}

    def _dispatch_to_main_thread(self, fn, *args):
        """Run a function on Blender's main thread and wait for result."""
        result = {"value": None, "error": None, "done": False}
        event = threading.Event()

        def _run():
            try:
                result["value"] = fn(*args)
            except Exception as e:
                result["error"] = str(e)
            finally:
                result["done"] = True
                event.set()

        bpy.app.timers.register(_run, first_interval=0.0)
        event.wait(timeout=30)

        if not result["done"]:
            return None, "Timeout waiting for main thread"
        return result["value"], result["error"]

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # Flatten single-value params
        params = {k: v[0] if len(v) == 1 else v for k, v in params.items()}

        from .handlers import handle_get
        response, error = self._dispatch_to_main_thread(handle_get, path, params)

        if error:
            self._send_error(error, 500)
        elif response is None:
            self._send_error("Not found", 404)
        else:
            self._send_json(response)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_body()

        if body is None:
            self._send_error("Invalid JSON body")
            return

        from .handlers import handle_post
        response, error = self._dispatch_to_main_thread(handle_post, path, body)

        if error:
            self._send_error(error, 500)
        elif response is None:
            self._send_error("Not found", 404)
        else:
            self._send_json(response)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def start_server(port=None):
    """Start the HTTP bridge server."""
    global _server, _server_thread

    if _server is not None:
        return False

    if port is None:
        try:
            prefs = bpy.context.preferences.addons["BlenderTools"].preferences
            port = prefs.bridge_port
        except (KeyError, AttributeError):
            port = BRIDGE_PORT

    try:
        _server = HTTPServer(("127.0.0.1", port), BridgeRequestHandler)
    except OSError as e:
        print(f"BlenderTools Bridge: Failed to bind port {port}: {e}")
        return False

    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()
    print(f"BlenderTools Bridge: Listening on http://127.0.0.1:{port}")
    return True


def stop_server():
    """Stop the HTTP bridge server."""
    global _server, _server_thread

    if _server is not None:
        _server.shutdown()
        _server = None
        _server_thread = None
        print("BlenderTools Bridge: Server stopped")
        return True
    return False


def is_running():
    """Check if the server is running."""
    return _server is not None
