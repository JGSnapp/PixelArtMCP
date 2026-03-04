"""TCP server daemon for pxart."""
from __future__ import annotations
import atexit
import json
import socketserver
import threading
from typing import TYPE_CHECKING

from ..shared import port_file
from .canvas import CanvasState
from . import commands

# Shared shutdown event
_shutdown_event = threading.Event()
_server_ref: "socketserver.TCPServer | None" = None


class _Handler(socketserver.StreamRequestHandler):
    """Handles one TCP connection: read one JSON request, write one JSON response."""

    canvas_state: CanvasState  # set on server class below

    def handle(self) -> None:
        try:
            raw = self.rfile.readline()
            if not raw:
                return
            data = json.loads(raw.decode("utf-8"))
            cmd = data.get("cmd", "")
            args = data.get("args", [])
            frame_override = data.get("frame")  # None or int

            response = commands.dispatch(self.server.canvas_state, cmd, args, frame_override)

            # If stop command, signal shutdown after sending response
            if cmd == "stop":
                _shutdown_event.set()

        except (json.JSONDecodeError, Exception) as exc:
            response = {"status": "error", "code": "server_error", "message": str(exc)}

        try:
            line = json.dumps(response, ensure_ascii=False) + "\n"
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, canvas_state: CanvasState):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.canvas_state = canvas_state


def start_server(canvas_state: CanvasState) -> "_Server":
    """Create and start the TCP server on a background thread. Returns the server."""
    global _server_ref
    server = _Server(canvas_state)
    _server_ref = server

    actual_port = server.server_address[1]
    port_file.write_port(actual_port)

    def _cleanup():
        port_file.delete_port()
        try:
            server.shutdown()
        except Exception:
            pass

    atexit.register(_cleanup)

    thread = threading.Thread(target=server.serve_forever, daemon=True, name="pxart-tcp")
    thread.start()

    return server


def wait_for_shutdown(server: "_Server") -> None:
    """Block until a stop command is received, then shut down."""
    _shutdown_event.wait()
    server.shutdown()
    port_file.delete_port()
