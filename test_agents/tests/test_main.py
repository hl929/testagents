from unittest.mock import patch, MagicMock

from test_agents.main import is_simple_request, run_test_agents


class TestIsSimpleRequest:
    def test_code_analysis_detected(self):
        assert is_simple_request("分析 payment 模块代码变更") == "code_analyzer"

    def test_code_change_keyword(self):
        assert is_simple_request("查看 code change") == "code_analyzer"

    def test_case_review_detected(self):
        assert is_simple_request("评审测试用例") == "case_reviewer"

    def test_complex_request_returns_none(self):
        assert is_simple_request("分析代码变更并评审测试用例") is None

    def test_unknown_request_returns_none(self):
        assert is_simple_request("帮我写个测试") is None


class TestRunTestAgents:
    def test_supervisor_mode_invoked(self):
        mock_app = MagicMock()
        mock_app.invoke.return_value = {"final_answer": "结果"}
        mock_state = MagicMock(next=[])
        mock_state.values = {"final_answer": "结果"}
        mock_app.get_state.return_value = mock_state
        with patch("test_agents.main.build_graph", return_value=mock_app):
            result = run_test_agents("分析代码变更并评审测试用例")
        assert "final_answer" in result