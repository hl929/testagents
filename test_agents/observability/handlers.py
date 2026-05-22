"""JsonlMultiHandler — emit to daily-rotated main log + per-trace files.

Per spec §5 and §10. Failure modes per spec §12:
  - disk write OSError → degrade to sys.__stderr__
  - LRU evicts oldest handle when above trace_handles
  - trace_id=None → main log only, no per-trace file
  - unserializable objects → safe_json_dumps marks them
"""
import logging
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import IO

from test_agents.observability.serializer import safe_json_dumps


class _DailyJsonlHandler(TimedRotatingFileHandler):
    """TimedRotatingFileHandler that names today's live file
    ``app-YYYY-MM-DD.jsonl`` AND ensures rotated archives match the same
    pattern (spec §10).

    The stock ``TimedRotatingFileHandler`` keeps ``baseFilename`` pinned at
    whatever was passed in at construction, so subsequent rollovers would
    forever re-open the construction-day filename and produce
    doubled-date archive names. We override ``doRollover`` to:
      1. Rename the existing live file to its already-correctly-dated
         archive name (a no-op since baseFilename already encodes the
         old date).
      2. Repoint ``baseFilename`` to ``app-<today>.jsonl`` and re-open.
    """

    _NAME_RE = re.compile(r"app-(\d{4}-\d{2}-\d{2})\.jsonl$")

    def __init__(self, log_dir: Path, backup_count: int):
        self._log_dir = log_dir
        today = datetime.now().strftime("%Y-%m-%d")
        live = log_dir / f"app-{today}.jsonl"
        super().__init__(
            filename=str(live),
            when="midnight",
            backupCount=backup_count,
            encoding="utf-8",
            utc=False,
        )
        self.suffix = "%Y-%m-%d"

    def doRollover(self):
        # Close the current stream.
        if self.stream:
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        # The existing baseFilename already encodes the date it was opened
        # for, e.g. app-2026-05-22.jsonl. That IS its final archive name,
        # so no rename is required — we just need to leave it on disk and
        # open a fresh file for today's date.
        old_path = Path(self.baseFilename)

        new_today = datetime.now().strftime("%Y-%m-%d")
        new_path = self._log_dir / f"app-{new_today}.jsonl"

        # Edge case: if rollover fires twice within the same calendar day
        # (test or DST shenanigans), keep distinct files by suffixing the
        # collision with a counter so we never silently lose data.
        if new_path == old_path:
            n = 1
            while True:
                candidate = self._log_dir / f"app-{new_today}.{n}.jsonl"
                if not candidate.exists():
                    new_path = candidate
                    break
                n += 1

        self.baseFilename = str(new_path)

        # Honor backupCount by trimming oldest dated files.
        if self.backupCount > 0:
            dated = sorted(
                p for p in self._log_dir.glob("app-*.jsonl")
                if self._NAME_RE.match(p.name) and p != new_path
            )
            for stale in dated[:-self.backupCount] if len(dated) > self.backupCount else []:
                try:
                    stale.unlink()
                except Exception:
                    pass

        if not self.delay:
            self.stream = self._open()

        # Recompute next rollover time using stdlib's helper so behavior
        # (DST handling etc.) matches the parent class.
        current_time = int(time.time())
        new_rollover_at = self.computeRollover(current_time)
        while new_rollover_at <= current_time:
            new_rollover_at += self.interval
        self.rolloverAt = new_rollover_at


class JsonlMultiHandler(logging.Handler):
    def __init__(
        self, log_dir: str, trace_handles: int = 64,
        write_per_trace: bool = True, retain_days: int = 30,
    ):
        super().__init__()
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        (self._log_dir / "traces").mkdir(parents=True, exist_ok=True)
        self._write_per_trace = write_per_trace
        self._trace_handles_cap = trace_handles
        self._per_trace_handles: "OrderedDict[str, IO]" = OrderedDict()
        # Daily-rotated underlying file handler (spec §10).
        # _DailyJsonlHandler guarantees both live and rotated filenames
        # match the app-YYYY-MM-DD.jsonl pattern.
        self._main = _DailyJsonlHandler(self._log_dir, backup_count=retain_days)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self._format_record(record)
            self._write_line(self._main, line)
            tid = getattr(record, "trace_id", None)
            if self._write_per_trace and tid:
                self._write_per_trace_line(tid, line)
        except Exception:
            # CEO Finding 1.2: never propagate to business.
            try:
                sys.__stderr__.write(
                    f"[observability] emit failed: {record.getMessage()}\n"
                )
            except Exception:
                pass

    def _format_record(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": _iso_now(),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", None),
            "message": record.getMessage(),
        }
        # Pull through any extra fields the callback attaches.
        for k, v in record.__dict__.items():
            if k in payload or k.startswith("_") or k in _STD_RECORD_KEYS:
                continue
            payload[k] = v
        return safe_json_dumps(payload)

    def _write_line(self, handler_or_stream, line: str) -> None:
        """Write a line + newline. Hook point for tests to inject failures."""
        if isinstance(handler_or_stream, logging.Handler):
            stream = handler_or_stream.stream
            stream.write(line + "\n")
            stream.flush()
        else:
            handler_or_stream.write(line + "\n")
            handler_or_stream.flush()

    def _write_per_trace_line(self, trace_id: str, line: str) -> None:
        fp = self._get_or_open_trace(trace_id)
        self._write_line(fp, line)

    def _get_or_open_trace(self, trace_id: str) -> IO:
        if trace_id in self._per_trace_handles:
            self._per_trace_handles.move_to_end(trace_id)
            return self._per_trace_handles[trace_id]
        # Evict if over cap.
        while len(self._per_trace_handles) >= self._trace_handles_cap:
            _, old = self._per_trace_handles.popitem(last=False)
            try: old.close()
            except Exception: pass
        path = self._log_dir / "traces" / f"{trace_id}.jsonl"
        fp = path.open("a", encoding="utf-8")
        self._per_trace_handles[trace_id] = fp
        return fp

    def close_trace(self, trace_id: str) -> None:
        """Called by close_trace_writer() in main.py finally block."""
        fp = self._per_trace_handles.pop(trace_id, None)
        if fp:
            try: fp.close()
            except Exception: pass

    def close(self) -> None:
        for fp in self._per_trace_handles.values():
            try: fp.close()
            except Exception: pass
        self._per_trace_handles.clear()
        try: self._main.close()
        except Exception: pass
        super().close()


def _iso_now() -> str:
    from datetime import timezone
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# Stdlib LogRecord attrs we don't want to pass through to payload.
_STD_RECORD_KEYS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName",
    "taskName", "trace_id",
})
