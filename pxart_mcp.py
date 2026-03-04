#!/usr/bin/env python3
"""MCP server for PixelArtMCP."""
from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from server.canvas import CanvasState
from server import commands

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency 'mcp'. Install with: pip install mcp") from exc


def _maybe_start_gui(state: CanvasState, enabled: bool) -> None:
    if not enabled:
        return

    def _run() -> None:
        from gui.preview import PreviewWindow
        PreviewWindow(state).run()

    thread = threading.Thread(target=_run, daemon=True, name="pxart-gui")
    thread.start()


def build_server(state: CanvasState) -> FastMCP:
    mcp = FastMCP("pixel-art")

    @mcp.tool(description="List all available pixel-art commands")
    def list_commands() -> list[str]:
        return sorted(commands.REGISTRY.keys())

    @mcp.tool(description="Execute a pxart command with string args. Use this for all drawing/actions.")
    def run_command(cmd: str, args: list[str], frame: int | None = None) -> dict:
        return commands.dispatch(state, cmd, args, frame_override=frame, actor="mcp")

    @mcp.tool(description="Get project status")
    def status() -> dict:
        return commands.dispatch(state, "status", [], actor="mcp")

    @mcp.tool(description="Capture screenshot of current canvas to PNG path")
    def screenshot(path: str, zoom: int = 8) -> dict:
        return commands.dispatch(state, "capture_screenshot", [path, str(zoom)], actor="mcp")

    return mcp


def _load_config(path: str | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", default="64x64")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--name", default="untitled")
    parser.add_argument("--load", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--gui", action="store_true", help="Force GUI window on")
    args = parser.parse_args()

    cfg = _load_config(args.config)

    if args.load:
        state = CanvasState.load_file(args.load)
    else:
        w, h = (int(v) for v in args.size.lower().split("x", 1))
        state = CanvasState.new(name=args.name, width=w, height=h, fps=args.fps)

    show_gui = bool(cfg.get("show_gui", False) or args.gui)
    _maybe_start_gui(state, show_gui)

    server = build_server(state)
    server.run()


if __name__ == "__main__":
    main()
