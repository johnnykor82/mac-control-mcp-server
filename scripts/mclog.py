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

DEFAULT_LOG = (Path(os.environ["MAC_CONTROL_DATA_ROOT"]) / "logs"
               if os.environ.get("MAC_CONTROL_DATA_ROOT") else
               Path.home() / "Library/Application Support/MacControl/MCPServer/data/logs")
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


def source(event):
    # PID identifies the MCP server, not the calling application.
    for name in ("client_id", "client_name", "client", "source", "origin", "caller"):
        value = event.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return "—"


def is_error(event):
    return str(event.get("status", "")).lower() not in ("ok", "success", "running", "unfinished")


def draw(scr, events, invalid, log_dir, now, offset, errors_only=False):
    height, width = scr.getmaxyx()
    scr.erase()
    def line(y, content, style=0):
        if 0 <= y < height:
            try:
                scr.addnstr(y, 0, content.ljust(max(0, width - 1)), max(0, width - 1), style)
            except curses.error:
                pass
    if height < 9 or width < 44:
        line(0, "mclog: увеличьте окно терминала (от 44×9)")
        scr.refresh()
        return 0, 0

    bold = curses.A_BOLD
    recent = [e for e in events if e["started"] >= now - dt.timedelta(hours=1)]
    day = [e for e in events if e["started"] >= now - dt.timedelta(hours=24)]
    bad_hour = sum(is_error(e) for e in recent)
    bad_day = sum(is_error(e) for e in day)
    bad_total = sum(is_error(e) for e in events)
    running = sum(e.get("status") == "running" and e["started"] >= now - dt.timedelta(minutes=10) for e in recent)
    done = [e for e in recent if e.get("status") != "running"]
    durations = [float(e["duration_ms"]) for e in done if e.get("duration_ms") is not None]
    mean = sum(durations) / len(durations) / 1000 if durations else 0
    pct = bad_hour / len(recent) * 100 if recent else 0

    line(0, " MAC CONTROL • ЖУРНАЛ   " + now.astimezone().strftime("%d.%m.%Y  %H:%M:%S"), curses.color_pair(4) | bold)
    line(1, f" ЗА ЧАС: {len(recent)} запросов    {bad_hour} ошибок ({pct:.1f}%)    {running} выполняется    среднее {mean:.2f} с", bold)
    line(2, f" 24 ЧАСА: {len(day)} запросов / {bad_day} ошибок     АРХИВ: {len(events)} запросов / {bad_total} ошибок", curses.color_pair(3))

    chart_height = min(6, max(3, (height - 18) // 2)) if height >= 18 else 0
    header_y = 4
    if chart_height:
        hours = min(24, max(5, (width - 8) // 5))
        clock = now.replace(minute=0, second=0, microsecond=0)
        slots = [clock - dt.timedelta(hours=i) for i in range(hours-1, -1, -1)]
        counts = collections.Counter(e["started"].replace(minute=0, second=0, microsecond=0) for e in events)
        faults = collections.Counter(e["started"].replace(minute=0, second=0, microsecond=0) for e in events if is_error(e))
        peak = max([counts[s] for s in slots] + [1])
        line(3, f" НАГРУЗКА ПО ЧАСАМ • последние {hours} ч    пик {peak} запр./час", bold)
        for y in range(chart_height):
            cells = []
            for stamp in slots:
                level = (counts[stamp] * chart_height + peak - 1) // peak
                cells.append(" ███ " if level >= chart_height - y else "     ")
            line(4 + y, "     " + "".join(cells), curses.color_pair(3))
        def cells(prefix, fn):
            return f"{prefix:<5}" + "".join(f"{str(fn(t))[:4]:^5}" for t in slots)
        line(4 + chart_height, cells("час", lambda t: t.astimezone().strftime("%H")), curses.A_DIM)
        line(5 + chart_height, cells("зап.", lambda t: counts[t]), bold)
        line(6 + chart_height, cells("ош.", lambda t: faults[t] if faults[t] else "·"), curses.color_pair(1))
        header_y = 8 + chart_height

    line(header_y - 1,
         f" {'ТОЛЬКО ОШИБКИ' if errors_only else 'ВСЕ ЗАПРОСЫ'} | e — фильтр | ↑↓ / PgUp / PgDn — история | g — наверх | q — выход",
         curses.A_DIM)
    src_width = 12 if width >= 80 else 7
    cmd_width = max(12, min(25, width // 5))
    args_width = max(3, width - 23 - src_width - cmd_width)
    line(header_y, f" {'ВРЕМЯ':8} {'КЛИЕНТ':{src_width}} {'КОМАНДА':{cmd_width}} {'АРГУМЕНТЫ':{args_width}} ИТОГ",
         curses.color_pair(4) | bold)
    filtered = [e for e in events if is_error(e)] if errors_only else events
    visible = max(0, height - header_y - 2)
    offset = max(0, min(offset, max(0, len(filtered) - visible)))
    for i, event in enumerate(filtered[offset:offset + visible]):
        status = str(event.get("status", "running")).lower()
        if status in ("ok", "success"):
            result, color = "OK", 2
        elif status == "running":
            result, color = "ИДЁТ", 3
        else:
            result, color = "ОШИБКА", 1
        payload = event.get("arguments")
        command = str(event.get("tool", "?"))
        if command in ("custom_command", "custom_query") and isinstance(payload, dict) and payload.get("operation"):
            command = str(payload["operation"])
            payload = payload.get("arguments") or {}
        args = safe_args(payload, args_width)
        tm = event["started"].astimezone().strftime("%H:%M:%S")
        row = f" {tm:8} {source(event)[:src_width]:{src_width}} {command[:cmd_width]:{cmd_width}} {args:{args_width}} {result}"
        line(header_y + 1 + i, row, curses.color_pair(color))
    line(height - 1,
         f" {offset+1 if filtered else 0}–{min(len(filtered), offset + visible)} из {len(filtered)} | «—» — клиент неизвестен | обновление 2 с",
         curses.A_DIM)
    scr.refresh()
    return offset, visible


def main(scr, log_dir):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    scr.nodelay(True)
    scr.keypad(True)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        for i, color in enumerate((curses.COLOR_RED, curses.COLOR_GREEN, curses.COLOR_CYAN,
                                   curses.COLOR_BLUE), 1):
            curses.init_pair(i, color, -1)
    rows, invalid = [], 0
    reader = AuditReader()
    offset = 0
    errors_only = False
    next_refresh = 0
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        try:
            if time.monotonic() >= next_refresh:
                rows, invalid = reader.refresh(log_dir)
                next_refresh = time.monotonic() + 2
            offset, visible = draw(scr, rows, invalid, log_dir, now, offset, errors_only)
            key = scr.getch()
            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (curses.KEY_DOWN, ord("j")):
                offset += 1
            elif key in (curses.KEY_UP, ord("k")):
                offset -= 1
            elif key == curses.KEY_NPAGE:
                offset += max(1, visible)
            elif key == curses.KEY_PPAGE:
                offset -= max(1, visible)
            elif key in (curses.KEY_END, ord("g")):
                offset = 0
            elif key in (ord("e"), ord("E")):
                errors_only = not errors_only
                offset = 0
        except OSError as exc:
            scr.erase()
            scr.addnstr(0, 0, f"Audit read error: {exc}", max(1, scr.getmaxyx()[1] - 1))
            scr.refresh()
        time.sleep(0.1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mac Control live terminal audit monitor")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG)
    arguments = parser.parse_args()
    curses.wrapper(main, arguments.log_dir.expanduser())
