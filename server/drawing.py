"""Drawing primitives operating on Frame objects."""
from __future__ import annotations
from ..shared.protocol import Frame
from ..shared.color import PixelColor


def set_pixel(frame: Frame, x: int, y: int, color: PixelColor) -> None:
    frame.pixels[y][x] = color


def fill_rect(frame: Frame, x: int, y: int, w: int, h: int, color: PixelColor) -> None:
    x2 = min(x + w, frame.width)
    y2 = min(y + h, frame.height)
    x1 = max(x, 0)
    y1 = max(y, 0)
    for py in range(y1, y2):
        for px in range(x1, x2):
            frame.pixels[py][px] = color


def draw_rect(frame: Frame, x: int, y: int, w: int, h: int, color: PixelColor) -> None:
    """Rectangle outline only."""
    x2, y2 = x + w - 1, y + h - 1
    for px in range(x, x + w):
        if 0 <= y < frame.height and 0 <= px < frame.width:
            frame.pixels[y][px] = color
        if 0 <= y2 < frame.height and 0 <= px < frame.width:
            frame.pixels[y2][px] = color
    for py in range(y, y + h):
        if 0 <= py < frame.height and 0 <= x < frame.width:
            frame.pixels[py][x] = color
        if 0 <= py < frame.height and 0 <= x2 < frame.width:
            frame.pixels[py][x2] = color


def line(frame: Frame, x1: int, y1: int, x2: int, y2: int, color: PixelColor) -> None:
    """Bresenham's line algorithm."""
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx - dy
    cx, cy = x1, y1

    while True:
        if 0 <= cx < frame.width and 0 <= cy < frame.height:
            frame.pixels[cy][cx] = color
        if cx == x2 and cy == y2:
            break
        e2 = err * 2
        if e2 > -dy:
            err -= dy
            cx += sx
        if e2 < dx:
            err += dx
            cy += sy


def flood_fill(frame: Frame, x: int, y: int, new_color: PixelColor) -> None:
    """Iterative BFS flood fill (avoids Python recursion limit)."""
    if not (0 <= x < frame.width and 0 <= y < frame.height):
        return
    target = frame.pixels[y][x]
    if target == new_color:
        return

    stack = [(x, y)]
    visited: set[tuple[int, int]] = set()
    w, h = frame.width, frame.height

    while stack:
        cx, cy = stack.pop()
        if (cx, cy) in visited:
            continue
        if not (0 <= cx < w and 0 <= cy < h):
            continue
        if frame.pixels[cy][cx] != target:
            continue
        visited.add((cx, cy))
        frame.pixels[cy][cx] = new_color
        stack.extend([(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)])


def circle(frame: Frame, cx: int, cy: int, r: int, color: PixelColor) -> None:
    """Midpoint circle algorithm — outline only."""
    def _plot(x: int, y: int) -> None:
        if 0 <= x < frame.width and 0 <= y < frame.height:
            frame.pixels[y][x] = color

    x, y = 0, r
    d = 1 - r
    while x <= y:
        for px, py in [
            (cx + x, cy + y), (cx - x, cy + y),
            (cx + x, cy - y), (cx - x, cy - y),
            (cx + y, cy + x), (cx - y, cy + x),
            (cx + y, cy - x), (cx - y, cy - x),
        ]:
            _plot(px, py)
        if d < 0:
            d += 2 * x + 3
        else:
            d += 2 * (x - y) + 5
            y -= 1
        x += 1


def fill_circle(frame: Frame, cx: int, cy: int, r: int, color: PixelColor) -> None:
    """Filled circle."""
    for y in range(max(0, cy - r), min(frame.height, cy + r + 1)):
        for x in range(max(0, cx - r), min(frame.width, cx + r + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                frame.pixels[y][x] = color
