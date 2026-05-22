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
