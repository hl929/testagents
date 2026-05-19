"""
Test Agents v3 Integration Tests

Tests for the complete supervisor pipeline (planner → confirm → dispatch → workers → reflect → synthesize)
using extensive mocking for LLM and worker subgraphs.
"""

import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage
from test_agents.main import run_test_agents
from test_agents.agents.supervisor import route_from_confirm, route_from_dispatch, route_from_reflect
from test_agents.agents.worker_base import _resolve_input


def test_route_from_confirm():
    """Test route_from_confirm function with different state shapes"""
    # Test case: confirmed = True → dispatch
    state = {
        "plan": {"confirmed": True}
    }
    assert route_from_confirm(state) == "dispatch"

    # Test case: confirmed = False → planner
    state = {
        "plan": {"confirmed": False},
        "confirm_retry_count": 0
    }
    assert route_from_confirm(state) == "planner"

    # Test case: retry limit exceeded → end
    state = {
        "plan": {"confirmed": False},
        "confirm_retry_count": 3
    }
    assert route_from_confirm(state) == "end"


def test_route_from_dispatch():
    """Test route_from_dispatch function with different state shapes"""
    # Test case: plan has code_analyzer steps → code_analyzer
    state = {
        "plan": {
            "steps": [
                {"agent": "code_analyzer"}
            ]
        },
        "current_step_index": 0
    }
    assert route_from_dispatch(state) == "code_analyzer"

    # Test case: plan has case_reviewer steps → case_reviewer
    state = {
        "plan": {
            "steps": [
                {"agent": "case_reviewer"}
            ]
        },
        "current_step_index": 0
    }
    assert route_from_dispatch(state) == "case_reviewer"

    # Test case: no plan steps left → reflect
    state = {
        "plan": {
            "steps": [
                {"agent": "code_analyzer"}
            ]
        },
        "current_step_index": 1
    }
    assert route_from_dispatch(state) == "reflect"

    # Test case: invalid agent type → reflect
    state = {
        "plan": {
            "steps": [
                {"agent": "invalid_agent"}
            ]
        },
        "current_step_index": 0
    }
    assert route_from_dispatch(state) == "reflect"


def test_route_from_reflect():
    """Test route_from_reflect function with different state shapes"""
    # Test case: needs_replan = True and under iteration limit → planner
    state = {
        "needs_replan": True,
        "plan_iterations": 0
    }
    assert route_from_reflect(state) == "planner"

    # Test case: needs_replan = True but over iteration limit → synthesize
    state = {
        "needs_replan": True,
        "plan_iterations": 1
    }
    assert route_from_reflect(state) == "synthesize"

    # Test case: no replan needed → synthesize
    state = {
        "needs_replan": False
    }
    assert route_from_reflect(state) == "synthesize"


def test_resolve_input():
    """Test _resolve_input function with state references and constants"""
    # Test case: constants are returned as-is
    assert _resolve_input("constant value", {}) == "constant value"

    # Test case: simple field references
    state = {
        "user_request": "test request",
        "source_commit": "abc123"
    }
    assert _resolve_input("${user_request}", state) == "test request"
    assert _resolve_input("${source_commit}", state) == "abc123"

    # Test case: non-string values are JSON serialized
    state = {
        "changes": ["file1.txt", "file2.py"]
    }
    assert _resolve_input("${changes}", state) == '["file1.txt", "file2.py"]'

    # Test case: missing fields → return empty string
    assert _resolve_input("${nonexistent_field}", {}) == ""

    # Test case: outputs reference
    state = {
        "outputs": {"code_change_report": "报告内容", "review_results": [{"id": "1"}]},
        "user_request": "test"
    }
    assert _resolve_input("${outputs.code_change_report}", state) == "报告内容"
    assert _resolve_input("${outputs.review_results}", state) == '[{"id": "1"}]'

    # Test case: missing outputs key returns empty string
    assert _resolve_input("${outputs.nonexistent}", state) == ""

    # Test case: outputs reference when outputs is missing
    assert _resolve_input("${outputs.code_change_report}", {}) == ""


def test_full_pipeline_mocked():
    """Test the complete supervisor pipeline with mocks for all external dependencies"""
    # Mock planner LLM response
    mock_planner_response = MagicMock()
    mock_planner_response.invoke.return_value = {
        "intent": "测试订单模块",
        "steps": [
            {"agent": "code_analyzer", "step_id": 1, "description": "分析订单模块代码变更"},
            {"agent": "case_reviewer", "step_id": 2, "description": "评审订单模块测试用例"}
        ]
    }

    # Mock reflect LLM response
    mock_reflect_response = MagicMock()
    mock_reflect_response.content = '{"assessment": "COMPLETE", "feedback": "All tests passed"}'

    # Mock synthesize LLM response
    mock_synthesize_response = MagicMock()
    mock_synthesize_response.content = "所有测试用例通过，订单模块功能正常"

    # Mock worker responses
    mock_code_analyzer_result = {
        "outputs": {"code_change_report": "代码变更分析完成"},
        "current_step_index": 1,
        "step_results": [
            {"step_id": 1, "agent": "code_analyzer", "status": "success", "output_key": "code_change_report"}
        ]
    }
    mock_case_reviewer_result = {
        "outputs": {"review_results": [{"case_id": "TC001", "verdict": "pass", "score": 90}]},
        "current_step_index": 2,
        "step_results": [
            {"step_id": 2, "agent": "case_reviewer", "status": "success", "output_key": "review_results"}
        ]
    }

    with patch("test_agents.agents.supervisor.get_llm") as mock_supervisor_llm, \
         patch("test_agents.graph.builder.get_llm") as mock_builder_llm, \
         patch("test_agents.agents.supervisor.interrupt") as mock_interrupt, \
         patch("test_agents.graph.builder.code_analyzer_wrapper") as mock_code_analyzer_wrapper, \
         patch("test_agents.graph.builder.case_reviewer_wrapper") as mock_case_reviewer_wrapper:

        # Configure supervisor LLM mocks
        mock_llm_instance = MagicMock()
        mock_supervisor_llm.return_value = mock_llm_instance
        mock_builder_llm.return_value = mock_llm_instance

        # Configure LLM for planning (with structured output)
        mock_llm_instance.with_structured_output.return_value = mock_planner_response

        # Configure LLM for reflection and synthesis (without structured output)
        mock_llm_instance.invoke.side_effect = [mock_reflect_response, mock_synthesize_response]

        # Mock LLM with tools binding (used for workers)
        mock_llm_with_tools = MagicMock()
        mock_llm_instance.bind_tools.return_value = mock_llm_with_tools

        # Configure interrupt to skip user confirmation
        mock_interrupt.return_value = {"confirmed": True}

        # Configure worker wrappers
        mock_code_analyzer_wrapper.return_value = mock_code_analyzer_result
        mock_case_reviewer_wrapper.return_value = mock_case_reviewer_result

        # Run test pipeline
        result = run_test_agents("测试订单模块")

        # Verify pipeline completed
        assert "outputs" in result
        assert "code_change_report" in result["outputs"]
        assert "review_results" in result["outputs"]
        assert "final_answer" in result




def test_direct_worker_invocation_code_analyzer():
    """Test direct worker invocation for code analyzer simple request"""
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "result": "## 变更概述\n新增订单功能",
        "messages": [],
        "error": "no",
    }
    with patch("test_agents.main.WORKER_REGISTRY", {"code_analyzer": mock_graph}):
        result = run_test_agents("分析订单模块代码变更")
    assert result["outputs"]["code_change_report"] == "## 变更概述\n新增订单功能"
    assert result["final_answer"] == "## 变更概述\n新增订单功能"
    assert result["step_results"][0]["agent"] == "code_analyzer"


def test_direct_worker_invocation_case_reviewer():
    """Test direct worker invocation for case reviewer simple request"""
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "result": '[{"case_id": "TC001", "verdict": "pass"}]',
        "messages": [],
        "error": "no",
    }
    with patch("test_agents.main.WORKER_REGISTRY", {"case_reviewer": mock_graph}):
        result = run_test_agents("评审测试用例")
    assert result["outputs"]["review_results"] == '[{"case_id": "TC001", "verdict": "pass"}]'
    assert result["step_results"][0]["agent"] == "case_reviewer"
