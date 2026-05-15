from unittest.mock import patch
from test_agents.main import run_test_agents


def test_full_pipeline_mocked():
    """测试完整流程（使用 mock）"""
    with patch("test_agents.tools.claude_cli.ClaudeCliTool.run") as mock_claude:
        mock_claude.side_effect = [
            "## 变更概述\n新增订单功能",
            '[{"case_id": "TC001", "verdict": "pass", "score": 90}]',
        ]

        result = run_test_agents(
            module_name="order",
            source_commit="a1b2c3d",
            target_commit="e4f5a6b",
            test_cases='[{"case_id":"TC001","title":"test order"}]',
        )

        assert "code_change_report" in result
        assert "review_results" in result
        assert result["review_results"][0]["verdict"] == "pass"


def test_pipeline_with_error():
    """测试错误处理流程"""
    with patch("test_agents.tools.claude_cli.ClaudeCliTool.run") as mock_claude:
        mock_claude.return_value = "错误: Claude CLI 调用失败"

        result = run_test_agents(
            module_name="order",
            source_commit="a1b2c3d",
            target_commit="e4f5a6b",
        )

        assert "error" in result
