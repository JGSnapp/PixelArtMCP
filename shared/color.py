"""Color parsing utilities for pxart."""
from __future__ import annotations
from dataclasses import dataclass

NAMED_COLORS: dict[str, tuple[int, int, int, int]] = {
    "black":       (0,   0,   0,   255),
    "white":       (255, 255, 255, 255),
    "red":         (255, 0,   0,   255),
    "green":       (0,   200, 0,   255),
    "blue":        (0,   0,   255, 255),
    "yellow":      (255, 255, 0,   255),
    "orange":      (255, 165, 0,   255),
    "purple":      (128, 0,   128, 255),
    "cyan":        (0,   255, 255, 255),
    "magenta":     (255, 0,   255, 255),
    "gray":        (128, 128, 128, 255),
    "grey":        (128, 128, 128, 255),
    "transparent": (0,   0,   0,   0),
    "lime":        (0,   255, 0,   255),
    "maroon":      (128, 0,   0,   255),
    "navy":        (0,   0,   128, 255),
    "pink":        (255, 192, 203, 255),
    "brown":       (139, 69,  19,  255),
    "gold":        (255, 215, 0,   255),
    "silver":      (192, 192, 192, 255),
    "teal":        (0,   128, 128, 255),
    "darkblue":    (0,   0,   139, 255),
    "darkred":     (139, 0,   0,   255),
    "darkgreen":   (0,   100, 0,   255),
}


@dataclass(eq=True, frozen=True)
class PixelColor:
    r: int
    g: int
    b: int
    a: int = 255

    def to_hex(self) -> str:
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}{self.a:02x}"

    def to_rgba_tuple(self) -> tuple[int, int, int, int]:
        return (self.r, self.g, self.b, self.a)

    def __repr__(self) -> str:
        return self.to_hex()


TRANSPARENT = PixelColor(0, 0, 0, 0)
BLACK = PixelColor(0, 0, 0, 255)
WHITE = PixelColor(255, 255, 255, 255)


def parse_color(s: str) -> PixelColor | None:
    """Parse color string. Returns None on failure.
    Accepts: #rgb, #rgba, #rrggbb, #rrggbbaa, named colors.
    """
    s = s.strip().lower()

    # Named color
    if s in NAMED_COLORS:
        r, g, b, a = NAMED_COLORS[s]
        return PixelColor(r, g, b, a)

    # Hex
    if s.startswith("#"):
        h = s[1:]
        try:
            if len(h) == 3:
                r = int(h[0] * 2, 16)
                g = int(h[1] * 2, 16)
                b = int(h[2] * 2, 16)
                return PixelColor(r, g, b, 255)
            elif len(h) == 4:
                r = int(h[0] * 2, 16)
                g = int(h[1] * 2, 16)
                b = int(h[2] * 2, 16)
                a = int(h[3] * 2, 16)
                return PixelColor(r, g, b, a)
            elif len(h) == 6:
                r = int(h[0:2], 16)
                g = int(h[2:4], 16)
                b = int(h[4:6], 16)
                return PixelColor(r, g, b, 255)
            elif len(h) == 8:
                r = int(h[0:2], 16)
                g = int(h[2:4], 16)
                b = int(h[4:6], 16)
                a = int(h[6:8], 16)
                return PixelColor(r, g, b, a)
        except ValueError:
            return None

    # rgb(...) or rgba(...)
    if s.startswith("rgb"):
        import re
        m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)", s)
        if m:
            r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            a = int(float(m.group(4)) * 255) if m.group(4) else 255
            return PixelColor(
                max(0, min(255, r)),
                max(0, min(255, g)),
                max(0, min(255, b)),
                max(0, min(255, a)),
            )

    return None
