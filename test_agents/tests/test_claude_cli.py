import pytest
from unittest.mock import patch, MagicMock
from test_agents.tools.claude_cli import ClaudeCliTool


def test_claude_cli_tool_escapes_prompt():
    """测试 prompt 中的特殊字符被正确处理"""
    tool = ClaudeCliTool()
    # 包含引号和换行的 prompt
    prompt = 'Say "hello"\nThen say "world"'
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="hello world", stderr="")
        result = tool.run({"prompt": prompt})
        assert result == "hello world"
        # 验证调用参数
        args = mock_run.call_args[0][0]
        assert args[0] == "claude"
        assert args[1] == "--dangerously-skip-permissions"
        assert args[2] == "-p"
        assert args[3] == prompt


def test_claude_cli_tool_timeout():
    """测试超时处理"""
    tool = ClaudeCliTool(timeout_seconds=1)
    with patch("subprocess.run") as mock_run:
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired("claude", 1)
        result = tool.run({"prompt": "test"})
        assert "超时" in result


def test_claude_cli_tool_not_found():
    """测试 Claude CLI 未安装"""
    tool = ClaudeCliTool()
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("claude")
        result = tool.run({"prompt": "test"})
        assert "未找到" in result
