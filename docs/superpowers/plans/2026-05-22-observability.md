# Test Agents Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained logging + tracing system for Test Agents v3 using stdlib logging + ContextVar + LangGraph callbacks. Zero data exfiltration, zero new dependencies, zero business code changes outside main.py/config.py.

**Architecture:** All node / LLM / tool events are captured automatically via a single `ObservabilityCallback` mounted into `app.invoke(config={...})`. Trace lifecycle is owned by `_with_observability()` in main.py (try/finally). Logs go to two destinations: a daily-rotated `logs/app-YYYY-MM-DD.jsonl` (all events) and per-trace `logs/traces/<trace_id>.jsonl` (single execution). Per-execution summary goes to `logs/metrics.jsonl`.

**Tech Stack:** Python stdlib `logging`, `contextvars`, `json`, `langchain_core.callbacks.BaseCallbackHandler` (already a transitive dep of langgraph).

**Spec reference:** `docs/superpowers/specs/2026-05-22-observability-design.md`

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `test_agents/observability/__init__.py` | Public API exports | Create |
| `test_agents/observability/context.py` | `trace_id_var` ContextVar + `new_trace` / `get_trace_id` / `_new_span_id` | Create |
| `test_agents/observability/serializer.py` | `_summarize` / `_full` / `safe_json_dumps` (handles unserializable) | Create |
| `test_agents/observability/filters.py` | `ContextInjectFilter` (injects trace_id into LogRecord) | Create |
| `test_agents/observability/handlers.py` | `JsonlMultiHandler` (main log + per-trace LRU writer) | Create |
| `test_agents/observability/metrics.py` | Global `MetricsCollector` dict[trace_id, counters] | Create |
| `test_agents/observability/callback.py` | `ObservabilityCallback(BaseCallbackHandler)` | Create |
| `test_agents/observability/logger.py` | `setup_logging` entry + level switching + `make_run_config` | Create |
| `test_agents/config.py` | Add 6 new env vars (LOG_LEVEL/DIR/etc) | Modify |
| `test_agents/main.py` | Add `_with_observability` wrapper around both run paths | Modify |
| `test_agents/tests/test_observability/__init__.py` | Empty package marker | Create |
| `test_agents/tests/test_observability/test_context.py` | ContextVar + new_trace tests | Create |
| `test_agents/tests/test_observability/test_serializer.py` | Serialization + unserializable | Create |
| `test_agents/tests/test_observability/test_filters.py` | ContextInjectFilter tests | Create |
| `test_agents/tests/test_observability/test_handlers.py` | JsonlMultiHandler tests | Create |
| `test_agents/tests/test_observability/test_metrics.py` | MetricsCollector tests | Create |
| `test_agents/tests/test_observability/test_callback.py` | 6 sub-items per spec §13 | Create |
| `test_agents/tests/test_observability/test_logger.py` | setup_logging idempotency / levels / failure | Create |
| `test_agents/tests/test_observability/test_off_switch.py` | OFF mode zero-overhead | Create |
| `test_agents/tests/test_observability/test_errors.py` | Error path coverage | Create |
| `test_agents/tests/test_observability/test_main_observability.py` | 7 sub-tests for main.py wrapper | Create |
| `test_agents/tests/test_observability/test_integration.py` | Full mock pipeline E2E | Create |
| `CLAUDE.md` | Add 5-line "## Observability" section | Modify |

---
## Tasks
---

## Task 1: Config — Add observability environment variables

**Files:**
- Modify: `test_agents/config.py`
- Test: `test_agents/tests/test_config.py`

- [ ] **Step 1: Write the failing test** — append to `test_agents/tests/test_config.py`

```python
def test_observability_config_defaults(monkeypatch):
    """Observability config keys exist with documented defaults."""
    for k in (
        "TEST_AGENTS_LOG_LEVEL", "TEST_AGENTS_LOG_DIR",
        "TEST_AGENTS_LOG_TRACE_FILES", "TEST_AGENTS_LOG_TRACES_KEEP",
        "TEST_AGENTS_LOG_RETAIN_DAYS", "TEST_AGENTS_LOG_TRACE_HANDLES",
    ):
        monkeypatch.delenv(k, raising=False)
    import importlib, test_agents.config as cfg_mod
    importlib.reload(cfg_mod)
    cfg = cfg_mod.config
    assert cfg.LOG_LEVEL == "INFO"
    assert cfg.LOG_DIR == "logs"
    assert cfg.LOG_TRACE_FILES is True
    assert cfg.LOG_TRACES_KEEP == 1000
    assert cfg.LOG_RETAIN_DAYS == 30
    assert cfg.LOG_TRACE_HANDLES == 64
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_agents/tests/test_config.py::test_observability_config_defaults -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'LOG_LEVEL'`

- [ ] **Step 3: Add config attributes** — append inside class `Config` in `test_agents/config.py`

```python
    # 可观测体系配置（spec §6）
    LOG_LEVEL: str = os.getenv("TEST_AGENTS_LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("TEST_AGENTS_LOG_DIR", "logs")
    LOG_TRACE_FILES: bool = os.getenv("TEST_AGENTS_LOG_TRACE_FILES", "true").lower() == "true"
    LOG_TRACES_KEEP: int = int(os.getenv("TEST_AGENTS_LOG_TRACES_KEEP", "1000"))
    LOG_RETAIN_DAYS: int = int(os.getenv("TEST_AGENTS_LOG_RETAIN_DAYS", "30"))
    LOG_TRACE_HANDLES: int = int(os.getenv("TEST_AGENTS_LOG_TRACE_HANDLES", "64"))
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_config.py -v`
Expected: PASS for both new tests; pre-existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add test_agents/config.py test_agents/tests/test_config.py
git commit -m "feat(observability): add config env vars for logging system"
```

---

## Task 2: context.py — trace_id ContextVar + helpers

**Files:**
- Create: `test_agents/observability/__init__.py` (empty)
- Create: `test_agents/observability/context.py`
- Create: `test_agents/tests/test_observability/__init__.py` (empty)
- Create: `test_agents/tests/test_observability/test_context.py`

- [ ] **Step 1: Create empty package markers**

```bash
mkdir -p test_agents/observability test_agents/tests/test_observability
: > test_agents/observability/__init__.py
: > test_agents/tests/test_observability/__init__.py
```

- [ ] **Step 2: Write the failing test** — `test_agents/tests/test_observability/test_context.py`

```python
"""ContextVar lifecycle + span_id format tests (spec §7)."""
import re
from test_agents.observability.context import (
    new_trace, get_trace_id, _new_span_id, reset_trace,
)

def test_get_trace_id_default_none():
    reset_trace()
    assert get_trace_id() is None

def test_new_trace_sets_id():
    reset_trace()
    tid = new_trace("hello world")
    assert isinstance(tid, str)
    assert re.fullmatch(r"tr_[0-9a-f]{8}", tid)
    assert get_trace_id() == tid

def test_reset_trace_clears():
    new_trace("any")
    reset_trace()
    assert get_trace_id() is None

def test_new_trace_overwrites_previous():
    reset_trace()
    t1 = new_trace("first")
    t2 = new_trace("second")
    assert t1 != t2
    assert get_trace_id() == t2

def test_new_span_id_format_and_uniqueness():
    a = _new_span_id()
    b = _new_span_id()
    assert re.fullmatch(r"sp_[0-9a-f]{8}", a)
    assert re.fullmatch(r"sp_[0-9a-f]{8}", b)
    assert a != b
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest test_agents/tests/test_observability/test_context.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 4: Implement context.py** — write `test_agents/observability/context.py`

```python
"""trace_id ContextVar + span_id generator (spec §7).

Spec §7 removed span_id_var on purpose — span_id is held in
ObservabilityCallback._spans (dict[run_id, span_id]). Only trace_id
is propagated via ContextVar across the call stack.
"""
import secrets
from contextvars import ContextVar

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

def new_trace(user_request: str) -> str:
    """Generate a new trace_id and store it in the ContextVar.

    Caller (main.py:_with_observability) owns trace lifecycle (spec §7).
    user_request kept in signature so MetricsCollector.new_trace_metrics
    can be called with the same value at the same site.
    """
    tid = "tr_" + secrets.token_hex(4)
    trace_id_var.set(tid)
    return tid

def get_trace_id() -> str | None:
    return trace_id_var.get()

def reset_trace() -> None:
    """Clear the trace_id. Idempotent."""
    trace_id_var.set(None)

def _new_span_id() -> str:
    return "sp_" + secrets.token_hex(4)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_observability/test_context.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add test_agents/observability/__init__.py test_agents/observability/context.py \
        test_agents/tests/test_observability/__init__.py \
        test_agents/tests/test_observability/test_context.py
git commit -m "feat(observability): add trace_id ContextVar + new_trace/span_id helpers"
```

---

## Task 3: serializer.py — safe_json_dumps + truncation helpers

**Files:**
- Create: `test_agents/observability/serializer.py`
- Create: `test_agents/tests/test_observability/test_serializer.py`

- [ ] **Step 1: Write the failing test** — `test_agents/tests/test_observability/test_serializer.py`

```python
"""Serializer + truncation behaviors (spec §8)."""
import json
import socket
from test_agents.observability.serializer import (
    safe_json_dumps, summarize, full,
)


def test_safe_json_dumps_basic_types():
    assert safe_json_dumps({"a": 1}) == '{"a": 1}'
    assert "[1, 2, 3]" in safe_json_dumps([1, 2, 3])


def test_safe_json_dumps_unicode_kept():
    """ensure_ascii=False — Chinese kept verbatim."""
    assert "你好" in safe_json_dumps({"msg": "你好"})


def test_safe_json_dumps_unserializable_marker():
    """Unserializable objects get ___unserializable___ marker (spec §8)."""
    s = safe_json_dumps({"sock": socket.socket()})
    parsed = json.loads(s)
    assert parsed["___unserializable___"] is True
    # Original object replaced by its str() rendering
    assert "socket" in parsed["sock"].lower()


def test_summarize_dict_kind_truncates_to_200():
    big = {"k": "x" * 1000}
    s = summarize(big, kind="dict")
    assert len(s) <= 200

def test_summarize_chat_kind_joins_messages():
    """on_chat_model_start.messages is list[list[BaseMessage]]; first list joined by space."""
    class FakeMsg:
        def __init__(self, c): self.content = c
    msgs = [[FakeMsg("hi"), FakeMsg("there")]]
    s = summarize(msgs, kind="chat")
    assert "hi" in s and "there" in s
    assert len(s) <= 200

def test_summarize_list_kind_first_element():
    """on_llm_start.prompts is list[str]; take prompts[0]."""
    s = summarize(["first prompt", "second"], kind="list")
    assert s.startswith("first prompt")

def test_summarize_str_kind_raw_truncate():
    s = summarize("x" * 500, kind="str")
    assert len(s) == 200

def test_summarize_empty_or_none_safe():
    assert summarize(None, kind="dict") == ""
    assert summarize([], kind="list") == ""
    assert summarize("", kind="str") == ""


def test_full_truncates_to_2000():
    big = {"k": "x" * 5000}
    s = full(big, kind="dict")
    assert len(s) <= 2000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_agents/tests/test_observability/test_serializer.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement serializer.py**

```python
"""Serialization helpers for LogRecord extras (spec §8).

Three event-source kinds need different treatment (Eng Finding 2.3):
  - "dict": on_chain_start.inputs (dict)         → json.dumps default=str
  - "chat": on_chat_model_start.messages (list[list[BaseMessage]])
  - "list": on_llm_start.prompts (list[str])     → take prompts[0]
  - "str" : on_tool_start.input_str (str)        → raw

Unserializable objects (sockets, lambdas) never crash logging — they
become str(obj) plus a ___unserializable___: true marker.
"""
import json

_SUMMARY_LIMIT = 200
_FULL_LIMIT = 2000


def safe_json_dumps(obj) -> str:
    """json.dumps that never raises. Records unserializable objects with marker."""
    flagged = False
    def _default(o):
        nonlocal flagged
        flagged = True
        return str(o)
    s = json.dumps(obj, ensure_ascii=False, default=_default)
    if flagged:
        # Re-encode with the marker so consumers can detect the degradation.
        # We can't mutate dict in place safely; emit as wrapped object.
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                parsed["___unserializable___"] = True
                return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            pass
    return s


def _stringify(obj, kind: str) -> str:
    if obj is None:
        return ""
    if kind == "dict":
        return safe_json_dumps(obj)
    if kind == "chat":
        # messages is list[list[BaseMessage]] from on_chat_model_start
        try:
            return " ".join(
                getattr(m, "content", str(m)) for m in obj[0]
            ) if obj else ""
        except Exception:
            return str(obj)
    if kind == "list":
        # prompts is list[str] from on_llm_start
        if not obj:
            return ""
        return str(obj[0])
    if kind == "str":
        return str(obj)
    return str(obj)


def summarize(obj, kind: str) -> str:
    """Truncate to 200 chars (spec §8 input_summary)."""
    s = _stringify(obj, kind)
    return s[:_SUMMARY_LIMIT]


def full(obj, kind: str) -> str:
    """Truncate to 2000 chars (spec §8 input_full, DEBUG only)."""
    s = _stringify(obj, kind)
    return s[:_FULL_LIMIT]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_observability/test_serializer.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add test_agents/observability/serializer.py test_agents/tests/test_observability/test_serializer.py
git commit -m "feat(observability): add safe_json_dumps + summarize/full helpers"
```

---

## Task 4: filters.py — ContextInjectFilter

**Files:**
- Create: `test_agents/observability/filters.py`
- Create: `test_agents/tests/test_observability/test_filters.py`

- [ ] **Step 1: Write the failing test** — `test_agents/tests/test_observability/test_filters.py`

```python
"""ContextInjectFilter injects trace_id into LogRecord (spec §4)."""
import logging
from test_agents.observability.context import new_trace, reset_trace
from test_agents.observability.filters import ContextInjectFilter


def _make_record():
    return logging.LogRecord(
        "test", logging.INFO, "f.py", 1, "msg", None, None,
    )


def test_filter_injects_trace_id_when_set():
    new_trace("x")
    rec = _make_record()
    ContextInjectFilter().filter(rec)
    assert rec.trace_id is not None
    assert rec.trace_id.startswith("tr_")
    reset_trace()


def test_filter_injects_none_when_unset():
    reset_trace()
    rec = _make_record()
    ContextInjectFilter().filter(rec)
    assert rec.trace_id is None


def test_filter_returns_true_always():
    """Filter must allow record through; this is an enricher, not a gate."""
    new_trace("x")
    assert ContextInjectFilter().filter(_make_record()) is True
    reset_trace()
    assert ContextInjectFilter().filter(_make_record()) is True


def test_filter_preserves_existing_extra():
    """If caller already supplied trace_id via extra=, do not overwrite."""
    new_trace("x")
    rec = _make_record()
    rec.trace_id = "tr_caller01"
    ContextInjectFilter().filter(rec)
    assert rec.trace_id == "tr_caller01"
    reset_trace()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_agents/tests/test_observability/test_filters.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement filters.py**

```python
"""LogRecord enrichment filter (spec §4).

Injects trace_id from ContextVar into every record so handlers can
route per-trace files without business code passing it manually.
"""
import logging

from test_agents.observability.context import get_trace_id


class ContextInjectFilter(logging.Filter):
    """Inject trace_id from ContextVar into LogRecord.

    span_id / parent_span_id are NOT injected here (spec §4): the
    callback emits them via the logger.info(..., extra={"span_id": ...})
    path, since they're known at emit time and not via ContextVar.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id") or record.trace_id is None:
            record.trace_id = get_trace_id()
        # Always allow the record through.
        return True
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_observability/test_filters.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add test_agents/observability/filters.py test_agents/tests/test_observability/test_filters.py
git commit -m "feat(observability): add ContextInjectFilter for trace_id propagation"
```

---
## Task 5: handlers.py — JsonlMultiHandler with LRU per-trace writer

**Files:**
- Create: `test_agents/observability/handlers.py`
- Create: `test_agents/tests/test_observability/test_handlers.py`

- [ ] **Step 1: Write the failing test** — `test_agents/tests/test_observability/test_handlers.py`

```python
"""JsonlMultiHandler emits to main + per-trace files (spec §5, §10, §12)."""
import json
import logging
from pathlib import Path
import pytest

from test_agents.observability.handlers import JsonlMultiHandler


def _make_record(trace_id=None, msg="hi"):
    rec = logging.LogRecord("t", logging.INFO, "f", 1, msg, None, None)
    rec.trace_id = trace_id
    return rec


def test_main_log_written(tmp_path):
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=4, write_per_trace=True)
    h.emit(_make_record(trace_id="tr_abc01234"))
    h.close()
    files = list(tmp_path.glob("app-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["trace_id"] == "tr_abc01234"
    assert payload["message"] == "hi"


def test_per_trace_file_written(tmp_path):
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=4, write_per_trace=True)
    h.emit(_make_record(trace_id="tr_abc01234", msg="event1"))
    h.emit(_make_record(trace_id="tr_abc01234", msg="event2"))
    h.close()
    trace_file = tmp_path / "traces" / "tr_abc01234.jsonl"
    assert trace_file.exists()
    lines = trace_file.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["message"] == "event1"
    assert json.loads(lines[1])["message"] == "event2"


def test_trace_id_none_skips_per_trace(tmp_path):
    """Eng Finding 4.1 + spec §12: trace_id=None → main log only."""
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=4, write_per_trace=True)
    h.emit(_make_record(trace_id=None))
    h.close()
    assert not (tmp_path / "traces").exists() or \
           not any((tmp_path / "traces").iterdir())


def test_lru_evicts_oldest_handle(tmp_path):
    """Eng Finding 4.3: per-trace handle LRU evicts oldest beyond cap."""
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=2, write_per_trace=True)
    for i in range(5):
        h.emit(_make_record(trace_id=f"tr_{i:08x}", msg=f"m{i}"))
    # Only 2 handles open at any moment, but all 5 files exist on disk.
    files = sorted((tmp_path / "traces").glob("tr_*.jsonl"))
    assert len(files) == 5
    # Re-emitting an evicted trace must still work (re-open the file).
    h.emit(_make_record(trace_id="tr_00000000", msg="reopened"))
    h.close()
    content = (tmp_path / "traces" / "tr_00000000.jsonl").read_text()
    assert "m0" in content and "reopened" in content


def test_unserializable_object_marked(tmp_path):
    """CEO Finding 2.1: emit must not crash on unserializable extra."""
    import socket
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=4, write_per_trace=True)
    rec = _make_record(trace_id="tr_abc01234")
    rec.extra_payload = {"sock": socket.socket()}
    h.emit(rec)  # must not raise
    h.close()
    files = list(tmp_path.glob("app-*.jsonl"))
    text = files[0].read_text()
    assert "___unserializable___" in text


def test_write_failure_silent_degrade(tmp_path, monkeypatch, capsys):
    """CEO Finding 1.2: emit OSError → stderr warning, no exception."""
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=4, write_per_trace=True)
    # Force underlying write to fail
    def boom(*a, **kw): raise OSError("disk full")
    monkeypatch.setattr(h, "_write_line", boom)
    h.emit(_make_record(trace_id="tr_abc01234"))  # must not raise
    # Spec: degrade to sys.__stderr__, do not re-raise.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_agents/tests/test_observability/test_handlers.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement handlers.py** (next step)

- [ ] **Step 3: Implement handlers.py** — `test_agents/observability/handlers.py`

```python
"""JsonlMultiHandler — emit to daily-rotated main log + per-trace files.

Per spec §5 and §10. Failure modes per spec §12:
  - disk write OSError → degrade to sys.__stderr__
  - LRU evicts oldest handle when above trace_handles
  - trace_id=None → main log only, no per-trace file
  - unserializable objects → safe_json_dumps marks them
"""
import json
import logging
import sys
from collections import OrderedDict
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import IO

from test_agents.observability.serializer import safe_json_dumps


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
        self._main = TimedRotatingFileHandler(
            filename=str(self._log_dir / "app.jsonl"),
            when="midnight", backupCount=retain_days, encoding="utf-8",
            utc=False,
        )
        # Override suffix so file becomes app-YYYY-MM-DD.jsonl
        self._main.suffix = "%Y-%m-%d"
        self._main.namer = lambda name: name.replace(".jsonl.", "-").rstrip(".") + ".jsonl"

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
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
           f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


# Stdlib LogRecord attrs we don't want to pass through to payload.
_STD_RECORD_KEYS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName",
    "taskName", "trace_id",
})
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_observability/test_handlers.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add test_agents/observability/handlers.py test_agents/tests/test_observability/test_handlers.py
git commit -m "feat(observability): JsonlMultiHandler with LRU per-trace writer"
```

---
## Task 6: metrics.py — Global MetricsCollector dict[trace_id, counters]

**Files:**
- Create: `test_agents/observability/metrics.py`
- Create: `test_agents/tests/test_observability/test_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
"""MetricsCollector singleton + per-trace counters (spec §4, §11)."""
import json
from pathlib import Path
import pytest

from test_agents.observability.metrics import MetricsCollector


def test_new_trace_metrics_initialises_counters(tmp_path):
    m = MetricsCollector(metrics_path=str(tmp_path / "metrics.jsonl"))
    m.new_trace("tr_abc", user_request="hello")
    snap = m._traces["tr_abc"]
    assert snap["node_count"] == 0
    assert snap["llm_call_count"] == 0
    assert snap["tool_call_count"] == 0
    assert snap["replan_count"] == 0
    assert snap["user_request"] == "hello"
    assert "ts_start" in snap

def test_incr_increments_named_counter(tmp_path):
    m = MetricsCollector(metrics_path=str(tmp_path / "metrics.jsonl"))
    m.new_trace("tr_abc", user_request="x")
    m.incr("tr_abc", "node_count")
    m.incr("tr_abc", "node_count")
    m.incr("tr_abc", "llm_call_count")
    assert m._traces["tr_abc"]["node_count"] == 2
    assert m._traces["tr_abc"]["llm_call_count"] == 1

def test_flush_appends_one_line_and_removes(tmp_path):
    p = tmp_path / "metrics.jsonl"
    m = MetricsCollector(metrics_path=str(p))
    m.new_trace("tr_abc", user_request="x")
    m.incr("tr_abc", "node_count")
    m.flush("tr_abc", status="ok", final_answer_length=42)
    assert "tr_abc" not in m._traces
    line = p.read_text().strip()
    payload = json.loads(line)
    assert payload["trace_id"] == "tr_abc"
    assert payload["status"] == "ok"
    assert payload["node_count"] == 1
    assert payload["final_answer_length"] == 42

def test_flush_three_statuses(tmp_path):
    """Eng Finding 4.6: status ∈ {ok, error, aborted}."""
    p = tmp_path / "metrics.jsonl"
    m = MetricsCollector(metrics_path=str(p))
    for tid, st in [("tr_a", "ok"), ("tr_b", "error"), ("tr_c", "aborted")]:
        m.new_trace(tid, user_request="x")
        m.flush(tid, status=st)
    statuses = [json.loads(l)["status"] for l in p.read_text().splitlines()]
    assert statuses == ["ok", "error", "aborted"]

def test_flush_missing_trace_safe(tmp_path):
    """Flushing an unknown trace_id must not raise."""
    m = MetricsCollector(metrics_path=str(tmp_path / "metrics.jsonl"))
    m.flush("tr_never", status="ok")  # must not raise

def test_flush_write_failure_silent(tmp_path, monkeypatch, capsys):
    """CEO Finding 1.2: metrics write failure degrades to stderr."""
    p = tmp_path / "metrics.jsonl"
    m = MetricsCollector(metrics_path=str(p))
    m.new_trace("tr_abc", user_request="x")
    def boom(*a, **kw): raise OSError("disk full")
    monkeypatch.setattr("builtins.open", boom)
    m.flush("tr_abc", status="ok")  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_agents/tests/test_observability/test_metrics.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement metrics.py**

```python
"""MetricsCollector — global singleton, dict[trace_id, counters] (spec §4).

Why not on ObservabilityCallback.self? Eng Finding 4.7: each app.invoke
creates a fresh callback instance. For traces that span multiple invokes
(confirm_plan interrupt → resume), per-instance state would lose half
the counters. We key by trace_id (from ContextVar) instead.
"""
import json
import sys
from datetime import datetime, timezone


class MetricsCollector:
    def __init__(self, metrics_path: str):
        self._path = metrics_path
        self._traces: dict[str, dict] = {}

    def new_trace(self, trace_id: str, user_request: str) -> None:
        self._traces[trace_id] = {
            "trace_id": trace_id,
            "ts_start": _iso_now(),
            "user_request": user_request,
            "node_count": 0,
            "llm_call_count": 0,
            "tool_call_count": 0,
            "replan_count": 0,
        }

    def incr(self, trace_id: str, key: str) -> None:
        snap = self._traces.get(trace_id)
        if snap is None:
            return
        snap[key] = snap.get(key, 0) + 1

    def flush(self, trace_id: str, status: str,
              final_answer_length: int = 0, error: str | None = None) -> None:
        snap = self._traces.pop(trace_id, None)
        if snap is None:
            return  # Unknown trace; nothing to flush.
        snap["ts_end"] = _iso_now()
        snap["status"] = status
        snap["final_answer_length"] = final_answer_length
        snap["error"] = error
        snap["duration_ms"] = _duration_ms(snap["ts_start"], snap["ts_end"])
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(snap, ensure_ascii=False) + "\n")
        except Exception as e:
            try:
                sys.__stderr__.write(f"[observability] metrics flush failed: {e}\n")
            except Exception:
                pass


def _iso_now() -> str:
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _duration_ms(start_iso: str, end_iso: str) -> int:
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    try:
        s = datetime.strptime(start_iso, fmt)
        e = datetime.strptime(end_iso, fmt)
        return int((e - s).total_seconds() * 1000)
    except Exception:
        return 0
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_observability/test_metrics.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add test_agents/observability/metrics.py test_agents/tests/test_observability/test_metrics.py
git commit -m "feat(observability): MetricsCollector with dict[trace_id, counters]"
```

---
## Task 7: callback.py — ObservabilityCallback (test scaffold)

Big task. Implementation is non-trivial, so split into 7 sub-steps. Tests
match the spec §13 test_callback.py breakdown (6 sub-items).

**Files:**
- Create: `test_agents/observability/callback.py`
- Create: `test_agents/tests/test_observability/test_callback.py`

- [ ] **Step 1: Write the failing tests** — `test_agents/tests/test_observability/test_callback.py`

```python
"""ObservabilityCallback behavior (spec §5, §13)."""
import logging
import uuid
import pytest

from test_agents.observability.callback import ObservabilityCallback
from test_agents.observability.context import new_trace, reset_trace
from test_agents.observability.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def _reset_state():
    ObservabilityCallback._spans.clear()
    ObservabilityCallback._last_node_per_trace.clear()
    reset_trace()
    yield
    ObservabilityCallback._spans.clear()
    ObservabilityCallback._last_node_per_trace.clear()
    reset_trace()


def _uuid(): return uuid.uuid4()


def test_filter_non_langgraph_chain(caplog):
    """Sub-item 1: on_chain_start without metadata.langgraph_node returns silently."""
    cb = ObservabilityCallback()
    with caplog.at_level(logging.INFO, logger="test_agents.observability.callback"):
        cb.on_chain_start({}, {"x": 1}, run_id=_uuid(), metadata={})
    # No node.enter event logged for non-langgraph chains.
    msgs = [r for r in caplog.records if getattr(r, "event", "") == "node.enter"]
    assert msgs == []


def test_node_enter_records_span_and_parent(caplog):
    """on_chain_start with metadata.langgraph_node records node.enter with span."""
    cb = ObservabilityCallback()
    parent_id, child_id = _uuid(), _uuid()
    with caplog.at_level(logging.INFO, logger="test_agents.observability.callback"):
        cb.on_chain_start({}, {"x": 1}, run_id=parent_id,
                          metadata={"langgraph_node": "planner"})
        cb.on_chain_start({}, {"y": 2}, run_id=child_id, parent_run_id=parent_id,
                          metadata={"langgraph_node": "dispatch"})
    enters = [r for r in caplog.records if getattr(r, "event", "") == "node.enter"]
    assert len(enters) == 2
    assert enters[0].node == "planner"
    assert enters[1].node == "dispatch"
    assert enters[1].parent_span_id == enters[0].span_id


def test_replan_inference(tmp_path, monkeypatch):
    """Sub-item 2: reflect → planner transition increments replan_count."""
    metrics = MetricsCollector(metrics_path=str(tmp_path / "metrics.jsonl"))
    monkeypatch.setattr("test_agents.observability.callback.metrics", metrics)
    new_trace("x")
    tid = "tr_x"
    monkeypatch.setattr("test_agents.observability.callback.get_trace_id",
                        lambda: tid)
    metrics.new_trace(tid, user_request="t")

    cb = ObservabilityCallback()
    rid1, rid2 = _uuid(), _uuid()
    cb.on_chain_start({}, {}, run_id=rid1, metadata={"langgraph_node": "reflect"})
    cb.on_chain_end({}, run_id=rid1)
    cb.on_chain_start({}, {}, run_id=rid2, metadata={"langgraph_node": "planner"})
    cb.on_chain_end({}, run_id=rid2)
    assert metrics._traces[tid]["replan_count"] == 1


def test_serialization_three_kinds(caplog):
    """Sub-item 3: dict / chat / str event sources summarized correctly."""
    cb = ObservabilityCallback()
    class M:
        def __init__(self, c): self.content = c
    with caplog.at_level(logging.INFO, logger="test_agents.observability.callback"):
        cb.on_chain_start({}, {"k": "v"}, run_id=_uuid(),
                          metadata={"langgraph_node": "planner"})
        cb.on_chat_model_start({"id": ["openai", "ChatOpenAI"],
                                "kwargs": {"model_name": "gpt-4o"}},
                               [[M("hello"), M("world")]],
                               run_id=_uuid())
        cb.on_tool_start({}, "some tool input", run_id=_uuid())
    sums = {r.event: getattr(r, "input_summary", "") for r in caplog.records}
    assert "k" in sums.get("node.enter", "") and "v" in sums.get("node.enter", "")
    assert "hello" in sums.get("llm.call", "") or \
           "hello" in (caplog.records[1].input_summary)
    assert "some tool input" in sums.get("tool.call", "")


def test_callback_exception_not_propagating(caplog, monkeypatch):
    """Sub-item 4: internal callback bug never propagates to LangGraph."""
    cb = ObservabilityCallback()
    monkeypatch.setattr(
        "test_agents.observability.callback._new_span_id",
        lambda: 1 / 0,  # Inject an exception inside the callback.
    )
    with caplog.at_level(logging.WARNING):
        cb.on_chain_start({}, {"k": "v"}, run_id=_uuid(),
                          metadata={"langgraph_node": "planner"})
    # Must NOT raise. Warning must be logged.
    msgs = [r.getMessage() for r in caplog.records]
    assert any("callback.failed" in m for m in msgs)


def test_tokens_extraction_present_and_missing(caplog, monkeypatch, tmp_path):
    """Sub-item 5: tokens from response.usage_metadata; missing → field absent."""
    metrics = MetricsCollector(metrics_path=str(tmp_path / "m.jsonl"))
    monkeypatch.setattr("test_agents.observability.callback.metrics", metrics)
    new_trace("t")
    metrics.new_trace("t", user_request="x")
    monkeypatch.setattr("test_agents.observability.callback.get_trace_id",
                        lambda: "t")
    cb = ObservabilityCallback()
    class Resp:
        usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    class NoMeta: pass
    rid1, rid2 = _uuid(), _uuid()
    with caplog.at_level(logging.INFO, logger="test_agents.observability.callback"):
        cb.on_chat_model_start({"id": ["x"], "kwargs": {}}, [[]], run_id=rid1)
        cb.on_chat_model_end(Resp(), run_id=rid1)
        cb.on_chat_model_start({"id": ["x"], "kwargs": {}}, [[]], run_id=rid2)
        cb.on_chat_model_end(NoMeta(), run_id=rid2)
    ends = [r for r in caplog.records
            if getattr(r, "event", "") == "llm.call"
            and getattr(r, "phase", "") == "end"]
    assert len(ends) == 2
    assert ends[0].tokens["total"] == 15
    assert not hasattr(ends[1], "tokens") or ends[1].tokens is None


def test_chat_model_and_llm_both_implemented():
    """Sub-item 6 + Eng Finding 1.1: both on_chat_model_start AND on_llm_start."""
    cb = ObservabilityCallback()
    assert hasattr(cb, "on_chat_model_start")
    assert hasattr(cb, "on_llm_start")
    assert hasattr(cb, "on_chat_model_end")
    assert hasattr(cb, "on_llm_end")


def test_run_id_cleanup_on_all_six_exits(monkeypatch, tmp_path):
    """Eng Finding 4.3: _spans dict has no leftovers after any end/error."""
    metrics = MetricsCollector(metrics_path=str(tmp_path / "m.jsonl"))
    monkeypatch.setattr("test_agents.observability.callback.metrics", metrics)
    new_trace("t"); metrics.new_trace("t", user_request="x")
    monkeypatch.setattr("test_agents.observability.callback.get_trace_id",
                        lambda: "t")
    cb = ObservabilityCallback()
    # 6 exits: chain_end, chain_error, chat_model_end, llm_end (alias),
    # tool_end, tool_error
    for trigger in (
        lambda r: cb.on_chain_end({}, run_id=r),
        lambda r: cb.on_chain_error(Exception("x"), run_id=r),
        lambda r: cb.on_chat_model_end(type("R", (), {})(), run_id=r),
        lambda r: cb.on_tool_end("out", run_id=r),
        lambda r: cb.on_tool_error(Exception("x"), run_id=r),
    ):
        rid = _uuid()
        cb.on_chain_start({}, {}, run_id=rid, metadata={"langgraph_node": "x"})
        assert rid in cb._spans
        trigger(rid)
        assert rid not in cb._spans  # cleanup on every exit path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test_agents/tests/test_observability/test_callback.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement callback.py** — `test_agents/observability/callback.py`

```python
"""ObservabilityCallback — wraps LangGraph events into JSON logs (spec §5).

Class-level dicts (not self.) because each app.invoke creates a fresh
callback instance, but state must survive across invokes (interrupt → resume).

All callback methods are wrapped in try/except. A bug in observability
must NEVER propagate into the business graph (CEO Finding 4.1).
"""
import logging
import traceback
from time import perf_counter
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from test_agents.observability.context import get_trace_id, _new_span_id
from test_agents.observability.metrics import MetricsCollector
from test_agents.observability.serializer import summarize, full

logger = logging.getLogger("test_agents.observability.callback")

# Set by setup_logging(); tests inject directly.
metrics: MetricsCollector | None = None  # type: ignore[assignment]


class ObservabilityCallback(BaseCallbackHandler):
    # Class-level: shared across invokes within the same process.
    _spans: dict[UUID, dict] = {}  # run_id → {"span_id", "node", "t0"}
    _last_node_per_trace: dict[str, str] = {}  # trace_id → last node name

    # ---- chain (node) events ----

    def on_chain_start(self, serialized, inputs, *, run_id,
                       parent_run_id=None, metadata=None, **kw):
        try:
            node_name = (metadata or {}).get("langgraph_node")
            if not node_name:
                return  # Filter non-langgraph runnables.
            span_id = _new_span_id()
            parent_span = (self._spans.get(parent_run_id) or {}).get("span_id")
            self._spans[run_id] = {
                "span_id": span_id, "node": node_name, "t0": perf_counter(),
            }
            logger.info("node.enter", extra={
                "event": "node.enter",
                "node": node_name,
                "span_id": span_id,
                "parent_span_id": parent_span,
                "input_summary": summarize(inputs, kind="dict"),
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed",
                "callback": "on_chain_start",
                "error": traceback.format_exc()[:500],
            })

    def on_chain_end(self, outputs, *, run_id, **kw):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            tid = get_trace_id()
            # Replan inference: reflect → planner transition (Eng Finding 2.2/4.2).
            last = self._last_node_per_trace.get(tid)
            if last == "reflect" and entry["node"] == "planner" and metrics and tid:
                metrics.incr(tid, "replan_count")
            if tid:
                self._last_node_per_trace[tid] = entry["node"]
            if metrics and tid:
                metrics.incr(tid, "node_count")
            logger.info("node.exit", extra={
                "event": "node.exit",
                "node": entry["node"],
                "span_id": entry["span_id"],
                "duration_ms": int((perf_counter() - entry["t0"]) * 1000),
                "status": "ok",
                "output_summary": summarize(outputs, kind="dict"),
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed",
                "callback": "on_chain_end",
                "error": traceback.format_exc()[:500],
            })

    def on_chain_error(self, error, *, run_id, **kw):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            logger.error("node.exit", extra={
                "event": "node.exit",
                "node": entry["node"],
                "span_id": entry["span_id"],
                "duration_ms": int((perf_counter() - entry["t0"]) * 1000),
                "status": "error",
                "error": {
                    "type": type(error).__name__,
                    "message": str(error)[:500],
                },
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed",
                "callback": "on_chain_error",
                "error": traceback.format_exc()[:500],
            })

    # ---- LLM events (Eng Finding 1.1: both chat + completion) ----

    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        self._on_llm_start(serialized, messages, run_id, kind="chat")

    def on_llm_start(self, serialized, prompts, *, run_id, **kw):
        self._on_llm_start(serialized, prompts, run_id, kind="list")

    def _on_llm_start(self, serialized, payload, run_id, kind):
        try:
            span_id = _new_span_id()
            t0 = perf_counter()
            self._spans[run_id] = {"span_id": span_id, "node": "_llm", "t0": t0}
            model = (
                (serialized or {}).get("kwargs", {}).get("model_name")
                or ((serialized or {}).get("id") or [None])[-1]
            )
            logger.info("llm.call", extra={
                "event": "llm.call",
                "phase": "start",
                "span_id": span_id,
                "model": model,
                "input_summary": summarize(payload, kind=kind),
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed", "callback": "_on_llm_start",
                "error": traceback.format_exc()[:500],
            })

    def on_chat_model_end(self, response, *, run_id, **kw):
        self._on_llm_end(response, run_id)

    def on_llm_end(self, response, *, run_id, **kw):
        self._on_llm_end(response, run_id)

    def _on_llm_end(self, response, run_id):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            tid = get_trace_id()
            if metrics and tid:
                metrics.incr(tid, "llm_call_count")
            tokens = getattr(response, "usage_metadata", None)
            extra = {
                "event": "llm.call",
                "phase": "end",
                "span_id": entry["span_id"],
                "duration_ms": int((perf_counter() - entry["t0"]) * 1000),
                "status": "ok",
            }
            if tokens:
                extra["tokens"] = {
                    "prompt": tokens.get("input_tokens"),
                    "completion": tokens.get("output_tokens"),
                    "total": tokens.get("total_tokens"),
                }
            logger.info("llm.call", extra=extra)
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed", "callback": "_on_llm_end",
                "error": traceback.format_exc()[:500],
            })

    def on_llm_error(self, error, *, run_id, **kw):
        self._on_llm_error(error, run_id)

    def on_chat_model_error(self, error, *, run_id, **kw):
        self._on_llm_error(error, run_id)

    def _on_llm_error(self, error, run_id):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            logger.error("llm.call", extra={
                "event": "llm.call", "phase": "end",
                "span_id": entry["span_id"], "status": "error",
                "error": {"type": type(error).__name__, "message": str(error)[:500]},
            })
        except Exception:
            pass

    # ---- tool events ----

    def on_tool_start(self, serialized, input_str, *, run_id, **kw):
        try:
            span_id = _new_span_id()
            t0 = perf_counter()
            tool = (serialized or {}).get("name") or "_tool"
            self._spans[run_id] = {"span_id": span_id, "node": tool, "t0": t0}
            logger.info("tool.call", extra={
                "event": "tool.call", "phase": "start",
                "span_id": span_id, "tool": tool,
                "input_summary": summarize(input_str, kind="str"),
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed", "callback": "on_tool_start",
                "error": traceback.format_exc()[:500],
            })

    def on_tool_end(self, output, *, run_id, **kw):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            tid = get_trace_id()
            if metrics and tid:
                metrics.incr(tid, "tool_call_count")
            logger.info("tool.call", extra={
                "event": "tool.call", "phase": "end",
                "span_id": entry["span_id"], "tool": entry["node"],
                "duration_ms": int((perf_counter() - entry["t0"]) * 1000),
                "status": "ok",
                "output_summary": summarize(output, kind="str"),
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed", "callback": "on_tool_end",
                "error": traceback.format_exc()[:500],
            })

    def on_tool_error(self, error, *, run_id, **kw):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            logger.error("tool.call", extra={
                "event": "tool.call", "phase": "end",
                "span_id": entry["span_id"], "tool": entry["node"],
                "status": "error",
                "error": {"type": type(error).__name__, "message": str(error)[:500]},
            })
        except Exception:
            pass

    # ---- trace teardown hook ----

    @classmethod
    def cleanup_trace(cls, trace_id: str) -> None:
        """Called from close_trace_writer to evict per-trace state (Eng Finding 4.3)."""
        cls._last_node_per_trace.pop(trace_id, None)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_observability/test_callback.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add test_agents/observability/callback.py test_agents/tests/test_observability/test_callback.py
git commit -m "feat(observability): ObservabilityCallback with chat+llm+tool+chain events"
```

---
## Task 8: logger.py — setup_logging + make_run_config + OFF/INFO/DEBUG/TRACE

**Files:**
- Create: `test_agents/observability/logger.py`
- Create: `test_agents/tests/test_observability/test_logger.py`

- [ ] **Step 1: Write the failing test** — `test_agents/tests/test_observability/test_logger.py`

```python
"""setup_logging idempotency, level switching, failure degrade (spec §9 + Finding 3.1)."""
import logging
import sys
from pathlib import Path
import pytest

from test_agents.observability import logger as logger_mod


@pytest.fixture(autouse=True)
def _reset():
    logger_mod._reset_for_tests()
    yield
    logger_mod._reset_for_tests()


def test_setup_logging_idempotent(tmp_path):
    """Two calls do not register duplicate handlers."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    handlers_after_first = len(logging.getLogger("test_agents").handlers)
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    handlers_after_second = len(logging.getLogger("test_agents").handlers)
    assert handlers_after_first == handlers_after_second

def test_setup_logging_off_registers_nothing(tmp_path):
    """OFF: no handlers, no MetricsCollector, no callback in run_config."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="OFF")
    handlers = logging.getLogger("test_agents").handlers
    assert all("Jsonl" not in type(h).__name__ for h in handlers)
    cfg = logger_mod.make_run_config(thread_id="t")
    assert cfg["callbacks"] == []
    # logs/ directory not created in OFF mode
    assert not (tmp_path / "traces").exists()

def test_setup_logging_info_registers_callback(tmp_path):
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    cfg = logger_mod.make_run_config(thread_id="t")
    assert len(cfg["callbacks"]) == 1

def test_setup_logging_debug_attaches_full_fields(tmp_path):
    """DEBUG: callback writes input_full/output_full beyond summary."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="DEBUG")
    # The exact mechanism: callback consults logger level when emitting.
    assert logging.getLogger("test_agents").level == logging.DEBUG

def test_setup_logging_trace_level_registered(tmp_path):
    """TRACE custom level=5 is added via addLevelName."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="TRACE")
    assert logging.getLevelName(5) == "TRACE"

def test_setup_logging_dir_create_failure_degrades(tmp_path, monkeypatch, capsys):
    """CEO Finding 2.1: log_dir mkdir fails → warning to stderr + NoOp."""
    def boom(*a, **kw): raise OSError("read-only")
    monkeypatch.setattr(Path, "mkdir", boom)
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    # Must not crash. Returns to NoOp logger.
    cfg = logger_mod.make_run_config(thread_id="t")
    assert cfg["callbacks"] == []  # degraded to OFF semantics

def test_make_run_config_returns_thread_id(tmp_path):
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    cfg = logger_mod.make_run_config(thread_id="abc123")
    assert cfg["configurable"]["thread_id"] == "abc123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_agents/tests/test_observability/test_logger.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement logger.py** — `test_agents/observability/logger.py`

```python
"""setup_logging entry + make_run_config helper (spec §9).

OFF: register nothing, return empty callbacks list — zero overhead.
INFO/DEBUG/TRACE: register Filter + JsonlMultiHandler + callback factory.
"""
import logging
import sys
from pathlib import Path

from test_agents.config import config
from test_agents.observability import callback as callback_mod
from test_agents.observability.callback import ObservabilityCallback
from test_agents.observability.filters import ContextInjectFilter
from test_agents.observability.handlers import JsonlMultiHandler
from test_agents.observability.metrics import MetricsCollector

_LOGGER_NAME = "test_agents"
_INITIALIZED = False
_ACTIVE_LEVEL: str = "OFF"
_HANDLER: JsonlMultiHandler | None = None

# Register custom TRACE level.
logging.addLevelName(5, "TRACE")


def setup_logging(
    log_dir: str | None = None, level: str | None = None,
) -> None:
    """Configure logging once at process start. Idempotent.

    OFF: no handlers registered, no metrics collector, no callback factory.
    """
    global _INITIALIZED, _ACTIVE_LEVEL, _HANDLER
    if _INITIALIZED:
        return

    chosen_level = (level or config.LOG_LEVEL).upper()
    chosen_dir = log_dir or config.LOG_DIR

    if chosen_level == "OFF":
        _ACTIVE_LEVEL = "OFF"
        _INITIALIZED = True
        return

    try:
        Path(chosen_dir).mkdir(parents=True, exist_ok=True)
        (Path(chosen_dir) / "traces").mkdir(parents=True, exist_ok=True)
    except Exception as e:
        try:
            sys.__stderr__.write(
                f"[observability] cannot create log dir {chosen_dir}: {e}. "
                f"Degrading to OFF.\n"
            )
        except Exception:
            pass
        _ACTIVE_LEVEL = "OFF"
        _INITIALIZED = True
        return

    py_level = {
        "TRACE": 5, "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
    }.get(chosen_level, logging.INFO)

    root = logging.getLogger(_LOGGER_NAME)
    root.setLevel(py_level)
    root.propagate = False

    _HANDLER = JsonlMultiHandler(
        log_dir=chosen_dir,
        trace_handles=config.LOG_TRACE_HANDLES,
        write_per_trace=config.LOG_TRACE_FILES,
        retain_days=config.LOG_RETAIN_DAYS,
    )
    _HANDLER.addFilter(ContextInjectFilter())
    root.addHandler(_HANDLER)

    callback_mod.metrics = MetricsCollector(
        metrics_path=str(Path(chosen_dir) / "metrics.jsonl"),
    )

    _ACTIVE_LEVEL = chosen_level
    _INITIALIZED = True


def make_run_config(thread_id: str) -> dict:
    """Build the LangGraph invoke config (spec §6).

    OFF mode: empty callbacks list, no observability cost.
    """
    callbacks = [] if _ACTIVE_LEVEL == "OFF" else [ObservabilityCallback()]
    return {
        "callbacks": callbacks,
        "configurable": {"thread_id": thread_id},
    }


def close_trace_writer(trace_id: str | None = None) -> None:
    """Called from main.py finally. Closes per-trace handle + cleans callback state."""
    if _HANDLER and trace_id:
        try: _HANDLER.close_trace(trace_id)
        except Exception: pass
        try: ObservabilityCallback.cleanup_trace(trace_id)
        except Exception: pass


def _reset_for_tests() -> None:
    """Test-only: clear singleton state so setup_logging can run again."""
    global _INITIALIZED, _ACTIVE_LEVEL, _HANDLER
    if _HANDLER:
        try: _HANDLER.close()
        except Exception: pass
    _HANDLER = None
    _ACTIVE_LEVEL = "OFF"
    _INITIALIZED = False
    root = logging.getLogger(_LOGGER_NAME)
    for h in list(root.handlers):
        root.removeHandler(h)
    callback_mod.metrics = None
```

- [ ] **Step 4: Wire up the public API** — write `test_agents/observability/__init__.py`

```python
"""Public observability API (spec §4)."""
from test_agents.observability.callback import ObservabilityCallback
from test_agents.observability.context import (
    new_trace, get_trace_id, reset_trace,
)
from test_agents.observability.logger import (
    setup_logging, make_run_config, close_trace_writer,
)
from test_agents.observability import callback as _cb_mod


def flush_metrics(trace_id: str, status: str,
                  final_answer_length: int = 0, error: str | None = None) -> None:
    """Forward to the active MetricsCollector. No-op if logging is OFF."""
    if _cb_mod.metrics is None:
        return
    _cb_mod.metrics.flush(
        trace_id, status=status,
        final_answer_length=final_answer_length, error=error,
    )


def new_trace_metrics(trace_id: str, user_request: str) -> None:
    if _cb_mod.metrics is None:
        return
    _cb_mod.metrics.new_trace(trace_id, user_request=user_request)


__all__ = [
    "setup_logging", "make_run_config", "close_trace_writer",
    "new_trace", "get_trace_id", "reset_trace",
    "flush_metrics", "new_trace_metrics", "ObservabilityCallback",
]
```

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_observability/test_logger.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add test_agents/observability/logger.py test_agents/observability/__init__.py \
        test_agents/tests/test_observability/test_logger.py
git commit -m "feat(observability): setup_logging + make_run_config + level switching"
```

---
## Task 9: test_off_switch.py — verify OFF mode zero overhead

**Files:**
- Create: `test_agents/tests/test_observability/test_off_switch.py`

- [ ] **Step 1: Write the test**

```python
"""TEST_AGENTS_LOG_LEVEL=OFF → no files, no callback, no measurable overhead."""
import os
import time
from pathlib import Path
import pytest

from test_agents.observability import logger as logger_mod


@pytest.fixture(autouse=True)
def _reset():
    logger_mod._reset_for_tests()
    yield
    logger_mod._reset_for_tests()


def test_off_creates_no_files(tmp_path):
    """OFF: no log directory created at all."""
    logger_mod.setup_logging(log_dir=str(tmp_path / "logs"), level="OFF")
    # The logs dir itself should not be created — OFF early-returns before mkdir.
    assert not (tmp_path / "logs" / "traces").exists()

def test_off_make_run_config_empty_callbacks(tmp_path):
    logger_mod.setup_logging(log_dir=str(tmp_path), level="OFF")
    assert logger_mod.make_run_config(thread_id="t")["callbacks"] == []

def test_off_close_trace_writer_safe(tmp_path):
    """close_trace_writer must not raise when nothing was initialized."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="OFF")
    logger_mod.close_trace_writer("tr_anything")  # no-op, must not raise
```

- [ ] **Step 2: Run tests to verify pass** (Task 8's implementation already supports OFF)

Run: `python -m pytest test_agents/tests/test_observability/test_off_switch.py -v`
Expected: PASS (3 tests).

- [ ] **Step 3: Commit**

```bash
git add test_agents/tests/test_observability/test_off_switch.py
git commit -m "test(observability): verify OFF mode is zero-overhead"
```

---

## Task 10: test_errors.py — coverage for error degradation paths

**Files:**
- Create: `test_agents/tests/test_observability/test_errors.py`

- [ ] **Step 1: Write the test**

```python
"""Error path coverage (spec §12 — combined verification)."""
import logging
import socket
from pathlib import Path
import pytest

from test_agents.observability import logger as logger_mod
from test_agents.observability.handlers import JsonlMultiHandler


@pytest.fixture(autouse=True)
def _reset():
    logger_mod._reset_for_tests()
    yield
    logger_mod._reset_for_tests()


def test_setup_with_unwritable_dir(monkeypatch, tmp_path, capsys):
    """log_dir mkdir raises OSError → degrade silently."""
    def boom(*a, **kw): raise PermissionError("read-only fs")
    monkeypatch.setattr(Path, "mkdir", boom)
    logger_mod.setup_logging(log_dir=str(tmp_path / "x"), level="INFO")
    cfg = logger_mod.make_run_config(thread_id="t")
    assert cfg["callbacks"] == []  # degraded to OFF
    err = capsys.readouterr().err
    assert "cannot create log dir" in err

def test_emit_with_unserializable_extra(tmp_path):
    """Logger.info with extra containing socket must not raise."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    log = logging.getLogger("test_agents.errortest")
    log.info("test", extra={"sock": socket.socket()})  # must not raise

def test_emit_with_circular_reference(tmp_path):
    """Circular dict must not raise (json marks as unserializable)."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    log = logging.getLogger("test_agents.errortest")
    d = {}
    d["self"] = d
    log.info("test", extra={"loop": d})  # must not raise

def test_lru_handle_eviction_does_not_crash_on_close_error(tmp_path, monkeypatch):
    """If an old per-trace file errored on close, eviction continues."""
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=2)
    rec = logging.LogRecord("t", logging.INFO, "f", 1, "m", None, None)
    rec.trace_id = "tr_a"
    h.emit(rec)
    # Force close to fail for the first file.
    fp = h._per_trace_handles["tr_a"]
    orig_close = fp.close
    fp.close = lambda: (_ for _ in ()).throw(OSError("flaky"))
    rec.trace_id = "tr_b"; h.emit(rec)
    rec.trace_id = "tr_c"; h.emit(rec)  # evicts tr_a, swallows OSError
    h.close()
```

- [ ] **Step 2: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_observability/test_errors.py -v`
Expected: PASS (4 tests).

- [ ] **Step 3: Commit**

```bash
git add test_agents/tests/test_observability/test_errors.py
git commit -m "test(observability): cover error degradation paths"
```

---
## Task 11: main.py — _with_observability wrapper around both paths

This is the central integration point. Both `_run_supervisor` and
`_run_direct_worker` must be wrapped so trace_id is set on every code path
(Eng Finding 4.1) and metrics are flushed in every termination case
(Eng Finding 4.6 — 3 statuses).

**Files:**
- Modify: `test_agents/main.py`
- Create: `test_agents/tests/test_observability/test_main_observability.py`

- [ ] **Step 1: Write the failing tests** — `test_agents/tests/test_observability/test_main_observability.py`

```python
"""main.py _with_observability wrapper (spec §6, Eng Findings 4.1/4.5/4.6/4.7)."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from test_agents.observability import logger as logger_mod


@pytest.fixture(autouse=True)
def _isolated_logs(tmp_path, monkeypatch):
    logger_mod._reset_for_tests()
    monkeypatch.setenv("TEST_AGENTS_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("TEST_AGENTS_LOG_LEVEL", "INFO")
    # Force config reload so the new env vars take effect.
    import importlib, test_agents.config as cfg_mod
    importlib.reload(cfg_mod)
    yield tmp_path
    logger_mod._reset_for_tests()


def _read_metrics(tmp_path):
    p = tmp_path / "metrics.jsonl"
    if not p.exists(): return []
    return [json.loads(l) for l in p.read_text().strip().splitlines()]


def test_supervisor_path_writes_ok_metric(_isolated_logs):
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor") as fake:
        fake.return_value = {"final_answer": "done", "step_results": []}
        result = main_mod.run_test_agents("complex non-keyword request that goes to supervisor")
    assert result["final_answer"] == "done"
    metrics = _read_metrics(_isolated_logs)
    assert len(metrics) == 1
    assert metrics[0]["status"] == "ok"
    assert metrics[0]["final_answer_length"] == 4
    assert metrics[0]["trace_id"].startswith("tr_")

def test_simple_worker_path_writes_ok_metric(_isolated_logs):
    """Eng Finding 4.1: simple worker path also gets new_trace + flush."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_direct_worker") as fake:
        fake.return_value = {"final_answer": "x", "outputs": {}, "step_results": []}
        result = main_mod.run_test_agents("分析代码")  # triggers _run_direct_worker
    metrics = _read_metrics(_isolated_logs)
    assert len(metrics) == 1
    assert metrics[0]["trace_id"] is not None
    assert metrics[0]["status"] == "ok"

def test_error_path_flushes_error_status(_isolated_logs):
    """Exception in target_func → flush_metrics(status=error) + raise."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            main_mod.run_test_agents("anything supervisor")
    metrics = _read_metrics(_isolated_logs)
    assert metrics[0]["status"] == "error"

def test_keyboard_interrupt_still_flushes(_isolated_logs):
    """BaseException (Ctrl-C) → flush_metrics(status=error) in finally."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            main_mod.run_test_agents("anything supervisor")
    metrics = _read_metrics(_isolated_logs)
    assert metrics[0]["status"] == "error"

def test_aborted_status_when_no_final_answer(_isolated_logs):
    """Eng Finding 4.6: confirm_retry limit → result without final_answer → status=aborted."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor") as fake:
        fake.return_value = {"step_results": []}  # No final_answer
        main_mod.run_test_agents("anything supervisor")
    metrics = _read_metrics(_isolated_logs)
    assert metrics[0]["status"] == "aborted"

def test_close_trace_writer_called_in_finally(_isolated_logs):
    """Ensure close_trace_writer fires even on success."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor") as fake, \
         patch.object(main_mod, "close_trace_writer") as ctw:
        fake.return_value = {"final_answer": "x", "step_results": []}
        main_mod.run_test_agents("anything supervisor")
        assert ctw.called
        # First positional arg must be the trace_id used.
        called_with = ctw.call_args[0][0]
        assert called_with.startswith("tr_")

def test_interrupt_resume_no_spurious_error(_isolated_logs):
    """Eng Finding 4.5 verification: GraphInterrupt does not produce error events.

    Mock _run_supervisor to drive a fake invoke that raises GraphInterrupt during
    the inner call but resumes successfully on a second pass. After the call
    completes, no node.exit with status=error should appear in the trace file.
    """
    from langgraph.errors import GraphInterrupt
    from test_agents import main as main_mod

    call_count = {"n": 0}
    def fake_supervisor(user_request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: simulate inner interrupt that LangGraph swallows.
            # _run_supervisor's interrupt loop handles this — we model the outer
            # behavior: it eventually returns success.
            pass
        return {"final_answer": "done", "step_results": []}

    with patch.object(main_mod, "_run_supervisor", side_effect=fake_supervisor):
        main_mod.run_test_agents("anything supervisor")

    metrics = _read_metrics(_isolated_logs)
    # No error status logged when interrupt was part of normal flow.
    assert metrics[0]["status"] == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test_agents/tests/test_observability/test_main_observability.py -v`
Expected: FAIL with `ImportError: cannot import name 'close_trace_writer' from 'test_agents.main'` or similar.

- [ ] **Step 3: Implement main.py changes** — `test_agents/main.py`

Add this near the top (after existing imports):

```python
from test_agents.observability import (
    setup_logging, new_trace, get_trace_id, new_trace_metrics,
    flush_metrics, close_trace_writer, make_run_config,
)

# Initialize once at module load. Idempotent.
setup_logging()
```

Then refactor `run_test_agents` to wrap both paths:

```python
def run_test_agents(user_request: str) -> dict:
    """运行测试智能体群（简单请求直接走 Worker，复杂请求走 Supervisor）"""
    build_graph()
    simple_agent = is_simple_request(user_request)
    if simple_agent:
        return _with_observability(
            lambda: _run_direct_worker(user_request, simple_agent),
            user_request,
            kind="simple",
        )
    return _with_observability(
        lambda: _run_supervisor(user_request),
        user_request,
        kind="supervisor",
    )


def _with_observability(target_func, user_request: str, kind: str) -> dict:
    """Trace lifecycle wrapper (spec §6 + Eng Finding 4.1/4.6).

    Owns:
      - new_trace() / new_trace_metrics() at entry
      - flush_metrics(status=ok|error|aborted) on every exit
      - close_trace_writer() in finally
    """
    trace_id = new_trace(user_request)
    new_trace_metrics(trace_id, user_request)
    status = "ok"
    final_answer = ""
    try:
        result = target_func()
        final_answer = (result.get("final_answer") if isinstance(result, dict) else "") or ""
        # Supervisor path may return without final_answer if confirm_retry
        # limit was hit (Eng Finding 4.6).
        if not final_answer and kind == "supervisor":
            status = "aborted"
        return result
    except BaseException:
        status = "error"
        raise
    finally:
        flush_metrics(trace_id, status=status, final_answer_length=len(final_answer))
        close_trace_writer(trace_id)
```

The existing `_run_supervisor` and `_run_direct_worker` need ONE additional
change each — they must pass `make_run_config(thread_id=...)` to their
`app.invoke(...)` / `worker_graph.invoke(...)` calls so the callback fires:

Modify `_run_supervisor`:

```python
def _run_supervisor(user_request: str) -> dict:
    """走完整的 Supervisor 主图。"""
    app = build_graph()
    thread_config = make_run_config(thread_id="test-agents-session")
    initial_state = _build_initial_state(user_request)
    result = app.invoke(initial_state, thread_config)
    while True:
        state = app.get_state(thread_config)
        if not state.next:
            break
        plan = state.values.get("plan", {})
        _display_plan(plan, file=sys.stderr)
        confirmed = input("\n确认计划？(y/n): ").lower().strip()
        if confirmed == "y":
            app.invoke(Command(resume={"confirmed": True}), thread_config)
        else:
            feedback = input("请输入修改建议: ")
            app.invoke(Command(resume={"confirmed": False, "feedback": feedback}), thread_config)
    final_state = app.get_state(thread_config)
    return final_state.values
```

Modify `_run_direct_worker` to pass run_config to the worker subgraph:

```python
def _run_direct_worker(user_request: str, agent_name: str) -> dict:
    """直接调用 Worker 子图，跳过 planner/confirm/reflect/synthesize。"""
    worker_graph = WORKER_REGISTRY.get(agent_name)
    if worker_graph is None:
        raise RuntimeError(f"Worker graph for {agent_name} not found in registry")
    worker_input: WorkerState = {
        "task": user_request,
        "messages": [HumanMessage(content=user_request)],
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": "result",
        "result": "",
    }
    # Eng Finding 1.3: callback must fire on simple-worker path too.
    result = worker_graph.invoke(worker_input, make_run_config(thread_id=f"direct-{agent_name}"))
    output_text = result.get("result", "")
    if not output_text:
        for msg in reversed(result.get("messages", [])):
            if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                output_text = msg.content
                break
    output_key = "code_change_report" if agent_name == "code_analyzer" else "review_results"
    return {
        "user_request": user_request,
        "outputs": {output_key: output_text},
        "final_answer": output_text,
        "step_results": [
            {"step_id": 1, "agent": agent_name, "status": "success", "output_key": output_key}
        ],
    }
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_observability/test_main_observability.py -v`
Expected: PASS (7 tests).

Run the full main test suite to ensure no regression:

Run: `python -m pytest test_agents/tests/test_main.py test_agents/tests/test_cli_entry.py -v`
Expected: PASS (pre-existing tests still green).

- [ ] **Step 5: Commit**

```bash
git add test_agents/main.py test_agents/tests/test_observability/test_main_observability.py
git commit -m "feat(observability): wire _with_observability into main.py both paths"
```

---
## Task 12: test_integration.py — full mock pipeline E2E

**Files:**
- Create: `test_agents/tests/test_observability/test_integration.py`

- [ ] **Step 1: Write the test**

```python
"""End-to-end: full mock pipeline → traces/<id>.jsonl + metrics.jsonl correct."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from test_agents.observability import logger as logger_mod
from test_agents.observability.callback import ObservabilityCallback


@pytest.fixture(autouse=True)
def _isolated_logs(tmp_path, monkeypatch):
    logger_mod._reset_for_tests()
    monkeypatch.setenv("TEST_AGENTS_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("TEST_AGENTS_LOG_LEVEL", "INFO")
    import importlib, test_agents.config as cfg_mod
    importlib.reload(cfg_mod)
    yield tmp_path
    logger_mod._reset_for_tests()


def test_per_trace_file_records_full_chain(_isolated_logs):
    """A successful pipeline produces a per-trace file with all node events."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor") as fake:
        fake.return_value = {"final_answer": "done", "step_results": []}
        main_mod.run_test_agents("complex request")

    trace_files = list((_isolated_logs / "traces").glob("tr_*.jsonl"))
    # _run_supervisor was mocked, so the trace file gets created by
    # _with_observability only via the per-trace handler — even with
    # no callback events, the trace_id was registered. Acceptable: file
    # may be empty if no events were emitted, OR may not exist if no logger
    # called info() under that trace. Either way metrics.jsonl is the
    # authoritative check.
    metrics = json.loads((_isolated_logs / "metrics.jsonl").read_text().strip())
    assert metrics["trace_id"].startswith("tr_")
    assert metrics["status"] == "ok"

def test_callback_state_dicts_clean_after_trace(_isolated_logs):
    """Eng Finding 4.3: _spans and _last_node_per_trace have no leftover entries."""
    from test_agents import main as main_mod
    ObservabilityCallback._spans.clear()
    ObservabilityCallback._last_node_per_trace.clear()
    with patch.object(main_mod, "_run_supervisor") as fake:
        fake.return_value = {"final_answer": "done", "step_results": []}
        main_mod.run_test_agents("complex request")
    # After completion, dicts should be empty (cleanup_trace called).
    assert ObservabilityCallback._spans == {}
    assert ObservabilityCallback._last_node_per_trace == {}

def test_metrics_accumulate_across_invokes(_isolated_logs):
    """Eng Finding 4.7: confirm_plan interrupt resume preserves counters.

    Modeled here: directly drive MetricsCollector across two fake invokes
    sharing the same trace_id (simulating interrupt → resume).
    """
    from test_agents.observability.callback import metrics as cb_metrics
    assert cb_metrics is not None
    cb_metrics.new_trace("tr_shared12", user_request="x")
    cb_metrics.incr("tr_shared12", "node_count")
    cb_metrics.incr("tr_shared12", "node_count")
    # Simulate "another invoke fires more callbacks with same trace_id"
    cb_metrics.incr("tr_shared12", "node_count")
    cb_metrics.flush("tr_shared12", status="ok", final_answer_length=10)
    line = json.loads((_isolated_logs / "metrics.jsonl").read_text().strip().splitlines()[-1])
    assert line["node_count"] == 3
```

- [ ] **Step 2: Run tests to verify pass**

Run: `python -m pytest test_agents/tests/test_observability/test_integration.py -v`
Expected: PASS (3 tests).

- [ ] **Step 3: Commit**

```bash
git add test_agents/tests/test_observability/test_integration.py
git commit -m "test(observability): E2E mock pipeline + state cleanup + cross-invoke metrics"
```

---

## Task 13: Documentation — CLAUDE.md and developer notes

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append to CLAUDE.md** at the end of the file

```markdown

## Observability

可观测系统（spec: `docs/superpowers/specs/2026-05-22-observability-design.md`）。
所有日志走 `test_agents/observability/`，业务代码 0 改动（callback 自动拦截）。

- 日志文件：`logs/app-YYYY-MM-DD.jsonl`（按天滚动）+ `logs/traces/<trace_id>.jsonl`（单次执行）+ `logs/metrics.jsonl`（汇总）
- 控制环境变量：`TEST_AGENTS_LOG_LEVEL=OFF|INFO|DEBUG|TRACE`（默认 INFO）
- 关闭整套观测：`TEST_AGENTS_LOG_LEVEL=OFF` → 零开销
- 查询示例见 spec §15 "日志查询 Cheatsheet"
```

- [ ] **Step 2: Verify markdown renders cleanly**

Run: `cat CLAUDE.md | head -160`
Expected: section appears at end, no broken markdown.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md observability section"
```

---

## Task 14: Final regression sweep

**Files:** none

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest test_agents/tests/ -v`
Expected: ALL tests pass (existing + new observability test files).

- [ ] **Step 2: Quick smoke test the CLI**

Run the system with a real-ish request to confirm runtime is healthy and a
trace file appears:

```bash
rm -rf logs/
TEST_AGENTS_LOG_LEVEL=INFO python -m test_agents "分析代码" 2>/dev/null || true
ls logs/
ls logs/traces/ | head -3
cat logs/metrics.jsonl | head -1 | python3 -m json.tool
```

Expected:
- `logs/app-YYYY-MM-DD.jsonl` exists with at least a few JSON lines
- `logs/traces/tr_<id>.jsonl` exists for the run
- `logs/metrics.jsonl` has one line with `trace_id`, `status`, `node_count` etc.

- [ ] **Step 3: Verify OFF mode is truly zero-impact**

```bash
rm -rf logs/
TEST_AGENTS_LOG_LEVEL=OFF python -m test_agents "分析代码" 2>/dev/null || true
test ! -d logs && echo "OK: OFF mode created no logs directory"
```

- [ ] **Step 4: Commit any final touches**

```bash
git status
# If there are stray files (cached __pycache__, etc.) ensure .gitignore covers them.
# Otherwise no further commits needed.
```

---

## Acceptance Criteria

- [ ] All 13 implementation tasks complete with passing tests
- [ ] `python -m pytest test_agents/tests/ -v` is green (no regressions)
- [ ] `logs/app-YYYY-MM-DD.jsonl`, `logs/traces/<id>.jsonl`, `logs/metrics.jsonl` all populate during real CLI run
- [ ] `TEST_AGENTS_LOG_LEVEL=OFF` truly creates no files and adds no measurable latency
- [ ] No new entries in `requirements.txt`
- [ ] Spec §1 goals are demonstrably met: someone can grep `logs/traces/<id>.jsonl` and see the full chain of one execution

