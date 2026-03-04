"""Command registry and handlers for pxart server."""
from __future__ import annotations
import copy
import json
from typing import Callable

from shared.protocol import ok_response, error_response, Frame, Project
from shared.color import parse_color, TRANSPARENT
from server import drawing, export, rendering
from server.canvas import CanvasState

# Type alias
Handler = Callable[[CanvasState, list[str]], dict]
REGISTRY: dict[str, Handler] = {}


def register(name: str):
    def decorator(fn: Handler) -> Handler:
        REGISTRY[name] = fn
        return fn
    return decorator


def dispatch(state: CanvasState, cmd: str, args: list[str], frame_override: int | None = None, actor: str = "cli") -> dict:
    handler = REGISTRY.get(cmd)
    if not handler:
        return error_response("invalid_command", f"Unknown command: '{cmd}'. Run 'python pxart.py help' for a list.")

    # If frame_override given, temporarily change active frame
    if frame_override is not None:
        with state.lock:
            old_idx = state.project.active_frame_index
            if not (0 <= frame_override < len(state.project.frames)):
                return error_response("invalid_frame", f"Frame {frame_override} does not exist")
            state.project.active_frame_index = frame_override

    result = handler(state, args)

    if result.get("status") == "ok":
        state.record_activity(actor, cmd, args)

    if frame_override is not None:
        with state.lock:
            state.project.active_frame_index = old_idx

    return result


# ─────────────────────────── helpers ──────────────────────────────

def _parse_int(s: str, name: str = "value") -> tuple[int, str | None]:
    try:
        return int(s), None
    except ValueError:
        return 0, f"'{name}' must be an integer, got: {s!r}"


def _parse_color(s: str) -> tuple[object, str | None]:
    c = parse_color(s)
    if c is None:
        return None, f"Invalid color: {s!r}. Use #rgb, #rrggbb, #rrggbbaa or a named color."
    return c, None


# ─────────────────────────── STATUS ────────────────────────────────

@register("status")
def cmd_status(state: CanvasState, args: list[str]) -> dict:
    with state.lock:
        p = state.project
        return ok_response({
            "name": p.name,
            "size": f"{p.width}x{p.height}",
            "frames": len(p.frames),
            "active_frame": p.active_frame_index,
            "fps": p.fps,
        })


@register("help")
def cmd_help(state: CanvasState, args: list[str]) -> dict:
    commands = sorted(REGISTRY.keys())
    return ok_response({"commands": commands})


# ─────────────────────────── DRAWING ───────────────────────────────

@register("set_pixel")
def cmd_set_pixel(state: CanvasState, args: list[str]) -> dict:
    if len(args) != 3:
        return error_response("invalid_args", "Usage: set_pixel <x> <y> <color>")
    x, ex = _parse_int(args[0], "x")
    if ex: return error_response("invalid_args", ex)
    y, ey = _parse_int(args[1], "y")
    if ey: return error_response("invalid_args", ey)
    color, ec = _parse_color(args[2])
    if ec: return error_response("invalid_color", ec)

    with state.lock:
        frame = state.active_frame
        if not (0 <= x < frame.width and 0 <= y < frame.height):
            return error_response("out_of_bounds", f"({x},{y}) is outside {frame.width}x{frame.height}")
        frame.push_undo()
        drawing.set_pixel(frame, x, y, color)
        state.mark_dirty()
    return ok_response({"x": x, "y": y, "color": color.to_hex()})


@register("get_pixel")
def cmd_get_pixel(state: CanvasState, args: list[str]) -> dict:
    if len(args) != 2:
        return error_response("invalid_args", "Usage: get_pixel <x> <y>")
    x, ex = _parse_int(args[0], "x")
    if ex: return error_response("invalid_args", ex)
    y, ey = _parse_int(args[1], "y")
    if ey: return error_response("invalid_args", ey)

    with state.lock:
        frame = state.active_frame
        if not (0 <= x < frame.width and 0 <= y < frame.height):
            return error_response("out_of_bounds", f"({x},{y}) is outside {frame.width}x{frame.height}")
        color = frame.pixels[y][x]
    return ok_response({"x": x, "y": y, "color": color.to_hex()})


@register("set_pixels")
def cmd_set_pixels(state: CanvasState, args: list[str]) -> dict:
    """Batch set pixels. Args: JSON array [[x,y,color], ...]"""
    if len(args) != 1:
        return error_response("invalid_args", "Usage: set_pixels '[[x,y,color], ...]'")
    try:
        batch = json.loads(args[0])
        if not isinstance(batch, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        return error_response("invalid_args", "Expected JSON array of [x, y, color] triples")

    parsed = []
    for item in batch:
        if len(item) != 3:
            return error_response("invalid_args", f"Each item must be [x, y, color], got: {item}")
        x, ex = _parse_int(str(item[0]), "x")
        if ex: return error_response("invalid_args", ex)
        y, ey = _parse_int(str(item[1]), "y")
        if ey: return error_response("invalid_args", ey)
        color, ec = _parse_color(str(item[2]))
        if ec: return error_response("invalid_color", ec)
        parsed.append((x, y, color))

    with state.lock:
        frame = state.active_frame
        # Single undo entry for whole batch
        frame.push_undo()
        oob = []
        for x, y, color in parsed:
            if 0 <= x < frame.width and 0 <= y < frame.height:
                drawing.set_pixel(frame, x, y, color)
            else:
                oob.append((x, y))
        state.mark_dirty()

    result = {"count": len(parsed)}
    if oob:
        result["out_of_bounds"] = oob
    return ok_response(result)


@register("fill_rect")
def cmd_fill_rect(state: CanvasState, args: list[str]) -> dict:
    if len(args) != 5:
        return error_response("invalid_args", "Usage: fill_rect <x> <y> <w> <h> <color>")
    x, ex = _parse_int(args[0], "x");
    if ex: return error_response("invalid_args", ex)
    y, ey = _parse_int(args[1], "y");
    if ey: return error_response("invalid_args", ey)
    w, ew = _parse_int(args[2], "w");
    if ew: return error_response("invalid_args", ew)
    h, eh = _parse_int(args[3], "h");
    if eh: return error_response("invalid_args", eh)
    color, ec = _parse_color(args[4]);
    if ec: return error_response("invalid_color", ec)

    with state.lock:
        frame = state.active_frame
        frame.push_undo()
        drawing.fill_rect(frame, x, y, w, h, color)
        state.mark_dirty()
    return ok_response({"x": x, "y": y, "w": w, "h": h, "color": color.to_hex()})


@register("draw_rect")
def cmd_draw_rect(state: CanvasState, args: list[str]) -> dict:
    if len(args) != 5:
        return error_response("invalid_args", "Usage: draw_rect <x> <y> <w> <h> <color>")
    x, ex = _parse_int(args[0], "x");
    if ex: return error_response("invalid_args", ex)
    y, ey = _parse_int(args[1], "y");
    if ey: return error_response("invalid_args", ey)
    w, ew = _parse_int(args[2], "w");
    if ew: return error_response("invalid_args", ew)
    h, eh = _parse_int(args[3], "h");
    if eh: return error_response("invalid_args", eh)
    color, ec = _parse_color(args[4]);
    if ec: return error_response("invalid_color", ec)

    with state.lock:
        frame = state.active_frame
        frame.push_undo()
        drawing.draw_rect(frame, x, y, w, h, color)
        state.mark_dirty()
    return ok_response({"x": x, "y": y, "w": w, "h": h, "color": color.to_hex()})


@register("line")
def cmd_line(state: CanvasState, args: list[str]) -> dict:
    if len(args) != 5:
        return error_response("invalid_args", "Usage: line <x1> <y1> <x2> <y2> <color>")
    x1, e = _parse_int(args[0], "x1");
    if e: return error_response("invalid_args", e)
    y1, e = _parse_int(args[1], "y1");
    if e: return error_response("invalid_args", e)
    x2, e = _parse_int(args[2], "x2");
    if e: return error_response("invalid_args", e)
    y2, e = _parse_int(args[3], "y2");
    if e: return error_response("invalid_args", e)
    color, ec = _parse_color(args[4]);
    if ec: return error_response("invalid_color", ec)

    with state.lock:
        frame = state.active_frame
        frame.push_undo()
        drawing.line(frame, x1, y1, x2, y2, color)
        state.mark_dirty()
    return ok_response({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": color.to_hex()})


@register("fill")
def cmd_fill(state: CanvasState, args: list[str]) -> dict:
    if len(args) != 3:
        return error_response("invalid_args", "Usage: fill <x> <y> <color>")
    x, ex = _parse_int(args[0], "x");
    if ex: return error_response("invalid_args", ex)
    y, ey = _parse_int(args[1], "y");
    if ey: return error_response("invalid_args", ey)
    color, ec = _parse_color(args[2]);
    if ec: return error_response("invalid_color", ec)

    with state.lock:
        frame = state.active_frame
        if not (0 <= x < frame.width and 0 <= y < frame.height):
            return error_response("out_of_bounds", f"({x},{y}) is outside canvas")
        frame.push_undo()
        drawing.flood_fill(frame, x, y, color)
        state.mark_dirty()
    return ok_response({"x": x, "y": y, "color": color.to_hex()})


@register("circle")
def cmd_circle(state: CanvasState, args: list[str]) -> dict:
    if len(args) != 4:
        return error_response("invalid_args", "Usage: circle <cx> <cy> <r> <color>")
    cx, e = _parse_int(args[0], "cx");
    if e: return error_response("invalid_args", e)
    cy, e = _parse_int(args[1], "cy");
    if e: return error_response("invalid_args", e)
    r, e = _parse_int(args[2], "r");
    if e: return error_response("invalid_args", e)
    color, ec = _parse_color(args[3]);
    if ec: return error_response("invalid_color", ec)

    with state.lock:
        frame = state.active_frame
        frame.push_undo()
        drawing.circle(frame, cx, cy, r, color)
        state.mark_dirty()
    return ok_response({"cx": cx, "cy": cy, "r": r, "color": color.to_hex()})


@register("fill_circle")
def cmd_fill_circle(state: CanvasState, args: list[str]) -> dict:
    if len(args) != 4:
        return error_response("invalid_args", "Usage: fill_circle <cx> <cy> <r> <color>")
    cx, e = _parse_int(args[0], "cx");
    if e: return error_response("invalid_args", e)
    cy, e = _parse_int(args[1], "cy");
    if e: return error_response("invalid_args", e)
    r, e = _parse_int(args[2], "r");
    if e: return error_response("invalid_args", e)
    color, ec = _parse_color(args[3]);
    if ec: return error_response("invalid_color", ec)

    with state.lock:
        frame = state.active_frame
        frame.push_undo()
        drawing.fill_circle(frame, cx, cy, r, color)
        state.mark_dirty()
    return ok_response({"cx": cx, "cy": cy, "r": r, "color": color.to_hex()})


@register("clear")
def cmd_clear(state: CanvasState, args: list[str]) -> dict:
    color = TRANSPARENT
    if args:
        color, ec = _parse_color(args[0])
        if ec: return error_response("invalid_color", ec)

    with state.lock:
        frame = state.active_frame
        frame.push_undo()
        drawing.fill_rect(frame, 0, 0, frame.width, frame.height, color)
        state.mark_dirty()
    return ok_response({"color": color.to_hex()})


@register("clear_frame")
def cmd_clear_frame(state: CanvasState, args: list[str]) -> dict:
    if not args:
        return error_response("invalid_args", "Usage: clear_frame <index> [color]")
    idx, e = _parse_int(args[0], "index")
    if e: return error_response("invalid_args", e)
    color = TRANSPARENT
    if len(args) > 1:
        color, ec = _parse_color(args[1])
        if ec: return error_response("invalid_color", ec)

    with state.lock:
        if not (0 <= idx < len(state.project.frames)):
            return error_response("invalid_frame", f"Frame {idx} does not exist")
        frame = state.project.frames[idx]
        frame.push_undo()
        drawing.fill_rect(frame, 0, 0, frame.width, frame.height, color)
        state.mark_dirty()
    return ok_response({"frame": idx, "color": color.to_hex()})


# ─────────────────────────── UNDO/REDO ─────────────────────────────

@register("undo")
def cmd_undo(state: CanvasState, args: list[str]) -> dict:
    n = 1
    if args:
        n, e = _parse_int(args[0], "n")
        if e: return error_response("invalid_args", e)

    with state.lock:
        frame = state.active_frame
        count = 0
        for _ in range(n):
            if frame.undo():
                count += 1
            else:
                break
        if count == 0:
            return error_response("no_history", "Nothing to undo")
        state.mark_dirty()
    return ok_response({"undone": count})


@register("redo")
def cmd_redo(state: CanvasState, args: list[str]) -> dict:
    n = 1
    if args:
        n, e = _parse_int(args[0], "n")
        if e: return error_response("invalid_args", e)

    with state.lock:
        frame = state.active_frame
        count = 0
        for _ in range(n):
            if frame.redo():
                count += 1
            else:
                break
        if count == 0:
            return error_response("no_history", "Nothing to redo")
        state.mark_dirty()
    return ok_response({"redone": count})


# ─────────────────────────── FRAMES ────────────────────────────────

@register("new_frame")
def cmd_new_frame(state: CanvasState, args: list[str]) -> dict:
    with state.lock:
        p = state.project
        new_idx = len(p.frames)
        p.frames.append(Frame.blank(new_idx, p.width, p.height))
        p.active_frame_index = new_idx
        state.mark_dirty()
    return ok_response({"frame_index": new_idx, "total_frames": len(state.project.frames)})


@register("dup_frame")
def cmd_dup_frame(state: CanvasState, args: list[str]) -> dict:
    with state.lock:
        p = state.project
        src_idx = p.active_frame_index
        if args:
            src_idx, e = _parse_int(args[0], "src_index")
            if e: return error_response("invalid_args", e)
        if not (0 <= src_idx < len(p.frames)):
            return error_response("invalid_frame", f"Frame {src_idx} does not exist")
        new_idx = len(p.frames)
        p.frames.append(p.frames[src_idx].clone(new_idx))
        p.active_frame_index = new_idx
        state.mark_dirty()
    return ok_response({"frame_index": new_idx, "total_frames": len(state.project.frames)})


@register("del_frame")
def cmd_del_frame(state: CanvasState, args: list[str]) -> dict:
    with state.lock:
        p = state.project
        if len(p.frames) <= 1:
            return error_response("invalid_args", "Cannot delete the last frame")
        idx = p.active_frame_index
        if args:
            idx, e = _parse_int(args[0], "index")
            if e: return error_response("invalid_args", e)
        if not (0 <= idx < len(p.frames)):
            return error_response("invalid_frame", f"Frame {idx} does not exist")
        p.frames.pop(idx)
        # Re-index remaining frames
        for i, f in enumerate(p.frames):
            f.index = i
        p.active_frame_index = min(p.active_frame_index, len(p.frames) - 1)
        state.mark_dirty()
    return ok_response({"deleted": idx, "total_frames": len(state.project.frames)})


@register("set_active_frame")
def cmd_set_active_frame(state: CanvasState, args: list[str]) -> dict:
    if not args:
        return error_response("invalid_args", "Usage: set_active_frame <index>")
    idx, e = _parse_int(args[0], "index")
    if e: return error_response("invalid_args", e)

    with state.lock:
        if not (0 <= idx < len(state.project.frames)):
            return error_response("invalid_frame", f"Frame {idx} does not exist")
        state.project.active_frame_index = idx
        state.mark_dirty()
    return ok_response({"active_frame": idx})


@register("get_active_frame")
def cmd_get_active_frame(state: CanvasState, args: list[str]) -> dict:
    with state.lock:
        return ok_response({"active_frame": state.project.active_frame_index})


@register("set_fps")
def cmd_set_fps(state: CanvasState, args: list[str]) -> dict:
    if not args:
        return error_response("invalid_args", "Usage: set_fps <n>")
    n, e = _parse_int(args[0], "fps")
    if e: return error_response("invalid_args", e)
    if not (1 <= n <= 120):
        return error_response("invalid_args", "FPS must be 1-120")

    with state.lock:
        state.project.fps = n
        state.mark_dirty()
    return ok_response({"fps": n})


@register("resize_canvas")
def cmd_resize_canvas(state: CanvasState, args: list[str]) -> dict:
    if len(args) != 2:
        return error_response("invalid_args", "Usage: resize_canvas <w> <h>")
    w, ew = _parse_int(args[0], "w")
    if ew: return error_response("invalid_args", ew)
    h, eh = _parse_int(args[1], "h")
    if eh: return error_response("invalid_args", eh)
    if w <= 0 or h <= 0 or w > 1024 or h > 1024:
        return error_response("invalid_args", "Canvas size must be 1-1024")

    with state.lock:
        p = state.project
        for frame in p.frames:
            frame.resize(w, h)
        p.width = w
        p.height = h
        state.mark_dirty()
    return ok_response({"width": w, "height": h})


# ─────────────────────────── EXPORT / SAVE ─────────────────────────

@register("export_png")
def cmd_export_png(state: CanvasState, args: list[str]) -> dict:
    if not args:
        return error_response("invalid_args", "Usage: export_png <path> [frame_index]")
    path = args[0]
    frame_idx = None
    if len(args) > 1:
        frame_idx, e = _parse_int(args[1], "frame_index")
        if e: return error_response("invalid_args", e)

    with state.lock:
        project_copy = copy.deepcopy(state.project)

    try:
        result_path = export.export_png(project_copy, path, frame_idx)
    except ImportError:
        return error_response("pillow_missing", "Pillow not installed. Run: pip install pillow")
    except Exception as exc:
        return error_response("io_error", str(exc))
    return ok_response({"path": result_path})


@register("export_spritesheet")
def cmd_export_spritesheet(state: CanvasState, args: list[str]) -> dict:
    # Usage: export_spritesheet <path> [--columns N]
    if not args:
        return error_response("invalid_args", "Usage: export_spritesheet <path> [--columns N]")
    path = args[0]
    columns = 0
    i = 1
    while i < len(args):
        if args[i] == "--columns" and i + 1 < len(args):
            columns, e = _parse_int(args[i + 1], "columns")
            if e: return error_response("invalid_args", e)
            i += 2
        else:
            i += 1

    with state.lock:
        project_copy = copy.deepcopy(state.project)

    try:
        result_path = export.export_spritesheet(project_copy, path, columns)
    except ImportError:
        return error_response("pillow_missing", "Pillow not installed. Run: pip install pillow")
    except Exception as exc:
        return error_response("io_error", str(exc))
    return ok_response({"path": result_path, "frames": len(project_copy.frames)})


@register("export_gif")
def cmd_export_gif(state: CanvasState, args: list[str]) -> dict:
    if not args:
        return error_response("invalid_args", "Usage: export_gif <path> [--fps N]")
    path = args[0]
    fps = None
    i = 1
    while i < len(args):
        if args[i] == "--fps" and i + 1 < len(args):
            fps, e = _parse_int(args[i + 1], "fps")
            if e: return error_response("invalid_args", e)
            i += 2
        else:
            i += 1

    with state.lock:
        project_copy = copy.deepcopy(state.project)

    try:
        result_path = export.export_gif(project_copy, path, fps)
    except ImportError:
        return error_response("pillow_missing", "Pillow not installed. Run: pip install pillow")
    except Exception as exc:
        return error_response("io_error", str(exc))
    return ok_response({"path": result_path})


@register("save")
def cmd_save(state: CanvasState, args: list[str]) -> dict:
    path = args[0] if args else None
    try:
        result_path = state.save(path)
    except Exception as exc:
        return error_response("io_error", str(exc))
    return ok_response({"path": result_path})


@register("load")
def cmd_load(state: CanvasState, args: list[str]) -> dict:
    if not args:
        return error_response("invalid_args", "Usage: load <path>")
    try:
        state.load(args[0])
    except FileNotFoundError:
        return error_response("io_error", f"File not found: {args[0]}")
    except Exception as exc:
        return error_response("io_error", str(exc))
    return ok_response({"path": args[0], "frames": len(state.project.frames)})


# ─────────────────────────── PALETTE ───────────────────────────────

@register("palette_add")
def cmd_palette_add(state: CanvasState, args: list[str]) -> dict:
    if not args:
        return error_response("invalid_args", "Usage: palette_add <color>")
    color, ec = _parse_color(args[0])
    if ec: return error_response("invalid_color", ec)

    with state.lock:
        if color not in state.project.palette:
            state.project.palette.append(color)
        state.mark_dirty()
    return ok_response({"color": color.to_hex(), "palette_size": len(state.project.palette)})


@register("palette_clear")
def cmd_palette_clear(state: CanvasState, args: list[str]) -> dict:
    with state.lock:
        state.project.palette.clear()
        state.mark_dirty()
    return ok_response({})


@register("palette_get")
def cmd_palette_get(state: CanvasState, args: list[str]) -> dict:
    with state.lock:
        palette = [c.to_hex() for c in state.project.palette]
    return ok_response({"palette": palette})


@register("palette_set")
def cmd_palette_set(state: CanvasState, args: list[str]) -> dict:
    if not args:
        return error_response("invalid_args", "Usage: palette_set '<json_array>'")
    try:
        colors_raw = json.loads(args[0])
        if not isinstance(colors_raw, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        return error_response("invalid_args", "Expected JSON array of color strings")

    palette = []
    for c in colors_raw:
        color, ec = _parse_color(str(c))
        if ec: return error_response("invalid_color", ec)
        palette.append(color)

    with state.lock:
        state.project.palette = palette
        state.mark_dirty()
    return ok_response({"palette_size": len(palette)})


@register("gradient_rect")
def cmd_gradient_rect(state: CanvasState, args: list[str]) -> dict:
    if len(args) < 6:
        return error_response("invalid_args", "Usage: gradient_rect <x> <y> <w> <h> <start_color> <end_color> [direction]")
    x, ex = _parse_int(args[0], "x")
    if ex: return error_response("invalid_args", ex)
    y, ey = _parse_int(args[1], "y")
    if ey: return error_response("invalid_args", ey)
    w, ew = _parse_int(args[2], "w")
    if ew: return error_response("invalid_args", ew)
    h, eh = _parse_int(args[3], "h")
    if eh: return error_response("invalid_args", eh)
    start_color, es = _parse_color(args[4])
    if es: return error_response("invalid_color", es)
    end_color, ee = _parse_color(args[5])
    if ee: return error_response("invalid_color", ee)
    direction = args[6].lower() if len(args) > 6 else "horizontal"
    if direction not in {"horizontal", "vertical", "diagonal"}:
        return error_response("invalid_args", "direction must be horizontal|vertical|diagonal")

    with state.lock:
        frame = state.active_frame
        frame.push_undo()
        drawing.gradient_rect(frame, x, y, w, h, start_color, end_color, direction)
        state.mark_dirty()
    return ok_response({"x": x, "y": y, "w": w, "h": h, "direction": direction})


@register("set_background_reference")
def cmd_set_background_reference(state: CanvasState, args: list[str]) -> dict:
    if not args:
        return error_response("invalid_args", "Usage: set_background_reference <path> [opacity] [offset_x] [offset_y]")
    path = args[0]
    opacity = 0.45
    offset_x = 0
    offset_y = 0
    if len(args) > 1:
        try:
            opacity = float(args[1])
        except ValueError:
            return error_response("invalid_args", "opacity must be float (0..1)")
    if len(args) > 2:
        offset_x, ex = _parse_int(args[2], "offset_x")
        if ex: return error_response("invalid_args", ex)
    if len(args) > 3:
        offset_y, ey = _parse_int(args[3], "offset_y")
        if ey: return error_response("invalid_args", ey)

    try:
        from PIL import Image
        image = Image.open(path).convert("RGBA")
    except ImportError:
        return error_response("pillow_missing", "Pillow not installed. Run: pip install pillow")
    except Exception as exc:
        return error_response("io_error", str(exc))

    with state.lock:
        state.set_background_reference(image, path, opacity, offset_x, offset_y)
    return ok_response({"path": path, "opacity": opacity, "offset_x": offset_x, "offset_y": offset_y})


@register("clear_background_reference")
def cmd_clear_background_reference(state: CanvasState, args: list[str]) -> dict:
    with state.lock:
        state.clear_background_reference()
    return ok_response({})


@register("paste_image_region")
def cmd_paste_image_region(state: CanvasState, args: list[str]) -> dict:
    if len(args) != 7:
        return error_response("invalid_args", "Usage: paste_image_region <path> <src_x> <src_y> <w> <h> <dest_x> <dest_y>")
    path = args[0]
    src_x, ex = _parse_int(args[1], "src_x")
    if ex: return error_response("invalid_args", ex)
    src_y, ey = _parse_int(args[2], "src_y")
    if ey: return error_response("invalid_args", ey)
    w, ew = _parse_int(args[3], "w")
    if ew: return error_response("invalid_args", ew)
    h, eh = _parse_int(args[4], "h")
    if eh: return error_response("invalid_args", eh)
    dest_x, edx = _parse_int(args[5], "dest_x")
    if edx: return error_response("invalid_args", edx)
    dest_y, edy = _parse_int(args[6], "dest_y")
    if edy: return error_response("invalid_args", edy)

    try:
        from PIL import Image
        image = Image.open(path).convert("RGBA")
        crop = image.crop((src_x, src_y, src_x + w, src_y + h))
    except ImportError:
        return error_response("pillow_missing", "Pillow not installed. Run: pip install pillow")
    except Exception as exc:
        return error_response("io_error", str(exc))

    with state.lock:
        frame = state.active_frame
        frame.push_undo()
        changed = drawing.paste_rgba_image(frame, crop, dest_x, dest_y)
        state.mark_dirty()
    return ok_response({"pixels_changed": changed, "dest_x": dest_x, "dest_y": dest_y})


@register("capture_screenshot")
def cmd_capture_screenshot(state: CanvasState, args: list[str]) -> dict:
    if not args:
        return error_response("invalid_args", "Usage: capture_screenshot <path> [zoom]")
    path = args[0]
    zoom = 8
    if len(args) > 1:
        zoom, ez = _parse_int(args[1], "zoom")
        if ez: return error_response("invalid_args", ez)

    try:
        result_path = rendering.save_state_screenshot(state, path, zoom=zoom)
    except ImportError:
        return error_response("pillow_missing", "Pillow not installed. Run: pip install pillow")
    except Exception as exc:
        return error_response("io_error", str(exc))
    return ok_response({"path": result_path})


# ─────────────────────────── STOP ──────────────────────────────────

@register("stop")
def cmd_stop(state: CanvasState, args: list[str]) -> dict:
    # The actual shutdown is handled in daemon.py after it sees this response.
    return ok_response({"message": "Shutting down..."})
