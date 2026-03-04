"""Palette panel — color swatches and foreground color selector."""
from __future__ import annotations
import tkinter as tk
from tkinter import colorchooser
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..server.canvas import CanvasState

from ..shared.color import PixelColor, parse_color, NAMED_COLORS


DEFAULT_PALETTE = [
    "#000000", "#ffffff", "#ff0000", "#00c800", "#0000ff",
    "#ffff00", "#ff8c00", "#800080", "#00ffff", "#ff00ff",
    "#808080", "#c0c0c0", "#5c3317", "#1a237e", "#e3000b",
    "#0033a0", "#e8c49a", "#4a2800", "#b8d4b8", "#c8e0c8",
    "#cc0000", "#2d4a7c", "#1a1a2e", "#3a5a8c", "#c0392b",
    "#2ecc71", "#e74c3c", "#3498db", "#f39c12", "#9b59b6",
    "#1abc9c", "#34495e",
]


class PalettePanel(tk.Frame):
    def __init__(
        self,
        parent,
        state: "CanvasState",
        on_color_selected: Callable[[PixelColor], None] | None = None,
    ):
        super().__init__(parent, bg="#111122", width=120)
        self.state = state
        self.on_color_selected = on_color_selected
        self._current_color = PixelColor(0, 0, 0, 255)  # foreground

        # Foreground display
        fg_frame = tk.Frame(self, bg="#111122")
        fg_frame.pack(fill=tk.X, padx=4, pady=(6, 2))
        tk.Label(fg_frame, text="FG:", bg="#111122", fg="#aaa",
                  font=("Consolas", 8)).pack(side=tk.LEFT)
        self._fg_btn = tk.Button(
            fg_frame, bg="#000000", width=3, relief=tk.FLAT, cursor="hand2",
            command=self._pick_fg_color,
        )
        self._fg_btn.pack(side=tk.LEFT, padx=4)
        self._fg_hex = tk.Label(fg_frame, text="#000000", bg="#111122",
                                 fg="#aaa", font=("Consolas", 7))
        self._fg_hex.pack(side=tk.LEFT)

        tk.Label(self, text="Palette", bg="#111122", fg="#88aaff",
                  font=("Consolas", 9, "bold")).pack(pady=(4, 2))

        # Swatch grid
        self._swatch_frame = tk.Frame(self, bg="#111122")
        self._swatch_frame.pack(fill=tk.X, padx=4)

        # Buttons
        btn_frame = tk.Frame(self, bg="#111122")
        btn_frame.pack(fill=tk.X, pady=4, padx=4)
        style = {"bg": "#223", "fg": "#adf", "font": ("Consolas", 8),
                  "relief": tk.FLAT, "cursor": "hand2"}
        tk.Button(btn_frame, text="+ Add", command=self._add_color, **style).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="Clear", command=self._clear_palette, **style).pack(side=tk.LEFT, padx=2)

        # Init with default palette
        with self.state.lock:
            if not self.state.project.palette:
                from ..shared.color import parse_color
                self.state.project.palette = [
                    parse_color(c) for c in DEFAULT_PALETTE if parse_color(c)
                ]

        self.refresh()

    @property
    def current_color(self) -> PixelColor:
        return self._current_color

    def refresh(self) -> None:
        for w in self._swatch_frame.winfo_children():
            w.destroy()

        with self.state.lock:
            palette = list(self.state.project.palette)

        cols = 4
        for i, color in enumerate(palette):
            row = i // cols
            col = i % cols
            hex_color = f"#{color.r:02x}{color.g:02x}{color.b:02x}"
            is_light = (color.r * 299 + color.g * 587 + color.b * 114) > 128000
            border = "#555" if is_light else "#888"
            btn = tk.Button(
                self._swatch_frame,
                bg=hex_color,
                width=2, height=1,
                relief=tk.FLAT,
                cursor="hand2",
                highlightbackground=border,
                highlightthickness=1,
            )
            btn.grid(row=row, column=col, padx=1, pady=1)
            btn.bind("<Button-1>", lambda e, c=color: self._select_color(c))
            btn.bind("<Button-3>", lambda e, c=color: self._remove_color(c))

    def _select_color(self, color: PixelColor) -> None:
        self._current_color = color
        hex_str = f"#{color.r:02x}{color.g:02x}{color.b:02x}"
        self._fg_btn.configure(bg=hex_str)
        self._fg_hex.configure(text=hex_str)
        if self.on_color_selected:
            self.on_color_selected(color)

    def _pick_fg_color(self) -> None:
        hex_str = f"#{self._current_color.r:02x}{self._current_color.g:02x}{self._current_color.b:02x}"
        result = colorchooser.askcolor(color=hex_str, title="Choose color")
        if result and result[1]:
            color = parse_color(result[1])
            if color:
                self._select_color(color)
                # Add to palette if not there
                with self.state.lock:
                    if color not in self.state.project.palette:
                        self.state.project.palette.append(color)
                self.refresh()

    def _add_color(self) -> None:
        self._pick_fg_color()

    def _remove_color(self, color: PixelColor) -> None:
        with self.state.lock:
            try:
                self.state.project.palette.remove(color)
            except ValueError:
                pass
        self.refresh()

    def _clear_palette(self) -> None:
        with self.state.lock:
            self.state.project.palette.clear()
        self.refresh()
