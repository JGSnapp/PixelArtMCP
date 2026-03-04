"""Export: PNG, spritesheet, GIF via Pillow."""
from __future__ import annotations
import math
from pathlib import Path

from ..shared.protocol import Project, Frame
from ..shared.color import PixelColor


def _frame_to_pil(frame: Frame):
    """Convert Frame to PIL RGBA Image."""
    try:
        from PIL import Image
    except ImportError:
        raise ImportError("pillow_missing")

    img = Image.new("RGBA", (frame.width, frame.height))
    px = img.load()
    for y in range(frame.height):
        for x in range(frame.width):
            c = frame.pixels[y][x]
            px[x, y] = (c.r, c.g, c.b, c.a)
    return img


def export_png(project: Project, path: str, frame_index: int | None = None) -> str:
    fidx = frame_index if frame_index is not None else project.active_frame_index
    frame = project.frames[fidx]
    img = _frame_to_pil(frame)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    return path


def export_spritesheet(project: Project, path: str, columns: int = 0) -> str:
    n = len(project.frames)
    cols = columns if columns > 0 else n
    rows = math.ceil(n / cols)

    sheet_w = cols * project.width
    sheet_h = rows * project.height

    try:
        from PIL import Image
    except ImportError:
        raise ImportError("pillow_missing")

    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    for i, frame in enumerate(project.frames):
        col = i % cols
        row = i // cols
        fi = _frame_to_pil(frame)
        sheet.paste(fi, (col * project.width, row * project.height))

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, "PNG")
    return path


def export_gif(project: Project, path: str, fps: int | None = None) -> str:
    try:
        from PIL import Image
    except ImportError:
        raise ImportError("pillow_missing")

    actual_fps = fps or project.fps or 12
    duration_ms = max(1, round(1000 / actual_fps))

    frames_pil = [_frame_to_pil(f).convert("RGBA") for f in project.frames]
    if not frames_pil:
        raise ValueError("No frames to export")

    # Convert to palette mode for GIF
    palette_frames = []
    for img in frames_pil:
        bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
        bg.alpha_composite(img)
        palette_frames.append(bg.convert("P", palette=Image.ADAPTIVE, colors=256))

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    palette_frames[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=palette_frames[1:],
        loop=0,
        duration=duration_ms,
        disposal=2,
    )
    return path
