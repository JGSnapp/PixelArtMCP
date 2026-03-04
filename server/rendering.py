"""Rendering helpers for GUI previews and screenshots."""
from __future__ import annotations

from pathlib import Path

from server.canvas import CanvasState

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - optional dependency
    Image = None
    ImageDraw = None


def pillow_available() -> bool:
    return Image is not None


def frame_to_image(frame):
    if Image is None:
        raise ImportError("pillow_missing")
    img = Image.new("RGBA", (frame.width, frame.height), (0, 0, 0, 0))
    data = []
    for row in frame.pixels:
        for px in row:
            data.append((px.r, px.g, px.b, px.a))
    img.putdata(data)
    return img


def composite_checkerboard(img, tile: int = 8):
    if Image is None:
        raise ImportError("pillow_missing")
    tile = max(2, tile)
    bg = Image.new("RGBA", img.size)
    px = bg.load()
    for y in range(img.height):
        for x in range(img.width):
            even = ((x // tile) + (y // tile)) % 2 == 0
            px[x, y] = (200, 200, 200, 255) if even else (160, 160, 160, 255)
    bg.alpha_composite(img)
    return bg


def render_state_image(
    state: CanvasState,
    include_background: bool = True,
    include_checkerboard: bool = True,
    include_grid: bool = False,
    zoom: int = 1,
):
    """Render active frame to PIL image, optionally including background reference."""
    if Image is None:
        raise ImportError("pillow_missing")

    with state.lock:
        project = state.project
        frame = project.active_frame
        canvas = Image.new("RGBA", (frame.width, frame.height), (0, 0, 0, 0))

        if include_background and state.background_reference is not None:
            ref = state.background_reference
            bg_img = ref["image"]
            alpha = ref["opacity"]
            ox, oy = ref["offset_x"], ref["offset_y"]
            if alpha < 1.0:
                bg_img = bg_img.copy()
                r, g, b, a = bg_img.split()
                a = a.point(lambda v: int(v * alpha))
                bg_img.putalpha(a)
            canvas.alpha_composite(bg_img, dest=(ox, oy))

        canvas.alpha_composite(frame_to_image(frame))

    if include_checkerboard:
        canvas = composite_checkerboard(canvas, tile=max(2, frame.width // 16))

    if zoom > 1:
        canvas = canvas.resize((canvas.width * zoom, canvas.height * zoom), Image.NEAREST)

    if include_grid and zoom >= 4:
        draw = ImageDraw.Draw(canvas)
        grid_color = (80, 80, 80, 120)
        for gx in range(0, frame.width * zoom, zoom):
            draw.line([(gx, 0), (gx, frame.height * zoom)], fill=grid_color)
        for gy in range(0, frame.height * zoom, zoom):
            draw.line([(0, gy), (frame.width * zoom, gy)], fill=grid_color)

    return canvas


def save_state_screenshot(state: CanvasState, path: str, zoom: int = 8) -> str:
    img = render_state_image(
        state,
        include_background=True,
        include_checkerboard=True,
        include_grid=True,
        zoom=max(1, zoom),
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return str(out)
