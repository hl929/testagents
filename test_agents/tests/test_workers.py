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


from test_agents.agents.worker_base import worker_reflect, _extract_last_agent_content
from langchain_core.messages import AIMessage


class TestWorkerReflect:
    def test_reflect_pass_writes_back_result(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"quality": "pass", "feedback": ""}')
        state = {
            "task": "test",
            "messages": [
                AIMessage(content="first", tool_calls=[]),
                AIMessage(content="final result"),
            ],
            "reflection_count": 0,
            "max_reflections": 1,
            "result": "",
        }
        result = worker_reflect(state, mock_llm)
        assert result["error"] == "no"
        assert result["result"] == "final result"

    def test_reflect_no_max_reflections_writes_back_result(self):
        state = {
            "task": "test",
            "messages": [AIMessage(content="agent output")],
            "reflection_count": 0,
            "max_reflections": 0,
            "result": "",
        }
        result = worker_reflect(state, MagicMock())
        assert result["error"] == "no"
        assert result["result"] == "agent output"

    def test_extract_last_agent_content_skips_tool_calls(self):
        # Create AIMessage with tool calls by setting tool_calls as empty list
        # since the actual format depends on langchain version
        msg_with_tool = AIMessage(content="tool call")
        msg_with_tool.tool_calls = [{"name": "test"}]  # Simplified format

        state = {
            "messages": [
                msg_with_tool,
                AIMessage(content="final content", tool_calls=[]),
            ],
            "result": "old result",
        }
        assert _extract_last_agent_content(state) == "final content"

    def test_extract_last_agent_content_uses_result_if_no_messages(self):
        state = {
            "messages": [],
            "result": "fallback result",
        }
        assert _extract_last_agent_content(state) == "fallback result"

    def test_extract_last_agent_content_skips_empty_messages(self):
        state = {
            "messages": [
                AIMessage(content="", tool_calls=[]),
                AIMessage(content="valid content", tool_calls=[]),
            ],
            "result": "",
        }
        assert _extract_last_agent_content(state) == "valid content"
