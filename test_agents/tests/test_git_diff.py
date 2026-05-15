import pytest
from test_agents.tools.git_diff import GitDiffTool, extract_diff_summary


def test_extract_diff_summary_with_changes():
    diff = """diff --git a/order.py b/order.py
+def new_func():
+    pass
"""
    result = extract_diff_summary(diff)
    assert "order.py" in result


def test_extract_diff_summary_empty():
    result = extract_diff_summary("")
    assert result == "无变更"


def test_git_diff_tool_validates_sha():
    tool = GitDiffTool()
    with pytest.raises(ValueError, match="Invalid commit SHA"):
        tool.run({
            "module_name": "order",
            "source_commit": "bad!",
            "target_commit": "e4f5a6b",
        })


def test_git_diff_tool_validates_module():
    tool = GitDiffTool()
    with pytest.raises(ValueError, match="Invalid module name"):
        tool.run({
            "module_name": "../../etc",
            "source_commit": "a1b2c3d",
            "target_commit": "e4f5a6b",
        })
