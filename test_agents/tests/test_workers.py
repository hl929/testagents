from unittest.mock import MagicMock, patch

from test_agents.agents.code_analyzer import build_code_analyzer_graph, code_analyzer_wrapper
from test_agents.agents.case_reviewer import build_case_reviewer_graph, case_reviewer_wrapper
from test_agents.graph.state import SupervisorState


class TestCodeAnalyzerGraph:
    def test_builds_code_analyzer_graph(self):
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        graph = build_code_analyzer_graph(mock_llm, mock_llm_with_tools)
        assert graph is not None

    def test_code_analyzer_wrapper_returns_report(self):
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "result": "## 变更概述\n新增订单功能",
            "messages": [],
            "error": "no",
        }
        state: SupervisorState = {
            "user_request": "分析代码",
            "plan": {
                "intent": "分析代码变更",
                "steps": [
                    {"step_id": 1, "agent": "code_analyzer", "description": "分析 payment 模块",
                     "input_mapping": {"module_name": "payment", "source_commit": "abc1234", "target_commit": "def5678"}},
                ],
                "confirmed": True,
            },
            "current_step_index": 0,
            "step_results": [],
            "messages": [],
        }
        with patch("test_agents.agents.code_analyzer.code_analyzer_graph", mock_graph):
            result = code_analyzer_wrapper(state)
        assert "outputs" in result
        assert "code_change_report" in result["outputs"]
        assert "变更概述" in result["outputs"]["code_change_report"]
        assert result["current_step_index"] == 1

    def test_code_analyzer_wrapper_writes_to_outputs(self):
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "result": "## 变更概述\n新增订单功能",
            "messages": [],
            "error": "no",
        }
        state: SupervisorState = {
            "user_request": "分析代码",
            "plan": {
                "intent": "分析代码变更",
                "steps": [
                    {"step_id": 1, "agent": "code_analyzer", "description": "分析 payment 模块",
                     "input_mapping": {"module_name": "payment", "source_commit": "abc1234", "target_commit": "def5678"},
                     "output_key": "code_change_report"},
                ],
                "confirmed": True,
            },
            "current_step_index": 0,
            "step_results": [],
            "messages": [],
        }
        with patch("test_agents.agents.code_analyzer.code_analyzer_graph", mock_graph):
            result = code_analyzer_wrapper(state)
        assert "outputs" in result
        assert "code_change_report" in result["outputs"]
        assert "变更概述" in result["outputs"]["code_change_report"]
        assert result["current_step_index"] == 1


class TestCaseReviewerGraph:
    def test_builds_case_reviewer_graph(self):
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        graph = build_case_reviewer_graph(mock_llm, mock_llm_with_tools)
        assert graph is not None

    def test_case_reviewer_wrapper_returns_results(self):
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "result": '[{"case_id": "TC001", "verdict": "pass"}]',
            "messages": [],
            "error": "no",
        }
        state: SupervisorState = {
            "user_request": "评审用例",
            "plan": {
                "intent": "评审测试用例",
                "steps": [
                    {"step_id": 2, "agent": "case_reviewer", "description": "评审用例",
                     "input_mapping": {"code_change_report": "${outputs.code_change_report}"}},
                ],
                "confirmed": True,
            },
            "current_step_index": 0,
            "outputs": {"code_change_report": "变更报告"},
            "step_results": [],
            "messages": [],
        }
        with patch("test_agents.agents.case_reviewer.case_reviewer_graph", mock_graph):
            result = case_reviewer_wrapper(state)
        assert "outputs" in result
        assert "review_results" in result["outputs"]
        assert result["current_step_index"] == 1

    def test_case_reviewer_wrapper_writes_to_outputs(self):
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "result": '[{"case_id": "TC001", "verdict": "pass"}]',
            "messages": [],
            "error": "no",
        }
        state: SupervisorState = {
            "user_request": "评审用例",
            "plan": {
                "intent": "评审测试用例",
                "steps": [
                    {"step_id": 2, "agent": "case_reviewer", "description": "评审用例",
                     "input_mapping": {"code_change_report": "${outputs.code_change_report}"},
                     "output_key": "review_results"},
                ],
                "confirmed": True,
            },
            "current_step_index": 0,
            "outputs": {"code_change_report": "变更报告"},
            "step_results": [],
            "messages": [],
        }
        with patch("test_agents.agents.case_reviewer.case_reviewer_graph", mock_graph):
            result = case_reviewer_wrapper(state)
        assert "outputs" in result
        assert "review_results" in result["outputs"]
        assert result["outputs"]["review_results"][0]["case_id"] == "TC001"
        assert result["current_step_index"] == 1
