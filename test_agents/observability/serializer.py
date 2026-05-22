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
