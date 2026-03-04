#!/usr/bin/env python3
"""
pxart — Pixel-Art CLI tool for Windows
Claude draws, you watch in real time.

Usage:
  python pxart.py start [--size 64x64] [--fps 12] [--name NAME] [--load FILE]
  python pxart.py tui                        ← terminal UI (interactive editor)
  python pxart.py mcp [--config FILE] [--gui] [--size 64x64] [--name NAME] [--load FILE]
  python pxart.py stop
  python pxart.py status
  python pxart.py set_pixel <x> <y> <color>
  python pxart.py set_pixels '[[x,y,color],...]'
  python pxart.py fill_rect <x> <y> <w> <h> <color>
  python pxart.py draw_rect <x> <y> <w> <h> <color>
  python pxart.py line <x1> <y1> <x2> <y2> <color>
  python pxart.py fill <x> <y> <color>
  python pxart.py circle <cx> <cy> <r> <color>
  python pxart.py fill_circle <cx> <cy> <r> <color>
  python pxart.py gradient_rect <x> <y> <w> <h> <start_color> <end_color> [direction]
  python pxart.py set_background_reference <path> [opacity] [offset_x] [offset_y]
  python pxart.py clear_background_reference
  python pxart.py paste_image_region <path> <src_x> <src_y> <w> <h> <dest_x> <dest_y>
  python pxart.py capture_screenshot <path> [zoom]
  python pxart.py clear [color]
  python pxart.py get_pixel <x> <y>
  python pxart.py undo [N]
  python pxart.py redo [N]
  python pxart.py new_frame
  python pxart.py dup_frame [src_index]
  python pxart.py del_frame [index]
  python pxart.py set_active_frame <index>
  python pxart.py get_active_frame
  python pxart.py set_fps <n>
  python pxart.py resize_canvas <w> <h>
  python pxart.py export_png <path> [frame_index]
  python pxart.py export_spritesheet <path> [--columns N]
  python pxart.py export_gif <path> [--fps N]
  python pxart.py save [path]
  python pxart.py load <path>
  python pxart.py palette_add <color>
  python pxart.py palette_get
  python pxart.py palette_set '<json_array>'
  python pxart.py palette_clear
  python pxart.py help

Colors: #rgb | #rrggbb | #rrggbbaa | black | white | red | green | blue |
        yellow | orange | purple | cyan | magenta | gray | transparent | ...
"""
from __future__ import annotations
import sys
import os

# Add parent dir to path so we can import pxart package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_start(argv: list[str]) -> None:
    """Launch server + GUI together via pythonw so the window appears on screen."""
    import argparse
    import subprocess

    parser = argparse.ArgumentParser(prog="pxart start", add_help=False)
    parser.add_argument("--size", default="64x64")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--name", default="untitled")
    parser.add_argument("--load", default=None)
    args, _ = parser.parse_known_args(argv)

    this_file = os.path.abspath(__file__)

    # Find pythonw.exe (Windows GUI subsystem — opens window but no console)
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable  # fallback: python.exe works too

    # Build args for the _run subcommand (actual server+GUI, run under pythonw)
    run_args = [pythonw, this_file, "_run",
                "--size", args.size,
                "--fps", str(args.fps),
                "--name", args.name]
    if args.load:
        run_args += ["--load", args.load]

    print(f"Launching pxart window...")
    proc = subprocess.Popen(run_args)
    print(f"PID: {proc.pid}")
    print(f"Window should open now. Use other commands to draw.")
    print(f"To stop: python pxart.py stop")


def _cmd_run(argv: list[str]) -> None:
    """Internal: actually start server + GUI on main thread (called via pythonw)."""
    import argparse

    parser = argparse.ArgumentParser(prog="pxart _run", add_help=False)
    parser.add_argument("--size", default="64x64")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--name", default="untitled")
    parser.add_argument("--load", default=None)
    args, _ = parser.parse_known_args(argv)

    try:
        w_str, h_str = args.size.lower().split("x")
        width, height = int(w_str), int(h_str)
    except (ValueError, AttributeError):
        sys.exit(1)

    from server.canvas import CanvasState
    from server.daemon import start_server
    from shared import port_file

    if args.load:
        try:
            state = CanvasState.load_file(args.load)
        except Exception:
            state = CanvasState.new(name=args.name, width=width, height=height, fps=args.fps)
    else:
        state = CanvasState.new(name=args.name, width=width, height=height, fps=args.fps)

    server = start_server(state)
    actual_port = server.server_address[1]

    # GUI on main thread
    try:
        from gui.preview import PreviewWindow
        PreviewWindow(state).run()
    except Exception as exc:
        import traceback
        traceback.print_exc()
    finally:
        port_file.delete_port()
        try:
            server.shutdown()
        except Exception:
            pass


def _cmd_mcp(argv: list[str]) -> None:
    """Run MCP stdio server."""
    from pxart_mcp import main as mcp_main
    old_argv = sys.argv
    try:
        sys.argv = [old_argv[0]] + argv
        mcp_main()
    finally:
        sys.argv = old_argv


def _cmd_client(cmd: str, args: list[str]) -> None:
    """Send a command to the running daemon."""
    # Handle --frame flag
    frame_override = None
    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--frame" and i + 1 < len(args):
            try:
                frame_override = int(args[i + 1])
            except ValueError:
                print(f"Error: --frame must be an integer")
                sys.exit(1)
            i += 2
        else:
            filtered_args.append(args[i])
            i += 1

    from client.client import run_command
    exit_code = run_command(cmd, filtered_args, frame=frame_override)
    sys.exit(exit_code)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd in ("-h", "--help", "help"):
        print(__doc__)
    elif cmd == "start":
        _cmd_start(rest)
    elif cmd == "_run":
        _cmd_run(rest)
    elif cmd == "mcp":
        _cmd_mcp(rest)
    else:
        _cmd_client(cmd, rest)


if __name__ == "__main__":
    main()
