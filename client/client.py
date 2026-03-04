"""TCP client: send one command to the pxart daemon, print result."""
from __future__ import annotations
import json
import socket
import sys

from ..shared import port_file


TIMEOUT = 5.0


def send_command(cmd: str, args: list[str], frame: int | None = None) -> dict:
    """Send a command to the daemon. Returns parsed response dict."""
    port = port_file.read_port()
    if port is None:
        print("Error: No running pxart server.")
        print("Start one with:  python pxart.py start")
        sys.exit(1)

    request = json.dumps({"cmd": cmd, "args": args, "frame": frame}, ensure_ascii=False) + "\n"

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as sock:
            sock.sendall(request.encode("utf-8"))

            # Read until newline
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk

    except ConnectionRefusedError:
        print(f"Error: Could not connect to server on port {port}.")
        print("Is 'python pxart.py start' still running?")
        sys.exit(1)
    except TimeoutError:
        print("Error: Server did not respond in time.")
        sys.exit(1)
    except OSError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    return json.loads(buf.decode("utf-8"))


def run_command(cmd: str, args: list[str], frame: int | None = None) -> int:
    """Send command, print result, return exit code (0=ok, 1=error)."""
    response = send_command(cmd, args, frame)

    if response["status"] == "ok":
        data = response.get("data") or {}
        if data:
            # Pretty-print key: value
            for k, v in data.items():
                if isinstance(v, (list, dict)):
                    print(f"{k}: {json.dumps(v)}")
                else:
                    print(f"{k}: {v}")
        else:
            print("ok")
        return 0
    else:
        code = response.get("code", "error")
        msg = response.get("message", "")
        print(f"Error [{code}]: {msg}", file=sys.stderr)
        return 1
