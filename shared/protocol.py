"""Data model: PixelColor, Frame, Project — shared between server and client."""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import Any

from shared.color import PixelColor, TRANSPARENT

MAX_UNDO = 50


@dataclass
class Frame:
    index: int
    width: int
    height: int
    pixels: list[list[PixelColor]]
    undo_stack: list[list[list[PixelColor]]] = field(default_factory=list)
    redo_stack: list[list[list[PixelColor]]] = field(default_factory=list)

    @classmethod
    def blank(cls, index: int, width: int, height: int, fill: PixelColor = TRANSPARENT) -> "Frame":
        pixels = [[fill for _ in range(width)] for _ in range(height)]
        return cls(index=index, width=width, height=height, pixels=pixels)

    def push_undo(self) -> None:
        """Snapshot current pixels for undo."""
        snapshot = copy.deepcopy(self.pixels)
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(copy.deepcopy(self.pixels))
        self.pixels = self.undo_stack.pop()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(copy.deepcopy(self.pixels))
        self.pixels = self.redo_stack.pop()
        return True

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "pixels": [
                [px.to_hex() for px in row]
                for row in self.pixels
            ],
        }

    @classmethod
    def from_dict(cls, d: dict, width: int, height: int) -> "Frame":
        from shared.color import parse_color
        pixels = []
        for row in d["pixels"]:
            pixels.append([parse_color(c) or TRANSPARENT for c in row])
        return cls(
            index=d["index"],
            width=width,
            height=height,
            pixels=pixels,
        )

    def clone(self, new_index: int) -> "Frame":
        return Frame(
            index=new_index,
            width=self.width,
            height=self.height,
            pixels=copy.deepcopy(self.pixels),
        )

    def resize(self, new_w: int, new_h: int, fill: PixelColor = TRANSPARENT) -> None:
        """Resize in-place: crops or pads with fill."""
        new_pixels = []
        for y in range(new_h):
            row = []
            for x in range(new_w):
                if y < self.height and x < self.width:
                    row.append(self.pixels[y][x])
                else:
                    row.append(fill)
            new_pixels.append(row)
        self.pixels = new_pixels
        self.width = new_w
        self.height = new_h
        self.undo_stack.clear()
        self.redo_stack.clear()


@dataclass
class Project:
    name: str
    width: int
    height: int
    frames: list[Frame]
    active_frame_index: int = 0
    fps: int = 12
    palette: list[PixelColor] = field(default_factory=list)

    @classmethod
    def new(cls, name: str = "untitled", width: int = 64, height: int = 64, fps: int = 12) -> "Project":
        frame = Frame.blank(0, width, height)
        return cls(name=name, width=width, height=height, frames=[frame], fps=fps)

    @property
    def active_frame(self) -> Frame:
        return self.frames[self.active_frame_index]

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "active_frame_index": self.active_frame_index,
            "palette": [c.to_hex() for c in self.palette],
            "frames": [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        from shared.color import parse_color
        width, height = d["width"], d["height"]
        frames = [Frame.from_dict(fd, width, height) for fd in d["frames"]]
        palette = [parse_color(c) or TRANSPARENT for c in d.get("palette", [])]
        return cls(
            name=d.get("name", "untitled"),
            width=width,
            height=height,
            frames=frames,
            active_frame_index=d.get("active_frame_index", 0),
            fps=d.get("fps", 12),
            palette=palette,
        )


# ---------- Wire protocol helpers ----------

def ok_response(data: Any = None) -> dict:
    return {"status": "ok", "data": data or {}}


def error_response(code: str, message: str) -> dict:
    return {"status": "error", "code": code, "message": message}
