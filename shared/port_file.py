"""Port file management for Windows: %LOCALAPPDATA%\\pxart\\server.port"""
from __future__ import annotations
import os
import pathlib


def _port_file_path() -> pathlib.Path:
    base = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("APPDATA")
        or os.environ.get("TEMP")
        or "."
    )
    d = pathlib.Path(base) / "pxart"
    d.mkdir(parents=True, exist_ok=True)
    return d / "server.port"


def write_port(port: int) -> None:
    _port_file_path().write_text(str(port), encoding="utf-8")


def read_port() -> int | None:
    p = _port_file_path()
    if not p.exists():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def delete_port() -> None:
    try:
        _port_file_path().unlink(missing_ok=True)
    except OSError:
        pass


def port_file_path_str() -> str:
    return str(_port_file_path())
