"""Drawing primitives operating on Frame objects."""
from __future__ import annotations
from shared.protocol import Frame
from shared.color import PixelColor


def _lerp_channel(a: int, b: int, t: float) -> int:
    return max(0, min(255, round(a + (b - a) * t)))


def _lerp_color(c1: PixelColor, c2: PixelColor, t: float) -> PixelColor:
    return PixelColor(
        _lerp_channel(c1.r, c2.r, t),
        _lerp_channel(c1.g, c2.g, t),
        _lerp_channel(c1.b, c2.b, t),
        _lerp_channel(c1.a, c2.a, t),
    )


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


def gradient_rect(
    frame: Frame,
    x: int,
    y: int,
    w: int,
    h: int,
    start_color: PixelColor,
    end_color: PixelColor,
    direction: str = "horizontal",
) -> None:
    x2 = min(x + w, frame.width)
    y2 = min(y + h, frame.height)
    x1 = max(0, x)
    y1 = max(0, y)
    if x1 >= x2 or y1 >= y2:
        return

    direction = direction.lower()
    width = max(1, x2 - x1 - 1)
    height = max(1, y2 - y1 - 1)

    for py in range(y1, y2):
        for px in range(x1, x2):
            if direction == "vertical":
                t = (py - y1) / height
            elif direction == "diagonal":
                t = ((px - x1) / width + (py - y1) / height) / 2
            else:
                t = (px - x1) / width
            frame.pixels[py][px] = _lerp_color(start_color, end_color, t)


def paste_rgba_image(frame: Frame, image, dest_x: int, dest_y: int) -> int:
    """Paste PIL RGBA image into frame, alpha-blended. Returns changed pixel count."""
    changed = 0
    src = image.convert("RGBA")
    for sy in range(src.height):
        for sx in range(src.width):
            dx = dest_x + sx
            dy = dest_y + sy
            if not (0 <= dx < frame.width and 0 <= dy < frame.height):
                continue
            r, g, b, a = src.getpixel((sx, sy))
            if a == 0:
                continue
            frame.pixels[dy][dx] = PixelColor(r, g, b, a)
            changed += 1
    return changed
