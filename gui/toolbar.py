"""Toolbar: zoom, playback controls, FPS, grid toggle, onion skin."""
from __future__ import annotations
import tkinter as tk
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .canvas_view import CanvasView
    from ..server.canvas import CanvasState


class Toolbar(tk.Frame):
    def __init__(
        self,
        parent,
        state: "CanvasState",
        canvas_view_getter: Callable,
        on_frame_advance: Callable[[int], None] | None = None,
        on_fps_change: Callable[[int], None] | None = None,
    ):
        super().__init__(parent, bg="#0d0d1e", pady=3)
        self.state = state
        self._get_canvas_view = canvas_view_getter
        self.on_frame_advance = on_frame_advance
        self.on_fps_change = on_fps_change

        self._playing = False
        self._play_job: str | None = None

        style_btn = {"bg": "#1a1a3a", "fg": "#88ddff", "font": ("Consolas", 9),
                     "relief": tk.FLAT, "padx": 6, "pady": 2, "cursor": "hand2",
                     "activebackground": "#2a2a5a", "activeforeground": "white",
                     "bd": 0}
        style_lbl = {"bg": "#0d0d1e", "fg": "#667788", "font": ("Consolas", 8)}

        # ── Playback ──────────────────────────────────────────────
        self._play_btn = tk.Button(self, text="▶ Play", command=self._toggle_play, **style_btn)
        self._play_btn.pack(side=tk.LEFT, padx=(4, 2))

        # ── FPS ───────────────────────────────────────────────────
        tk.Label(self, text="FPS:", **style_lbl).pack(side=tk.LEFT, padx=(8, 0))
        self._fps_var = tk.IntVar(value=12)
        fps_spin = tk.Spinbox(
            self, from_=1, to=60, width=3, textvariable=self._fps_var,
            bg="#1a1a3a", fg="#88ddff", font=("Consolas", 9), relief=tk.FLAT,
            command=self._on_fps_change, bd=0,
        )
        fps_spin.pack(side=tk.LEFT, padx=2)
        fps_spin.bind("<Return>", lambda e: self._on_fps_change())

        # ── Zoom ──────────────────────────────────────────────────
        tk.Label(self, text="  Zoom:", **style_lbl).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(self, text="▼", command=self._zoom_out, **style_btn).pack(side=tk.LEFT, padx=1)
        self._zoom_lbl = tk.Label(self, text="8x", bg="#0d0d1e", fg="#88ddff",
                                   font=("Consolas", 9), width=4)
        self._zoom_lbl.pack(side=tk.LEFT)
        tk.Button(self, text="▲", command=self._zoom_in, **style_btn).pack(side=tk.LEFT, padx=1)

        # ── Grid toggle ───────────────────────────────────────────
        self._grid_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            self, text="Grid", variable=self._grid_var, command=self._on_grid,
            bg="#0d0d1e", fg="#88ddff", selectcolor="#1a1a3a",
            font=("Consolas", 8), relief=tk.FLAT, cursor="hand2",
            activebackground="#0d0d1e", activeforeground="#88ddff",
        ).pack(side=tk.LEFT, padx=(8, 2))

        # ── Onion skin ────────────────────────────────────────────
        self._onion_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self, text="Onion", variable=self._onion_var, command=self._on_onion,
            bg="#0d0d1e", fg="#88ddff", selectcolor="#1a1a3a",
            font=("Consolas", 8), relief=tk.FLAT, cursor="hand2",
            activebackground="#0d0d1e", activeforeground="#88ddff",
        ).pack(side=tk.LEFT, padx=2)

        # ── Separator ─────────────────────────────────────────────
        tk.Label(self, text="  ", **style_lbl).pack(side=tk.LEFT)

    def sync_zoom(self, zoom: int) -> None:
        self._zoom_lbl.configure(text=f"{zoom}x")

    def sync_fps(self, fps: int) -> None:
        self._fps_var.set(fps)

    # ── Playback ─────────────────────────────────────────────────────

    def _toggle_play(self) -> None:
        if self._playing:
            self._stop()
        else:
            self._play()

    def _play(self) -> None:
        self._playing = True
        self._play_btn.configure(text="■ Stop")
        self._schedule_next()

    def _stop(self) -> None:
        self._playing = False
        self._play_btn.configure(text="▶ Play")
        if self._play_job:
            self.after_cancel(self._play_job)
            self._play_job = None

    def _schedule_next(self) -> None:
        if not self._playing:
            return
        fps = max(1, self._fps_var.get())
        delay = max(16, 1000 // fps)
        self._play_job = self.after(delay, self._advance_frame)

    def _advance_frame(self) -> None:
        if not self._playing:
            return
        with self.state.lock:
            p = self.state.project
            n = len(p.frames)
            if n > 1:
                p.active_frame_index = (p.active_frame_index + 1) % n
        self.state.mark_dirty()
        if self.on_frame_advance:
            self.on_frame_advance(self.state.project.active_frame_index)
        self._schedule_next()

    # ── Zoom ─────────────────────────────────────────────────────────

    def _zoom_in(self) -> None:
        cv = self._get_canvas_view()
        if cv:
            cv.zoom = cv.zoom + 1
            self._zoom_lbl.configure(text=f"{cv.zoom}x")

    def _zoom_out(self) -> None:
        cv = self._get_canvas_view()
        if cv:
            cv.zoom = cv.zoom - 1
            self._zoom_lbl.configure(text=f"{cv.zoom}x")

    # ── Callbacks ────────────────────────────────────────────────────

    def _on_fps_change(self) -> None:
        fps = self._fps_var.get()
        if self.on_fps_change:
            self.on_fps_change(fps)

    def _on_grid(self) -> None:
        cv = self._get_canvas_view()
        if cv:
            cv.show_grid = self._grid_var.get()

    def _on_onion(self) -> None:
        cv = self._get_canvas_view()
        if cv:
            cv.onion_skin = self._onion_var.get()
