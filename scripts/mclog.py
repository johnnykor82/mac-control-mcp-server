#!/usr/bin/env python3
"""mclog — read-only live dashboard for Mac Control audit JSONL."""
import argparse
import collections
import curses
import datetime as dt
import json
import os
from pathlib import Path
import re
import time
import textwrap

DEFAULT_LOG = (Path(os.environ["MAC_CONTROL_DATA_ROOT"]) / "logs"
               if os.environ.get("MAC_CONTROL_DATA_ROOT") else
               Path.home() / "MacControlMCP/data/logs")
SECRET = re.compile(r"(token|secret|password|passwd|api.?key|authorization|cookie|credential|bearer|private.?key)", re.I)


def safe_args(value, limit=80):
    """Render as much as fits, masking credential fields and inline tokens."""
    def compact(obj, depth=0):
        if isinstance(obj, dict):
            pairs = []
            # The command is the most useful part of a terminal operation.
            keys = sorted(obj, key=lambda k: (str(k) not in ("command", "cmd", "operation"), str(k)))
            for key in keys:
                name = str(key)
                if name.lower() in ("timeout", "timeout_seconds"):
                    continue
                if SECRET.search(name) or name.lower() in ("content", "prompt", "text", "script"):
                    val = "[скрыто]"
                elif depth >= 3:
                    val = "{…}"
                else:
                    val = compact(obj[key], depth + 1)
                pairs.append(f"{name}={val}")
            return ", ".join(pairs)
        if isinstance(obj, (tuple, list)):
            if depth >= 3:
                return "[…]"
            return "[" + ", ".join(compact(x, depth + 1) for x in obj[:3]) + (", …" if len(obj) > 3 else "") + "]"
        if obj is None:
            return "null"
        s = str(obj).replace("\n", " ").replace("\r", " ")
        s = re.sub(r"(?i)\b(bearer\s+)\S+", r"\1[скрыто]", s)
        s = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,})\b", "[скрыто]", s)
        return s
    rendered = compact(value)
    if limit <= 0:
        return ""
    return rendered if len(rendered) <= limit else rendered[:max(0, limit - 1)] + "…"


class AuditReader:
    """Incrementally parse audit JSONL files, including rotation and partial writes."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.starts = {}
        self.ends = {}
        self.positions = {}
        self.invalid = 0

    def accept(self, raw):
        try:
            record = json.loads(raw)
            stamp = dt.datetime.fromisoformat(record["time_utc"].replace("Z", "+00:00"))
            ident = record.get("id")
            if not isinstance(ident, str) or not ident:
                raise ValueError("missing request ID")
            kind = record.get("event")
            if kind == "tool_start":
                record.pop("result", None)
                self.starts[ident] = (stamp, record)
            elif kind == "tool_end":
                record.pop("result", None)
                self.ends[ident] = (stamp, record)
        except (ValueError, KeyError, TypeError):
            self.invalid += 1

    def refresh(self, log_dir):
        paths = [p for p in sorted(log_dir.glob("audit.jsonl*")) if p.is_file()]
        known = set(self.positions)
        if known - {str(p) for p in paths}:
            self.reset()
        for path in paths:
            try:
                stat = path.stat()
                old = self.positions.get(str(path))
                if old and (old[0] != stat.st_ino or stat.st_size < old[1] or
                            (stat.st_size == old[1] and stat.st_mtime_ns != old[2])):
                    self.reset()
                    break
            except OSError:
                self.invalid += 1

        for path in paths:
            try:
                stat = path.stat()
                old = self.positions.get(str(path))
                if old and old[1] == stat.st_size:
                    continue
                offset = old[1] if old else 0
                with path.open("rb") as stream:
                    stream.seek(offset)
                    data = stream.read()
                boundary = data.rfind(b"\n")
                if boundary >= 0:
                    for raw in data[:boundary+1].splitlines():
                        if raw.strip():
                            self.accept(raw.decode("utf-8", errors="replace"))
                    offset += boundary + 1
                self.positions[str(path)] = (stat.st_ino, offset, stat.st_mtime_ns)
            except OSError:
                self.invalid += 1

        entries = []
        for ident in self.starts.keys() | self.ends.keys():
            start = self.starts.get(ident)
            end = self.ends.get(ident)
            stamp = start[0] if start else end[0]
            entry = dict(start[1]) if start else {}
            if end:
                entry.update(end[1])
            entry["started"] = stamp
            entry["finished"] = end[0] if end else None
            entry["status"] = str(end[1].get("status", "unknown")) if end else "running"
            entries.append(entry)
        entries.sort(key=lambda item: item["started"], reverse=True)
        return entries, self.invalid


def load(log_dir):
    """One-shot reader retained for tests and diagnostics."""
    return AuditReader().refresh(log_dir)


def display_args(event, limit=80):
    """Show owner-visible task context first, then actual tool parameters."""
    arguments = event.get("arguments")
    context = event.get("audit_context")
    if not isinstance(context, dict) and isinstance(arguments, dict):
        context = arguments.get("audit_context")
    if isinstance(context, dict) and all(
        isinstance(context.get(k), str)
        for k in ("task_id", "action", "authorization_basis")
    ):
        task = safe_args(context["task_id"], 96)
        action = safe_args(context["action"], 512)
        basis = safe_args(context["authorization_basis"], 512)
        base = f"Задача: {task} | Действие: {action} | Основание: {basis}"
        others = (dict(arguments) if isinstance(arguments, dict) else {})
        others.pop("audit_context", None)
        if others:
            base += " | " + safe_args(others, 512)
        return base[:limit - 1] + "…" if limit > 0 and len(base) > limit else base[:max(0, limit)]
    if "arguments" in event and event.get("arguments") is not None:
        payload = event["arguments"]
        return safe_args(payload, limit) if payload != {} else "нет"
    if "argument_info" in event:
        payload = event["argument_info"]
        return safe_args(payload, limit) if isinstance(payload, dict) and payload else "нет"
    return "—"


def is_error(event):
    return str(event.get("status", "")).lower() not in ("ok", "success", "running", "unfinished")


def histogram_cell(level, row):
    """Render one vertically continuous hourly column; one horizontal spacer."""
    return "┃┃┃ " if level >= row else "    "


def argument_segments(value):
    """Split redacted display text into colorable spans without modifying it."""
    if not isinstance(value, str):
        value = str(value)
    if not value:
        return []
    pattern = re.compile(r"((?:[A-Za-z][A-Za-z0-9_-]*=)|(?:Задача: |Действие: |Основание: |Команда: ))")
    pieces = pattern.split(value)
    spans = []
    for part in pieces:
        if not part:
            continue
        if pattern.fullmatch(part):
            spans.append((part, "key"))
            continue
        fragments = re.split(r"(\[скрыто\]|\[REDACTED\])", part)
        for fragment in fragments:
            if fragment:
                spans.append((fragment, "secret" if fragment in ("[скрыто]", "[REDACTED]") else "value"))
    return spans


DISPLAY_MODES = ("compact", "wrap", "detail")
MAX_DISPLAY_ARGUMENTS = 100_000


def audit_fields(event):
    """Return scrubbed task/action/approval and invocation for every audit event."""
    payload = event.get("arguments")
    context = event.get("audit_context")
    if not isinstance(context, dict) and isinstance(payload, dict):
        context = payload.get("audit_context")
    if not isinstance(context, dict):
        context = {}
    task = safe_args(context.get("task_id", "—"), MAX_DISPLAY_ARGUMENTS)
    action = safe_args(context.get("action", "—"), MAX_DISPLAY_ARGUMENTS)
    basis = safe_args(context.get("authorization_basis", "—"), MAX_DISPLAY_ARGUMENTS)
    other = dict(payload) if isinstance(payload, dict) else None
    if other is not None:
        other.pop("audit_context", None)
        if event.get("tool") in ("custom_command", "custom_query") and isinstance(other.get("arguments"), dict):
            other = other["arguments"]
    if other is None:
        command = display_args({"argument_info": event.get("argument_info")}, MAX_DISPLAY_ARGUMENTS) if event.get("argument_info") is not None else "—"
    else:
        command = safe_args(other, MAX_DISPLAY_ARGUMENTS) if other else "нет"
    return task, action, basis, command


def wrap_in_column(value, width, continuation="  "):
    """Wrap word/long-token text; every physical line stays within ARGUMENTS."""
    width = max(1, width)
    value = str(value).replace("\r", " ").replace("\n", " ")
    if not value:
        return [""]
    lines = []
    remaining = value
    first = True
    while remaining:
        prefix = "" if first or width < 4 else continuation
        available = max(1, width - len(prefix))
        if len(remaining) <= available:
            lines.append(prefix + remaining)
            break
        cut = remaining.rfind(" ", 0, available + 1)
        if cut <= 0:
            cut = available
        piece = remaining[:cut].rstrip()
        if not piece:
            cut = available
            piece = remaining[:cut]
        lines.append(prefix + piece)
        remaining = remaining[cut:].lstrip()
        first = False
    return lines


def render_event_arguments(event, width, mode="compact"):
    """Three safely redacted views; detailed wraps ALL four semantic fields."""
    if mode not in DISPLAY_MODES:
        raise ValueError("Unsupported MClog display mode")
    width = max(1, width)
    if mode == "compact":
        return [display_args(event, width)]
    fields = audit_fields(event)
    labels = ("Задача", "Действие", "Основание", "Команда")
    if mode == "wrap":
        combined = " | ".join(f"{label}: {text}" for label, text in zip(labels, fields))
        return wrap_in_column(combined, width)
    rendered = []
    for label, value in zip(labels, fields):
        rendered.extend(wrap_in_column(f"{label}: {value}", width))
    return rendered


def scroll_delta(key, visible):
    """Fast keyboard scrolling by physical rows, no 100ms per keystroke."""
    if key in (curses.KEY_DOWN, ord("j")):
        return 1
    if key in (curses.KEY_UP, ord("k")):
        return -1
    if key == curses.KEY_NPAGE:
        return max(1, visible)
    if key == curses.KEY_PPAGE:
        return -max(1, visible)
    return 0


def wheel_delta(button_state):
    """Supported terminals send curses mouse button 4/5 as wheel events."""
    if button_state & getattr(curses, "BUTTON4_PRESSED", 0):
        return -4
    if button_state & getattr(curses, "BUTTON5_PRESSED", 0):
        return 4
    return 0


def build_physical_rows(events, width, mode):
    """Flatten all records, including their continuation rows, without loss."""
    result = []
    for event in events:
        fragments = render_event_arguments(event, width, mode)
        for index, fragment in enumerate(fragments):
            result.append((event, fragment, index == 0))
    return result


def draw(scr, events, invalid, log_dir, now, offset, errors_only=False,
         mode="compact", cache=None):
    """Render one frame; offset and page size are physical lines, not records."""
    height, width = scr.getmaxyx()
    scr.erase()

    def line(y, content, style=0):
        if 0 <= y < height:
            try:
                scr.addnstr(y, 0, content.ljust(max(0, width - 1)),
                            max(0, width - 1), style)
            except curses.error:
                pass

    if height < 9 or width < 44:
        line(0, "mclog: увеличьте окно терминала (от 44×9)")
        scr.refresh()
        return 0, 0

    bold = curses.A_BOLD
    quiet = curses.color_pair(3)
    muted = curses.color_pair(4)
    recent = [e for e in events if e["started"] >= now - dt.timedelta(hours=1)]
    day = [e for e in events if e["started"] >= now - dt.timedelta(hours=24)]
    bad_hour = sum(is_error(e) for e in recent)
    bad_total = sum(is_error(e) for e in events)
    running = sum(e.get("status") == "running" and e["started"] >=
                  now - dt.timedelta(minutes=10) for e in recent)
    finished = [e for e in recent if e.get("status") != "running"]
    durations = [float(e["duration_ms"]) for e in finished
                 if e.get("duration_ms") is not None]
    mean = sum(durations) / len(durations) / 1000 if durations else 0
    pct = bad_hour / len(recent) * 100 if recent else 0
    line(0, " MAC CONTROL • ЖУРНАЛ   " +
         now.astimezone().strftime("%d.%m.%Y  %H:%M:%S"), muted | bold)
    line(1, f" ЗА ЧАС: {len(recent)} запросов    {bad_hour} ошибок ({pct:.1f}%)    "
            f"{running} выполняется    среднее {mean:.2f} с", quiet)
    line(2, f" 24 ЧАСА: {len(day)} запросов / {sum(is_error(e) for e in day)} ошибок"
            f"     АРХИВ: {len(events)} запросов / {bad_total} ошибок", muted)

    chart_height = min(6, max(3, (height - 18) // 2)) if height >= 18 else 0
    header_y = 4
    if chart_height:
        hours = min(24, max(5, (width - 8) // 4))
        clock = now.replace(minute=0, second=0, microsecond=0)
        slots = [clock - dt.timedelta(hours=i) for i in range(hours-1, -1, -1)]
        counts = collections.Counter(e["started"].replace(minute=0, second=0, microsecond=0)
                                     for e in events)
        faults = collections.Counter(e["started"].replace(minute=0, second=0, microsecond=0)
                                     for e in events if is_error(e))
        peak = max([counts[t] for t in slots] + [1])
        line(3, f" НАГРУЗКА ПО ЧАСАМ • последние {hours} ч    пик {peak} запр./час",
             muted)
        for y in range(chart_height):
            cells = [histogram_cell((counts[t] * chart_height + peak - 1) // peak,
                                    chart_height - y) for t in slots]
            line(4 + y, "     " + "".join(cells), quiet)
        def labels(prefix, fn):
            return f"{prefix:<5}" + "".join(f"{str(fn(t))[:3]:^4}" for t in slots)
        line(4 + chart_height, labels("час", lambda t: t.astimezone().strftime("%H")),
             curses.A_DIM)
        line(5 + chart_height, labels("зап.", lambda t: counts[t]), quiet)
        line(6 + chart_height, labels("ош.", lambda t: faults[t] if faults[t] else "·"),
             curses.color_pair(1))
        header_y = 8 + chart_height

    names = {"compact": "1:одна", "wrap": "2:перенос", "detail": "3:подробно"}
    line(header_y - 1,
         " " + names[mode] + " | m/1/2/3 — режим | e — ошибки | ↑↓/PgUp/PgDn/колесо — "
         "прокрутка | g — начало | G — конец | q — выход", curses.A_DIM)

    has_chat = width >= 95 and any(e.get("chat_ref") for e in events)
    chat_width = 12 if has_chat else 0
    cmd_width = max(12, min(32, width // 4))
    chat_header = f" {'ЧАТ':{chat_width}}" if has_chat else ""
    args_x = 1 + 8 + (1 + chat_width if has_chat else 0) + 1 + cmd_width + 1
    args_width = max(1, width - 1 - args_x - 8)
    line(header_y, f" {'ВРЕМЯ':8}{chat_header} {'КОМАНДА':{cmd_width}} "
         f"{'АРГУМЕНТЫ':{args_width}} ИТОГ", muted | bold)

    filtered = [e for e in events if is_error(e)] if errors_only else events
    key = (id(events), len(events), mode, width, errors_only)
    if cache is not None and cache.get("key") == key:
        physical = cache["rows"]
    else:
        physical = build_physical_rows(filtered, args_width, mode)
        if cache is not None:
            cache.clear()
            cache.update(key=key, rows=physical)

    page_size = max(0, height - header_y - 2)
    offset = max(0, min(offset, max(0, len(physical) - page_size)))
    for j, (event, args, first) in enumerate(physical[offset:offset + page_size]):
        y = header_y + 1 + j
        status = str(event.get("status", "running")).lower()
        result = "OK" if status in ("ok", "success") else (
            "ИДЁТ" if status == "running" else "ОШИБКА")
        status_color = 2 if status in ("ok", "success") else (
            4 if status == "running" else 1)
        command = str(event.get("tool", "?"))
        payload = event.get("arguments")
        if command in ("custom_command", "custom_query") and isinstance(payload, dict):
            command = str(payload.get("operation") or command)
        tm = event["started"].astimezone().strftime("%H:%M:%S") if first else ""
        chat = event.get("chat_ref", "")
        chat_part = (f" {('Чат ' + chat[:8]) if isinstance(chat, str) and chat else '—':{chat_width}}"
                     if has_chat else "")
        label = f" {tm:8}{chat_part} {command[:cmd_width] if first else '':{cmd_width}} "
        line(y, label + args[:args_width].ljust(args_width) +
             (" " + result if first else ""), quiet)
        # A continuation starts at the same fixed ARGUMENTS x, never at the time/tool columns.
        at = args_x
        for span, kind in argument_segments(args):
            if at >= args_x + args_width:
                break
            size = min(len(span), args_x + args_width - at)
            style = {"key": curses.color_pair(5) | bold,
                     "value": curses.color_pair(6),
                     "secret": curses.color_pair(1) | bold}.get(kind, quiet)
            try:
                scr.addnstr(y, at, span[:size], size, style)
            except curses.error:
                break
            at += size
        if first and args_x + args_width + 1 < width - 1:
            try:
                scr.addnstr(y, args_x + args_width + 1, result,
                            max(0, width - args_x - args_width - 2),
                            curses.color_pair(status_color))
            except curses.error:
                pass

    end = min(len(physical), offset + page_size)
    line(height - 1,
         f" Строки {offset+1 if physical else 0}–{end} из {len(physical)}"
         f" | записей {len(filtered)} | режим: {names[mode]} | обновление 2 с",
         curses.A_DIM)
    scr.refresh()
    return offset, min(page_size, max(0, len(physical) - offset))


def main(scr, log_dir, mode="compact"):
    """Input-driven curses loop: batch keys, handle wheel, redraw on change."""
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    scr.nodelay(True)
    scr.keypad(True)
    if curses.has_colors():
        curses.start_color()
        try:
            curses.use_default_colors()
            default_fg = -1
        except curses.error:
            default_fg = curses.COLOR_WHITE
        if getattr(curses, "COLORS", 0) >= 256:
            colors = (174, 108, default_fg, 245, 110, default_fg)
        else:
            colors = (curses.COLOR_RED, curses.COLOR_GREEN, default_fg,
                      default_fg, default_fg, default_fg)
        for i, color in enumerate(colors, 1):
            try:
                curses.init_pair(i, color, -1)
            except curses.error:
                pass
    try:
        curses.mousemask(getattr(curses, "ALL_MOUSE_EVENTS", 0))
    except curses.error:
        pass

    rows, invalid = [], 0
    reader = AuditReader()
    offset = 0
    errors_only = False
    next_refresh = 0
    visible = 1
    cache = {}
    redraw = True
    last_size = None
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        tick = time.monotonic()
        if tick >= next_refresh:
            try:
                rows, invalid = reader.refresh(log_dir)
                next_refresh = tick + 2
                cache.clear()
                redraw = True
            except OSError as exc:
                scr.erase()
                scr.addnstr(0, 0, f"Audit read error: {exc}",
                            max(1, scr.getmaxyx()[1] - 1))
                scr.refresh()
                next_refresh = tick + 2
        if scr.getmaxyx() != last_size:
            last_size = scr.getmaxyx()
            cache.clear()
            redraw = True
        if redraw:
            offset, visible = draw(scr, rows, invalid, log_dir, now, offset,
                                   errors_only, mode=mode, cache=cache)
            redraw = False

        # Consume a burst of up to 512 queued events without a sleep per key.
        # This stays responsive when the user holds an arrow or uses the wheel.
        handled = 0
        while handled < 512:
            key = scr.getch()
            if key == -1:
                break
            handled += 1
            if key in (ord("q"), ord("Q"), 27):
                return
            old_state = (offset, mode, errors_only)
            delta = scroll_delta(key, visible)
            if key == curses.KEY_MOUSE:
                try:
                    _id, _x, _y, _z, button_state = curses.getmouse()
                    delta += wheel_delta(button_state)
                except curses.error:
                    pass
            offset = max(0, offset + delta)
            if key in (curses.KEY_END, ord("G")):
                offset = 10**12  # draw clamps to final viewport, including long records
            elif key in (curses.KEY_HOME, ord("g")):
                offset = 0
            elif key in (ord("e"), ord("E")):
                errors_only = not errors_only
                offset = 0
                cache.clear()
            elif key in (ord("1"), ord("2"), ord("3"), ord("m"), ord("M")):
                if key in (ord("m"), ord("M")):
                    mode = DISPLAY_MODES[(DISPLAY_MODES.index(mode) + 1) % 3]
                else:
                    mode = DISPLAY_MODES[key - ord("1")]
                offset = 0
                cache.clear()
            if key == curses.KEY_RESIZE:
                cache.clear()
                redraw = True
            if (offset, mode, errors_only) != old_state:
                redraw = True
        # Poll at 25ms rather than imposing 100ms per scrolling command.
        if not redraw:
            time.sleep(0.025)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mac Control live terminal audit monitor")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--mode", choices=DISPLAY_MODES, default="compact",
                        help="compact=1 line; wrap=wrapped arguments; detail=4 labelled fields")
    arguments = parser.parse_args()
    curses.wrapper(main, arguments.log_dir.expanduser(), arguments.mode)
