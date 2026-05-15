import pytest
from unittest.mock import MagicMock, patch
from langchain_core.tools import BaseTool, tool

from test_agents.agents.worker_base import worker_route, build_worker_graph
from test_agents.graph.state import WorkerState


class MockTool(BaseTool):
    name: str = "test_tool"
    description: str = "A test tool"

    def _run(self, *args, **kwargs):
        return "test result"


@tool
def mock_function_tool():
    """A test function tool."""
    return "test result"


class TestWorkerRoute:
    def test_error_no_returns_end(self):
        state: WorkerState = {"error": "no", "reflection_count": 0, "max_reflections": 1}
        assert worker_route(state) == "__end__"

    def test_error_yes_under_limit_returns_agent(self):
        state: WorkerState = {"error": "yes", "reflection_count": 0, "max_reflections": 2}
        assert worker_route(state) == "agent"

    def test_error_yes_at_limit_returns_end(self):
        state: WorkerState = {"error": "yes", "reflection_count": 2, "max_reflections": 2}
        assert worker_route(state) == "__end__"

    def test_error_yes_over_limit_returns_end(self):
        state: WorkerState = {"error": "yes", "reflection_count": 3, "max_reflections": 2}
        assert worker_route(state) == "__end__"

    def test_max_reflections_zero_always_end(self):
        state: WorkerState = {"error": "yes", "reflection_count": 0, "max_reflections": 0}
        assert worker_route(state) == "__end__"


class TestBuildWorkerGraph:
    def test_builds_graph_with_tools(self):
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        mock_tool = MockTool()

        graph = build_worker_graph([mock_tool], mock_llm, mock_llm_with_tools)
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        mock_tool = MockTool()

        graph = build_worker_graph([mock_tool], mock_llm, mock_llm_with_tools)
        node_names = set(graph.get_graph().nodes.keys())
        assert "agent" in node_names
        assert "tools" in node_names
        assert "reflect" in node_names
