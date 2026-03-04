"""Canvas view widget — displays the pixel grid with zoom, grid lines, onion skin."""
from __future__ import annotations
import tkinter as tk
from tkinter import colorchooser
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from server.canvas import CanvasState

try:
    from PIL import Image, ImageDraw, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from shared.color import PixelColor, TRANSPARENT
from ..server import rendering


def _frame_to_pil_image(frame, alpha_override: int | None = None):
    """Convert Frame pixels to PIL RGBA Image."""
    img = Image.new("RGBA", (frame.width, frame.height), (0, 0, 0, 0))
    data = []
    for row in frame.pixels:
        for px in row:
            data.append((px.r, px.g, px.b, px.a if alpha_override is None else alpha_override))
    img.putdata(data)
    return img


def _composite_with_checkerboard(img):
    """Composite RGBA image over a checkerboard background for transparent pixels."""
    bg = Image.new("RGBA", img.size)
    size = max(4, img.width // 16)
    for y in range(0, img.height, size):
        for x in range(0, img.width, size):
            even = ((x // size) + (y // size)) % 2 == 0
            color = (200, 200, 200, 255) if even else (160, 160, 160, 255)
            for py in range(y, min(y + size, img.height)):
                for px in range(x, min(x + size, img.width)):
                    bg.putpixel((px, py), color)
    bg.alpha_composite(img)
    return bg


class CanvasView(tk.Frame):
    def __init__(
        self,
        parent,
        state: "CanvasState",
        on_pixel_click: Callable[[int, int], None] | None = None,
        on_hover: Callable[[int, int, PixelColor | None], None] | None = None,
        zoom: int = 8,
    ):
        super().__init__(parent, bg="#1a1a2e")
        self.state = state
        self.on_pixel_click = on_pixel_click
        self.on_hover = on_hover

        self._zoom = zoom
        self._show_grid = True
        self._onion_skin = False
        self._onion_prev = True
        self._onion_next = False
        self._photo: object = None  # keep reference to prevent GC
        self._drag_last: tuple[int, int] | None = None

        # Build widget
        self._canvas = tk.Canvas(self, bg="#0a0a1a", cursor="crosshair",
                                 highlightthickness=0)
        h_scroll = tk.Scrollbar(self, orient=tk.HORIZONTAL, command=self._canvas.xview)
        v_scroll = tk.Scrollbar(self, orient=tk.VERTICAL, command=self._canvas.yview)

        self._canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        h_scroll.grid(row=1, column=0, sticky="ew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # Events
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag_last", None))
        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Leave>", lambda e: self.on_hover and self.on_hover(-1, -1, None))

    # ── Properties ──────────────────────────────────────────────────

    @property
    def zoom(self) -> int:
        return self._zoom

    @zoom.setter
    def zoom(self, value: int) -> None:
        self._zoom = max(1, min(32, value))
        self.refresh()

    @property
    def show_grid(self) -> bool:
        return self._show_grid

    @show_grid.setter
    def show_grid(self, value: bool) -> None:
        self._show_grid = value
        self.refresh()

    @property
    def onion_skin(self) -> bool:
        return self._onion_skin

    @onion_skin.setter
    def onion_skin(self, value: bool) -> None:
        self._onion_skin = value
        self.refresh()

    # ── Rendering ────────────────────────────────────────────────────

    def refresh(self) -> None:
        if not PIL_AVAILABLE:
            self._render_fallback()
            return
        self._render_pil()

    def _render_pil(self) -> None:
        with self.state.lock:
            frame = self.state.project.active_frame
            fw, fh = frame.width, frame.height
        zoom = self._zoom
        img = rendering.render_state_image(
            self.state,
            include_background=True,
            include_checkerboard=True,
            include_grid=self._show_grid,
            zoom=zoom,
        )

        self._photo = ImageTk.PhotoImage(img)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._canvas.configure(scrollregion=(0, 0, fw * zoom, fh * zoom))

    def _render_fallback(self) -> None:
        """Fallback rendering without PIL: draw rectangles (slow for large canvases)."""
        self._canvas.delete("all")
        with self.state.lock:
            frame = self.state.project.active_frame
            zoom = self._zoom
            for y, row in enumerate(frame.pixels):
                for x, px in enumerate(row):
                    color = f"#{px.r:02x}{px.g:02x}{px.b:02x}"
                    x0, y0 = x * zoom, y * zoom
                    self._canvas.create_rectangle(
                        x0, y0, x0 + zoom, y0 + zoom,
                        fill=color, outline="" if zoom < 4 else "#333",
                    )

    # ── Events ───────────────────────────────────────────────────────

    def _canvas_to_pixel(self, event) -> tuple[int, int] | None:
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        x = int(cx // self._zoom)
        y = int(cy // self._zoom)
        with self.state.lock:
            frame = self.state.project.active_frame
            if 0 <= x < frame.width and 0 <= y < frame.height:
                return x, y
        return None

    def _on_click(self, event) -> None:
        pos = self._canvas_to_pixel(event)
        if pos and self.on_pixel_click:
            self._drag_last = pos
            self.on_pixel_click(*pos)

    def _on_drag(self, event) -> None:
        pos = self._canvas_to_pixel(event)
        if pos and self.on_pixel_click and pos != self._drag_last:
            self._drag_last = pos
            self.on_pixel_click(*pos)

    def _on_motion(self, event) -> None:
        if not self.on_hover:
            return
        pos = self._canvas_to_pixel(event)
        if pos:
            with self.state.lock:
                frame = self.state.project.active_frame
                color = frame.pixels[pos[1]][pos[0]]
            self.on_hover(pos[0], pos[1], color)

    def _on_mousewheel(self, event) -> None:
        if event.delta > 0:
            self.zoom = self._zoom + 1
        else:
            self.zoom = self._zoom - 1
