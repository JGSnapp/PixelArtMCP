#!/usr/bin/env python3
"""
pxart TUI — Terminal pixel-art editor.
Works alongside the pxart server (start server first with pxart.py start).
Edits are reflected live in the GUI window.

Controls:
  WASD / Arrow keys  Move cursor
  Space / Enter      Paint pixel
  1-9                Select palette color
  f                  Toggle fill tool
  e                  Erase (transparent)
  u                  Undo
  r                  Redo
  n                  New frame
  Tab                Next frame
  Shift+Tab          Prev frame
  +/-                Zoom in/out (viewport scale)
  q / Esc            Quit

Run: python pxart_tui.py
"""
from __future__ import annotations
import sys
import os
import json
import socket
import queue
import threading
import time
import ctypes
import struct
from dataclasses import dataclass, field
from typing import Any

# ── Add project root to path ─────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pxart.shared.color import PixelColor, parse_color, TRANSPARENT
from pxart.shared.port_file import read_port

# ── Constants ────────────────────────────────────────────────────────
PIXEL_WIDTH   = 2          # terminal columns per canvas pixel
PALETTE_WIDTH = 22         # right panel columns
BOTTOM_ROWS   = 3          # frame strip + status + hints

DEFAULT_PALETTE: list[str] = [
    "#000000", "#ffffff", "#ff0000", "#00c800", "#0000ff",
    "#ffff00", "#ff8c00", "#800080", "#00ffff", "#ff00ff",
    "#808080", "#c0c0c0", "#5c3317", "#1a237e", "#e3000b",
    "#0033a0", "#e8c49a", "#4a2800", "#b8d4b8", "#c8e0c8",
    "#cc0000", "#2d4a7c", "#1a1a2e", "#3a5a8c", "#c0392b",
    "#2ecc71", "#e74c3c", "#3498db", "#f39c12", "#9b59b6",
    "#1abc9c", "#34495e",
]

# ── Windows VT + Console ─────────────────────────────────────────────
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
STD_OUTPUT_HANDLE = -11
STD_INPUT_HANDLE  = -10


def _enable_vt_mode() -> None:
    k32 = ctypes.windll.kernel32
    h = k32.GetStdHandle(STD_OUTPUT_HANDLE)
    mode = ctypes.c_ulong()
    k32.GetConsoleMode(h, ctypes.byref(mode))
    k32.SetConsoleMode(h, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    # Also set input mode for reading raw keys
    hi = k32.GetStdHandle(STD_INPUT_HANDLE)
    mi = ctypes.c_ulong()
    k32.GetConsoleMode(hi, ctypes.byref(mi))
    # Disable line input, echo
    ENABLE_PROCESSED_INPUT = 0x0001
    k32.SetConsoleMode(hi, mi.value & ~(0x0002 | 0x0004))  # remove ECHO + LINE


def _get_terminal_size() -> tuple[int, int]:
    """Returns (cols, rows) via Windows API."""
    k32 = ctypes.windll.kernel32
    h = k32.GetStdHandle(STD_OUTPUT_HANDLE)
    buf = ctypes.create_string_buffer(22)
    if k32.GetConsoleScreenBufferInfo(h, buf):
        left, top, right, bottom = struct.unpack_from("hhhh", buf, 10)
        return max(40, right - left + 1), max(10, bottom - top + 1)
    return 80, 24


def _read_key() -> str:
    """Read one keypress using msvcrt. Returns a string key name."""
    import msvcrt
    ch = msvcrt.getwch()
    if ch in ('\x00', '\xe0'):
        ch2 = msvcrt.getwch()
        return {
            'H': 'UP', 'P': 'DOWN', 'K': 'LEFT', 'M': 'RIGHT',
            'G': 'HOME', 'O': 'END',
            'I': 'PAGEUP', 'Q': 'PAGEDOWN',
            '\x0f': 'SHIFT_TAB',  # Shift+Tab extended
        }.get(ch2, f'EXT_{ord(ch2)}')
    if ch == '\x1b':
        return 'ESC'
    if ch == '\t':
        return 'TAB'
    if ch == '\r':
        return 'ENTER'
    if ch == ' ':
        return 'SPACE'
    if ch == '\x08':
        return 'BACKSPACE'
    return ch


# ── State ────────────────────────────────────────────────────────────
@dataclass
class EditorState:
    canvas: list[list[list[PixelColor]]]   # canvas[frame][y][x]
    canvas_w: int
    canvas_h: int
    frame_count: int
    active_frame: int = 0

    cursor_x: int = 0
    cursor_y: int = 0
    view_x: int = 0
    view_y: int = 0

    palette: list[PixelColor] = field(default_factory=list)
    palette_idx: int = 0

    tool: str = "pencil"   # "pencil" | "fill" | "erase"

    term_cols: int = 80
    term_rows: int = 24
    dirty: bool = True

    connected: bool = False
    server_port: int | None = None
    project_name: str = "untitled"

    status_msg: str = ""
    status_timer: float = 0.0

    cmd_queue: queue.Queue = field(default_factory=queue.Queue)

    # Incremental rendering: set of (x,y) changed this cycle
    changed_cells: set[tuple[int, int]] = field(default_factory=set)
    full_redraw_needed: bool = True


# ── TCP helpers ──────────────────────────────────────────────────────

def _tcp_send(port: int, cmd: str, args: list[str], frame: int | None = None) -> dict | None:
    try:
        req = json.dumps({"cmd": cmd, "args": args, "frame": frame}) + "\n"
        with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
            s.sendall(req.encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf)
    except Exception:
        return None


def _tcp_worker(state: EditorState) -> None:
    """Background thread: send queued commands to server."""
    while True:
        try:
            item = state.cmd_queue.get(timeout=1.0)
        except queue.Empty:
            # Reconnect attempt if disconnected
            if not state.connected and state.server_port:
                r = _tcp_send(state.server_port, "status", [])
                if r and r.get("status") == "ok":
                    state.connected = True
                    state.dirty = True
            continue

        if item is None:
            break

        cmd, args, extra = item

        if cmd == "_refresh_frame":
            # Fetch all pixels of active frame from server via save/load
            _fetch_frame(state, state.active_frame)
            state.full_redraw_needed = True
            state.dirty = True
            continue

        if cmd == "_refresh_meta":
            r = _tcp_send(state.server_port, "status", [])
            if r and r.get("status") == "ok":
                d = r["data"]
                state.frame_count = d.get("frames", 1)
                state.active_frame = d.get("active_frame", 0)
                state.project_name = d.get("name", "untitled")
                state.full_redraw_needed = True
                state.dirty = True
            continue

        if not state.connected or not state.server_port:
            continue

        r = _tcp_send(state.server_port, cmd, args)
        if r is None:
            state.connected = False
            state.status_msg = "Server disconnected!"
            state.status_timer = time.time() + 3
            state.dirty = True
        elif r.get("status") != "ok" and extra.get("show_error", False):
            state.status_msg = r.get("message", "Error")
            state.status_timer = time.time() + 2
            state.dirty = True


def _fetch_frame(state: EditorState, fidx: int) -> None:
    """Fetch frame pixels from server by requesting a temp save."""
    if not state.server_port:
        return
    import tempfile, json as _json
    tmp = os.path.join(os.environ.get("TEMP", "."), "pxart_tui_sync.pxart")
    r = _tcp_send(state.server_port, "save", [tmp])
    if not r or r.get("status") != "ok":
        return
    try:
        data = _json.loads(open(tmp, encoding="utf-8").read())
        frames_data = data.get("frames", [])
        if fidx < len(frames_data):
            fd = frames_data[fidx]
            for y, row in enumerate(fd.get("pixels", [])):
                for x, hex_str in enumerate(row):
                    c = parse_color(hex_str)
                    if c and y < state.canvas_h and x < state.canvas_w:
                        # Expand canvas if needed
                        while fidx >= len(state.canvas):
                            state.canvas.append(
                                [[TRANSPARENT]*state.canvas_w for _ in range(state.canvas_h)])
                        state.canvas[fidx][y][x] = c
        # Also update metadata
        state.frame_count = len(frames_data)
        state.canvas_w = data.get("width", state.canvas_w)
        state.canvas_h = data.get("height", state.canvas_h)
        state.project_name = data.get("name", state.project_name)
        state.active_frame = data.get("active_frame_index", state.active_frame)
        # Expand canvas list
        while len(state.canvas) < state.frame_count:
            state.canvas.append(
                [[TRANSPARENT]*state.canvas_w for _ in range(state.canvas_h)])
    except Exception:
        pass


# ── ANSI helpers ─────────────────────────────────────────────────────
ESC = "\x1b"

def _goto(row: int, col: int) -> str:
    return f"{ESC}[{row};{col}H"

def _bg(r: int, g: int, b: int) -> str:
    return f"{ESC}[48;2;{r};{g};{b}m"

def _fg(r: int, g: int, b: int) -> str:
    return f"{ESC}[38;2;{r};{g};{b}m"

def _reset() -> str:
    return f"{ESC}[0m"

def _bold() -> str:
    return f"{ESC}[1m"

def _dim() -> str:
    return f"{ESC}[2m"

def _reverse() -> str:
    return f"{ESC}[7m"

def _clreol() -> str:
    return f"{ESC}[K"

def _pixel_block(px: PixelColor, is_cursor: bool) -> str:
    """Render one canvas pixel as a 2-char colored terminal cell."""
    if px.a == 0:
        # Transparent: use dim checkerboard
        c = 55
        bg = _bg(c, c, c)
    else:
        # Blend pixel over dark bg based on alpha
        a = px.a / 255
        r2 = int(px.r * a + 15 * (1 - a))
        g2 = int(px.g * a + 10 * (1 - a))
        b2 = int(px.b * a + 20 * (1 - a))
        bg = _bg(r2, g2, b2)

    if is_cursor:
        # Cursor: bright white brackets on the color
        return f"{bg}\x1b[1m\x1b[38;2;255;255;255m[]\x1b[0m"
    else:
        return f"{bg}  \x1b[0m"


# ── Rendering ────────────────────────────────────────────────────────

def render_full(state: EditorState) -> None:
    """Full redraw of the entire screen."""
    cols, rows = _get_terminal_size()
    state.term_cols = cols
    state.term_rows = rows

    vw = (cols - PALETTE_WIDTH) // PIXEL_WIDTH   # viewport width in pixels
    vh = rows - BOTTOM_ROWS - 1                   # viewport height in pixels
    vw = max(1, vw)
    vh = max(1, vh)

    frame_pixels = state.canvas[state.active_frame] if state.active_frame < len(state.canvas) else []
    buf: list[str] = [f"{ESC}[H"]   # home

    # ── Canvas rows ──────────────────────────────────────────────────
    for screen_row in range(vh):
        cy = state.view_y + screen_row
        line: list[str] = []

        for screen_col in range(vw):
            cx = state.view_x + screen_col
            is_cursor = (cx == state.cursor_x and cy == state.cursor_y)

            if cy < 0 or cy >= state.canvas_h or cx < 0 or cx >= state.canvas_w:
                # Outside canvas
                line.append(f"{_bg(12,8,20)}  ")
            elif frame_pixels:
                px = frame_pixels[cy][cx]
                line.append(_pixel_block(px, is_cursor))
            else:
                line.append(f"{_bg(20,15,30)}  ")

        # Fill remaining cols with panel bg
        canvas_end_col = vw * PIXEL_WIDTH + 1
        line.append(_reset())

        # ── Palette panel ─────────────────────────────────────────
        pal_row = screen_row  # one palette entry per 2 rows (we'll do 1 per row)
        pal_line = _render_palette_entry(state, pal_row, cols)
        line.append(f"{ESC}[{screen_row + 1};{canvas_end_col}H{pal_line}")

        buf.append(f"{ESC}[{screen_row + 1};1H{''.join(line)}")

    # ── Divider ─────────────────────────────────────────────────────
    div_row = vh + 1
    divider = f"{_bg(30,20,50)}{_fg(80,60,120)}" + "─" * cols + _reset()
    buf.append(f"{ESC}[{div_row};1H{divider}")

    # ── Frame strip ──────────────────────────────────────────────────
    buf.append(_render_frame_strip(state, vh + 2, cols))

    # ── Status bar ───────────────────────────────────────────────────
    buf.append(_render_status(state, vh + 3, cols))

    # ── Key hints ────────────────────────────────────────────────────
    buf.append(_render_hints(state, vh + 4, cols))

    sys.stdout.write("".join(buf))
    sys.stdout.flush()
    state.full_redraw_needed = False
    state.changed_cells.clear()


def render_incremental(state: EditorState) -> None:
    """Only redraw changed cells + status bar (fast update)."""
    if not state.changed_cells:
        _update_status_only(state)
        return

    cols, rows = state.term_cols, state.term_rows
    vw = (cols - PALETTE_WIDTH) // PIXEL_WIDTH
    vh = rows - BOTTOM_ROWS - 1

    frame_pixels = state.canvas[state.active_frame] if state.active_frame < len(state.canvas) else []
    buf: list[str] = []

    for (cx, cy) in state.changed_cells:
        sc = cx - state.view_x
        sr = cy - state.view_y
        if 0 <= sc < vw and 0 <= sr < vh:
            is_cursor = (cx == state.cursor_x and cy == state.cursor_y)
            term_col = sc * PIXEL_WIDTH + 1
            if frame_pixels and cy < len(frame_pixels) and cx < len(frame_pixels[cy]):
                px = frame_pixels[cy][cx]
                cell = _pixel_block(px, is_cursor)
            else:
                cell = f"{_bg(12,8,20)}  {_reset()}"
            buf.append(f"{ESC}[{sr + 1};{term_col}H{cell}{_reset()}")

    # Update old cursor position too
    buf.append(_render_hints(state, vh + 4, cols))
    _update_status_only(state)

    if buf:
        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    state.changed_cells.clear()


def _update_status_only(state: EditorState) -> None:
    cols, rows = state.term_cols, state.term_rows
    vh = rows - BOTTOM_ROWS - 1
    status = _render_status(state, vh + 3, cols)
    sys.stdout.write(status)
    sys.stdout.flush()


def _render_palette_entry(state: EditorState, row_idx: int, cols: int) -> str:
    """Render one row of the palette panel. Two entries per row."""
    panel_bg = _bg(18, 12, 30)
    reset = _reset()
    result = [panel_bg]

    i1 = row_idx * 2
    i2 = i1 + 1

    def _swatch(idx: int) -> str:
        if idx >= len(state.palette):
            return f"{panel_bg}          "
        px = state.palette[idx]
        sel = (idx == state.palette_idx)
        num = f"{idx + 1:2d}" if idx < 9 else "  "
        hex_short = f"#{px.r:02x}{px.g:02x}{px.b:02x}"

        if sel:
            color_block = f"\x1b[1m{_bg(px.r,px.g,px.b)}{_fg(255,255,255)}[**]\x1b[0m{panel_bg}"
        else:
            color_block = f"{_bg(px.r,px.g,px.b)}    \x1b[0m{panel_bg}"
        return f" {num}{color_block}"

    result.append(_swatch(i1))
    result.append(_swatch(i2))
    result.append(f"{_reset()}")
    return "".join(result)


def _render_frame_strip(state: EditorState, row: int, cols: int) -> str:
    bg = _bg(15, 10, 28)
    reset = _reset()
    parts = [f"{ESC}[{row};1H{bg}"]
    for i in range(state.frame_count):
        if i == state.active_frame:
            parts.append(f"\x1b[1m{_fg(255,220,50)}[F{i}]{_reset()}{bg}")
        else:
            parts.append(f"{_fg(100,80,160)} F{i} {_reset()}{bg}")
    parts.append(_clreol())
    parts.append(reset)
    return "".join(parts)


def _render_status(state: EditorState, row: int, cols: int) -> str:
    bg = _bg(10, 8, 22)
    pal_px = state.palette[state.palette_idx] if state.palette else PixelColor(0, 0, 0)
    color_swatch = f"{_bg(pal_px.r, pal_px.g, pal_px.b)}  {_reset()}{bg}"
    hex_str = f"#{pal_px.r:02x}{pal_px.g:02x}{pal_px.b:02x}"

    srv = f"{_fg(0,220,100)}SRV{_reset()}{bg}" if state.connected else f"{_fg(220,60,60)}OFF{_reset()}{bg}"

    tool_colors = {"pencil": (100,200,255), "fill": (255,180,50), "erase": (255,100,100)}
    tc = tool_colors.get(state.tool, (200,200,200))
    tool_str = f"{_fg(*tc)}{state.tool.upper():6s}{_reset()}{bg}"

    msg = ""
    if state.status_msg and time.time() < state.status_timer:
        msg = f"  {_fg(255,255,100)}{state.status_msg}{_reset()}{bg}"

    status = (
        f"{ESC}[{row};1H{bg}{_fg(80,160,255)}"
        f" ({state.cursor_x:3d},{state.cursor_y:3d})"
        f" {_fg(150,150,180)}|{_fg(80,160,255)} {color_swatch} {hex_str}"
        f" {_fg(150,150,180)}|{_fg(80,160,255)} {tool_str}"
        f" {_fg(150,150,180)}| {srv}"
        f" {_fg(150,150,180)}| {_fg(180,160,220)}{state.project_name}"
        f"{msg}"
        f"{_clreol()}{_reset()}"
    )
    return status


def _render_hints(state: EditorState, row: int, cols: int) -> str:
    bg = _bg(8, 6, 18)
    kc = _fg(255, 220, 80)
    tc = _fg(140, 140, 180)
    r = _reset()
    hints = (
        f"{ESC}[{row};1H{bg}{tc}"
        f"{kc}WASD{tc}/Arrows:move "
        f"{kc}Space{tc}:paint "
        f"{kc}1-9{tc}:color "
        f"{kc}f{tc}:fill "
        f"{kc}e{tc}:erase "
        f"{kc}u{tc}:undo "
        f"{kc}Tab{tc}:frame "
        f"{kc}n{tc}:+frame "
        f"{kc}q{tc}:quit"
        f"{_clreol()}{r}"
    )
    return hints


# ── Scroll ───────────────────────────────────────────────────────────

def _scroll_to_cursor(state: EditorState) -> None:
    cols, rows = state.term_cols, state.term_rows
    vw = max(1, (cols - PALETTE_WIDTH) // PIXEL_WIDTH)
    vh = max(1, rows - BOTTOM_ROWS - 1)

    if state.cursor_x < state.view_x:
        state.view_x = state.cursor_x
        state.full_redraw_needed = True
    elif state.cursor_x >= state.view_x + vw:
        state.view_x = state.cursor_x - vw + 1
        state.full_redraw_needed = True

    if state.cursor_y < state.view_y:
        state.view_y = state.cursor_y
        state.full_redraw_needed = True
    elif state.cursor_y >= state.view_y + vh:
        state.view_y = state.cursor_y - vh + 1
        state.full_redraw_needed = True


# ── Paint ────────────────────────────────────────────────────────────

def _paint(state: EditorState, x: int, y: int) -> None:
    if not (0 <= x < state.canvas_w and 0 <= y < state.canvas_h):
        return
    if state.tool == "erase":
        color = TRANSPARENT
    else:
        color = state.palette[state.palette_idx]

    # Update local buffer
    while state.active_frame >= len(state.canvas):
        state.canvas.append([[TRANSPARENT]*state.canvas_w for _ in range(state.canvas_h)])
    state.canvas[state.active_frame][y][x] = color
    state.changed_cells.add((x, y))

    # Queue TCP command
    if state.connected and state.server_port:
        state.cmd_queue.put(("set_pixel", [str(x), str(y), color.to_hex()], {}))


def _flood_fill_local(state: EditorState, x: int, y: int) -> None:
    """BFS flood fill on local canvas, then send fill command to server."""
    color = state.palette[state.palette_idx]
    frame = state.canvas[state.active_frame]
    target = frame[y][x]
    if target == color:
        return

    stack = [(x, y)]
    visited: set[tuple[int, int]] = set()
    w, h = state.canvas_w, state.canvas_h

    while stack:
        cx, cy = stack.pop()
        if (cx, cy) in visited:
            continue
        if not (0 <= cx < w and 0 <= cy < h):
            continue
        if frame[cy][cx] != target:
            continue
        visited.add((cx, cy))
        frame[cy][cx] = color
        state.changed_cells.add((cx, cy))
        stack.extend([(cx+1,cy),(cx-1,cy),(cx,cy+1),(cx,cy-1)])

    state.full_redraw_needed = True

    # Server fill
    if state.connected and state.server_port:
        state.cmd_queue.put(("fill", [str(x), str(y), color.to_hex()], {}))


# ── Input handler ────────────────────────────────────────────────────

def handle_key(key: str, state: EditorState) -> bool:
    """Process keypress. Returns False if user wants to quit."""
    old_cursor = (state.cursor_x, state.cursor_y)

    if key in ('w', 'W', 'UP'):
        state.cursor_y = max(0, state.cursor_y - 1)
    elif key in ('s', 'S', 'DOWN'):
        state.cursor_y = min(state.canvas_h - 1, state.cursor_y + 1)
    elif key in ('a', 'A', 'LEFT'):
        state.cursor_x = max(0, state.cursor_x - 1)
    elif key in ('d', 'D', 'RIGHT'):
        state.cursor_x = min(state.canvas_w - 1, state.cursor_x + 1)
    elif key == 'HOME':
        state.cursor_x = 0
    elif key == 'END':
        state.cursor_x = state.canvas_w - 1
    elif key == 'PAGEUP':
        cols, rows = state.term_cols, state.term_rows
        state.cursor_y = max(0, state.cursor_y - (rows - BOTTOM_ROWS - 1))
    elif key == 'PAGEDOWN':
        cols, rows = state.term_cols, state.term_rows
        state.cursor_y = min(state.canvas_h - 1, state.cursor_y + (rows - BOTTOM_ROWS - 1))

    elif key in ('SPACE', 'ENTER'):
        if state.tool == "fill":
            _flood_fill_local(state, state.cursor_x, state.cursor_y)
        else:
            _paint(state, state.cursor_x, state.cursor_y)

    elif key.isdigit() and key != '0':
        idx = int(key) - 1
        if idx < len(state.palette):
            old_idx = state.palette_idx
            state.palette_idx = idx
            px = state.palette[idx]
            state.status_msg = f"Color {idx+1}: #{px.r:02x}{px.g:02x}{px.b:02x}"
            state.status_timer = time.time() + 2
            state.full_redraw_needed = True  # palette panel update

    elif key in ('f', 'F'):
        state.tool = "fill" if state.tool != "fill" else "pencil"
        state.status_msg = f"Tool: {state.tool}"
        state.status_timer = time.time() + 2

    elif key in ('e', 'E'):
        state.tool = "erase" if state.tool != "erase" else "pencil"
        state.status_msg = f"Tool: {state.tool}"
        state.status_timer = time.time() + 2

    elif key in ('u',):
        state.cmd_queue.put(("undo", [], {"show_error": True}))
        state.cmd_queue.put(("_refresh_frame", [], {}))
        state.status_msg = "Undo"
        state.status_timer = time.time() + 1.5

    elif key in ('r',):
        state.cmd_queue.put(("redo", [], {"show_error": True}))
        state.cmd_queue.put(("_refresh_frame", [], {}))
        state.status_msg = "Redo"
        state.status_timer = time.time() + 1.5

    elif key == 'n':
        state.cmd_queue.put(("new_frame", [], {}))
        state.cmd_queue.put(("_refresh_meta", [], {}))
        state.status_msg = "New frame added"
        state.status_timer = time.time() + 2

    elif key == 'TAB':
        new_idx = (state.active_frame + 1) % state.frame_count
        state.active_frame = new_idx
        state.cmd_queue.put(("set_active_frame", [str(new_idx)], {}))
        state.cmd_queue.put(("_refresh_frame", [], {}))
        state.status_msg = f"Frame {new_idx}"
        state.status_timer = time.time() + 1.5
        state.full_redraw_needed = True

    elif key == 'SHIFT_TAB' or key == 'EXT_15':
        new_idx = (state.active_frame - 1) % state.frame_count
        state.active_frame = new_idx
        state.cmd_queue.put(("set_active_frame", [str(new_idx)], {}))
        state.cmd_queue.put(("_refresh_frame", [], {}))
        state.status_msg = f"Frame {new_idx}"
        state.status_timer = time.time() + 1.5
        state.full_redraw_needed = True

    elif key in ('q', 'Q', 'ESC'):
        return False

    # If cursor moved, mark old and new position as changed
    new_cursor = (state.cursor_x, state.cursor_y)
    if old_cursor != new_cursor:
        state.changed_cells.add(old_cursor)
        state.changed_cells.add(new_cursor)
        _scroll_to_cursor(state)

    state.dirty = True
    return True


# ── Init ─────────────────────────────────────────────────────────────

def _build_state(port: int | None) -> EditorState:
    palette = []
    for hex_str in DEFAULT_PALETTE:
        c = parse_color(hex_str)
        if c:
            palette.append(c)

    # Default canvas
    w, h = 64, 64
    frame_count = 1
    active_frame = 0
    name = "untitled"
    connected = False

    if port:
        r = _tcp_send(port, "status", [])
        if r and r.get("status") == "ok":
            d = r["data"]
            wh = d.get("size", "64x64").split("x")
            w, h = int(wh[0]), int(wh[1])
            frame_count = d.get("frames", 1)
            active_frame = d.get("active_frame", 0)
            name = d.get("name", "untitled")
            connected = True

            # Fetch server palette
            rp = _tcp_send(port, "palette_get", [])
            if rp and rp.get("status") == "ok":
                srv_palette = [parse_color(c) for c in rp["data"].get("palette", []) if parse_color(c)]
                if srv_palette:
                    palette = srv_palette

    # Blank canvas buffers
    canvas = [
        [[TRANSPARENT] * w for _ in range(h)]
        for _ in range(frame_count)
    ]

    state = EditorState(
        canvas=canvas,
        canvas_w=w,
        canvas_h=h,
        frame_count=frame_count,
        active_frame=active_frame,
        palette=palette,
        server_port=port,
        connected=connected,
        project_name=name,
    )
    return state


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    _enable_vt_mode()

    port = read_port()
    state = _build_state(port)

    # Start TCP worker
    worker = threading.Thread(target=_tcp_worker, args=(state,), daemon=True)
    worker.start()

    # Fetch initial canvas from server
    if state.connected:
        _fetch_frame(state, state.active_frame)
        state.full_redraw_needed = True

    # Enter alternate screen, hide cursor
    sys.stdout.write(f"{ESC}[?1049h{ESC}[?25l{ESC}[2J")
    sys.stdout.flush()

    try:
        # Initial render
        render_full(state)
        state.dirty = False

        while True:
            # Non-blocking check for dirty (from server updates)
            if state.dirty:
                if state.full_redraw_needed:
                    render_full(state)
                else:
                    render_incremental(state)
                state.dirty = False

            key = _read_key()
            if not handle_key(key, state):
                break

    finally:
        # Restore terminal
        sys.stdout.write(f"{ESC}[?1049l{ESC}[?25h{ESC}[0m\n")
        sys.stdout.flush()
        # Stop worker
        state.cmd_queue.put(None)


if __name__ == "__main__":
    main()
