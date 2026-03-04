"""Main preview window — assembles all GUI panels."""
from __future__ import annotations
import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..server.canvas import CanvasState

from .canvas_view import CanvasView
from .frame_panel import FramePanel
from .palette_panel import PalettePanel
from .toolbar import Toolbar
from ..shared.color import PixelColor
from .. import server


POLL_INTERVAL_MS = 50  # 20 Hz


class PreviewWindow:
    def __init__(self, state: "CanvasState") -> None:
        self.state = state

        self.root = tk.Tk()
        self.root.title(f"pxart — {state.project.name}")
        self.root.configure(bg="#0a0a1a")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Minimum size
        self.root.minsize(700, 500)

        self._build_ui()
        self._schedule_poll()

    # ── Build ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        state = self.state

        # Toolbar (top)
        self.toolbar = Toolbar(
            self.root,
            state,
            canvas_view_getter=lambda: getattr(self, "_canvas_view", None),
            on_frame_advance=self._on_frame_advance,
            on_fps_change=self._on_fps_change,
        )
        self.toolbar.pack(side=tk.TOP, fill=tk.X)

        # Main paned window (3 columns)
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg="#0a0a1a",
                               sashwidth=4, sashrelief=tk.FLAT)
        paned.pack(fill=tk.BOTH, expand=True)

        # Left: Frame panel
        self._frame_panel = FramePanel(
            paned, state,
            on_new_frame=self._cmd_new_frame,
            on_dup_frame=self._cmd_dup_frame,
            on_del_frame=self._cmd_del_frame,
            on_select_frame=self._cmd_select_frame,
        )
        paned.add(self._frame_panel, minsize=90, width=110)

        # Center: Canvas view
        self._canvas_view = CanvasView(
            paned, state,
            on_pixel_click=self._on_pixel_click,
            on_hover=self._on_hover,
            zoom=8,
        )
        paned.add(self._canvas_view, minsize=200)

        # Right: Palette
        self._palette = PalettePanel(
            paned, state,
            on_color_selected=self._on_color_selected,
        )
        paned.add(self._palette, minsize=100, width=120)

        # Status bar (bottom)
        status_frame = tk.Frame(self.root, bg="#060614", height=20)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        status_frame.pack_propagate(False)

        self._status_frame_lbl = tk.Label(
            status_frame, text="Frame 1/1", bg="#060614", fg="#556677",
            font=("Consolas", 8), anchor="w")
        self._status_frame_lbl.pack(side=tk.LEFT, padx=8)

        tk.Label(status_frame, text="|", bg="#060614", fg="#334").pack(side=tk.LEFT)

        with self.state.lock:
            w = state.project.width
            h = state.project.height
        self._status_size_lbl = tk.Label(
            status_frame, text=f"{w}×{h}", bg="#060614", fg="#556677",
            font=("Consolas", 8))
        self._status_size_lbl.pack(side=tk.LEFT, padx=8)

        tk.Label(status_frame, text="|", bg="#060614", fg="#334").pack(side=tk.LEFT)

        self._status_cursor_lbl = tk.Label(
            status_frame, text="", bg="#060614", fg="#556677",
            font=("Consolas", 8))
        self._status_cursor_lbl.pack(side=tk.LEFT, padx=8)

        # Initial render
        self._full_refresh()

    # ── Polling ────────────────────────────────────────────────────────

    def _schedule_poll(self) -> None:
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        if self.state.dirty.is_set():
            self.state.dirty.clear()
            self._full_refresh()
        self._schedule_poll()

    def _full_refresh(self) -> None:
        """Redraw canvas and update panels."""
        self._canvas_view.refresh()
        self._frame_panel.refresh()
        self._palette.refresh()
        self._update_status()
        # Sync toolbar FPS
        with self.state.lock:
            fps = self.state.project.fps
        self.toolbar.sync_fps(fps)
        # Update window title
        with self.state.lock:
            name = self.state.project.name
        self.root.title(f"pxart — {name}")

    def _update_status(self) -> None:
        with self.state.lock:
            p = self.state.project
            fidx = p.active_frame_index
            total = len(p.frames)
            w, h = p.width, p.height
        self._status_frame_lbl.configure(text=f"Frame {fidx + 1}/{total}")
        self._status_size_lbl.configure(text=f"{w}×{h}")

    # ── Event handlers ────────────────────────────────────────────────

    def _on_hover(self, x: int, y: int, color: PixelColor | None) -> None:
        if x < 0 or color is None:
            self._status_cursor_lbl.configure(text="")
        else:
            self._status_cursor_lbl.configure(
                text=f"({x}, {y}) = {color.to_hex()}"
            )

    def _on_pixel_click(self, x: int, y: int) -> None:
        """User clicked on canvas — draw with foreground color via TCP."""
        color = self._palette.current_color
        # Send via TCP so undo history is tracked
        from ..client.client import send_command
        try:
            send_command("set_pixel", [str(x), str(y), color.to_hex()])
        except SystemExit:
            pass  # Server may not be reachable in rare cases

    def _on_color_selected(self, color: PixelColor) -> None:
        pass  # foreground color updated in PalettePanel

    def _on_frame_advance(self, new_idx: int) -> None:
        pass  # dirty flag set by toolbar

    def _on_fps_change(self, fps: int) -> None:
        from ..client.client import send_command
        try:
            send_command("set_fps", [str(fps)])
        except SystemExit:
            pass

    # ── Frame panel callbacks ──────────────────────────────────────────

    def _cmd_new_frame(self) -> None:
        from ..client.client import send_command
        try:
            send_command("new_frame", [])
        except SystemExit:
            pass

    def _cmd_dup_frame(self) -> None:
        from ..client.client import send_command
        try:
            send_command("dup_frame", [])
        except SystemExit:
            pass

    def _cmd_del_frame(self) -> None:
        from ..client.client import send_command
        try:
            send_command("del_frame", [])
        except SystemExit:
            pass

    def _cmd_select_frame(self, idx: int) -> None:
        from ..client.client import send_command
        try:
            send_command("set_active_frame", [str(idx)])
        except SystemExit:
            pass

    # ── Lifecycle ──────────────────────────────────────────────────────

    def _on_close(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        """Start the tkinter main loop (blocks until window is closed)."""
        self.root.mainloop()
