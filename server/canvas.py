"""CanvasState — thread-safe wrapper around Project."""
from __future__ import annotations
import copy
import json
import threading
from pathlib import Path

from ..shared.protocol import Project, Frame
from ..shared.color import PixelColor, TRANSPARENT


class CanvasState:
    """Thread-safe project state shared between TCP server thread and GUI main thread."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.lock = threading.Lock()
        self.dirty = threading.Event()  # set when GUI needs to redraw
        self._save_path: str | None = None

    @classmethod
    def new(cls, name: str = "untitled", width: int = 64, height: int = 64, fps: int = 12) -> "CanvasState":
        return cls(Project.new(name=name, width=width, height=height, fps=fps))

    @classmethod
    def load_file(cls, path: str) -> "CanvasState":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        project = Project.from_dict(data)
        state = cls(project)
        state._save_path = path
        return state

    # ------------------------------------------------------------------
    # Convenience accessors (call under lock)
    # ------------------------------------------------------------------

    @property
    def active_frame(self) -> Frame:
        return self.project.active_frame

    def mark_dirty(self) -> None:
        self.dirty.set()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | None = None) -> str:
        p = path or self._save_path
        if not p:
            p = f"{self.project.name}.pxart"
        Path(p).write_text(
            json.dumps(self.project.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._save_path = p
        return p

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.project = Project.from_dict(data)
        self._save_path = path
        self.mark_dirty()
