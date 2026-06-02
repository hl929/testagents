"""Tests for data_analyst worker"""

from unittest.mock import MagicMock, patch

from test_agents.agents.data_analyst import (
    build_data_analyst_graph,
    data_analyst_wrapper,
    data_analyst_graph,
)
from test_agents.graph.state import SupervisorState


class TestBuildDataAnalystGraph:
    def test_builds_graph(self):
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        graph = build_data_analyst_graph(mock_llm, mock_llm_with_tools)
        assert graph is not None


class TestDataAnalystWrapper:
    def test_no_worker_input_returns_empty(self):
        state: SupervisorState = {
            "user_request": "分析缺陷趋势",
            "plan": {"intent": "数据分析", "steps": [], "confirmed": True},
            "current_step_index": 0,
            "step_results": [],
            "messages": [],
            "outputs": {},
        }
        result = data_analyst_wrapper(state)
        assert result == {}

    def test_graph_not_initialized_raises(self):
        state: SupervisorState = {
            "user_request": "分析缺陷趋势",
            "plan": {
                "intent": "数据分析",
                "steps": [
                    {"step_id": 1, "agent": "data_analyst", "input_mapping": {}}
                ],
                "confirmed": True,
            },
            "current_step_index": 0,
            "step_results": [],
            "messages": [],
            "outputs": {},
            "worker_input": {
                "task": "分析缺陷趋势",
                "messages": [],
                "output_key": "data_insight_report",
                "error": "no",
                "reflection_count": 0,
                "max_reflections": 0,
                "result": "",
            },
        }
        original_graph = data_analyst_graph
        try:
            import test_agents.agents.data_analyst as da_module

            da_module.data_analyst_graph = None
            try:
                data_analyst_wrapper(state)
                assert False, "Expected RuntimeError"
            except RuntimeError as e:
                assert "data_analyst_graph not initialized" in str(e)
        finally:
            da_module.data_analyst_graph = original_graph

    def test_successful_invocation(self):
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "result": "## 缺陷趋势分析\n本月缺陷数下降 20%",
            "messages": [],
            "error": "no",
        }
        state: SupervisorState = {
            "user_request": "分析缺陷趋势",
            "plan": {
                "intent": "数据分析",
                "steps": [
                    {"step_id": 1, "agent": "data_analyst", "input_mapping": {}}
                ],
                "confirmed": True,
            },
            "current_step_index": 0,
            "step_results": [],
            "messages": [],
            "outputs": {},
            "worker_input": {
                "task": "分析缺陷趋势",
                "messages": [],
                "output_key": "data_insight_report",
                "error": "no",
                "reflection_count": 0,
                "max_reflections": 0,
                "result": "",
            },
        }
        with patch("test_agents.agents.data_analyst.data_analyst_graph", mock_graph):
            result = data_analyst_wrapper(state)
        assert "outputs" in result
        assert "data_insight_report" in result["outputs"]
        assert "缺陷趋势分析" in result["outputs"]["data_insight_report"]
        assert result["current_step_index"] == 1
        assert result["step_results"][0]["agent"] == "data_analyst"
