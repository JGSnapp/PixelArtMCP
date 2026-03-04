"""Frame panel — sidebar with frame thumbnails."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..server.canvas import CanvasState

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

THUMB_SIZE = 48
THUMB_PAD = 4


class FramePanel(tk.Frame):
    def __init__(
        self,
        parent,
        state: "CanvasState",
        on_new_frame: Callable | None = None,
        on_dup_frame: Callable | None = None,
        on_del_frame: Callable | None = None,
        on_select_frame: Callable[[int], None] | None = None,
    ):
        super().__init__(parent, bg="#111122", width=120)
        self.state = state
        self.on_new_frame = on_new_frame
        self.on_dup_frame = on_dup_frame
        self.on_del_frame = on_del_frame
        self.on_select_frame = on_select_frame

        self._photos: list = []  # keep PIL refs

        # Header
        lbl = tk.Label(self, text="Frames", bg="#111122", fg="#88aaff",
                       font=("Consolas", 9, "bold"))
        lbl.pack(pady=(6, 2))

        # Scrollable area
        scroll_frame = tk.Frame(self, bg="#111122")
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(scroll_frame, bg="#111122", highlightthickness=0, width=114)
        scrollbar = tk.Scrollbar(scroll_frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = tk.Frame(self._canvas, bg="#111122")
        self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>",
                          lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))

        # Buttons
        btn_frame = tk.Frame(self, bg="#111122")
        btn_frame.pack(fill=tk.X, pady=4)

        style = {"bg": "#223", "fg": "#adf", "font": ("Consolas", 8),
                 "relief": tk.FLAT, "padx": 4, "pady": 2, "cursor": "hand2"}
        tk.Button(btn_frame, text="+", command=self._new_frame, **style).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="Dup", command=self._dup_frame, **style).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="Del", command=self._del_frame, **style).pack(side=tk.LEFT, padx=2)

    def refresh(self) -> None:
        """Rebuild all frame thumbnails."""
        for w in self._inner.winfo_children():
            w.destroy()
        self._photos.clear()

        with self.state.lock:
            frames = self.state.project.frames
            active_idx = self.state.project.active_frame_index
            n = len(frames)

            # Build thumbnails
            frame_data = []
            for f in frames:
                thumb = self._make_thumbnail(f)
                frame_data.append((f.index, thumb))

        for idx, photo in frame_data:
            is_active = (idx == active_idx)
            border_color = "#4466ff" if is_active else "#333355"
            container = tk.Frame(self._inner, bg=border_color, padx=2, pady=2)
            container.pack(pady=2, padx=4)

            if photo:
                lbl = tk.Label(container, image=photo, bg=border_color, cursor="hand2")
                lbl.pack()
                self._photos.append(photo)
            else:
                lbl = tk.Label(container, text=f"F{idx}", bg=border_color,
                                fg="white", width=6, height=3)
                lbl.pack()

            num_lbl = tk.Label(container, text=str(idx), bg=border_color,
                                fg="#aaa", font=("Consolas", 7))
            num_lbl.pack()

            # Capture idx in closure
            def _click(event, i=idx):
                if self.on_select_frame:
                    self.on_select_frame(i)
            lbl.bind("<Button-1>", _click)
            num_lbl.bind("<Button-1>", _click)

        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _make_thumbnail(self, frame) -> object | None:
        if not PIL_AVAILABLE:
            return None
        img = Image.new("RGBA", (frame.width, frame.height))
        data = []
        for row in frame.pixels:
            for px in row:
                data.append((px.r, px.g, px.b, px.a))
        img.putdata(data)

        # Checkerboard under transparent
        bg = Image.new("RGBA", img.size)
        cs = max(2, frame.width // 8)
        for y in range(frame.height):
            for x in range(frame.width):
                even = ((x // cs) + (y // cs)) % 2 == 0
                bg.putpixel((x, y), (180, 180, 180) if even else (140, 140, 140))
        bg.alpha_composite(img)

        thumb = bg.resize((THUMB_SIZE, THUMB_SIZE), Image.NEAREST)
        return ImageTk.PhotoImage(thumb)

    def _new_frame(self) -> None:
        if self.on_new_frame:
            self.on_new_frame()

    def _dup_frame(self) -> None:
        if self.on_dup_frame:
            self.on_dup_frame()

    def _del_frame(self) -> None:
        if self.on_del_frame:
            self.on_del_frame()
