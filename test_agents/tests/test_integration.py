"""
Test Agents v3 Integration Tests

Tests for the complete supervisor pipeline (planner → confirm → dispatch → workers → reflect → synthesize)
using extensive mocking for LLM and worker subgraphs.
"""

import json

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

    # Test case: plan has data_analyst steps → data_analyst
    state = {
        "plan": {
            "steps": [
                {"agent": "data_analyst"}
            ]
        },
        "current_step_index": 0
    }
    assert route_from_dispatch(state) == "data_analyst"

    # Test case: plan has test_report_generator steps → test_report_generator
    state = {
        "plan": {
            "steps": [
                {"agent": "test_report_generator"}
            ]
        },
        "current_step_index": 0
    }
    assert route_from_dispatch(state) == "test_report_generator"

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


def test_resolve_input_multi_key():
    state = {
        "outputs": {
            "report_a": "Line A",
            "report_b": "Line B",
        }
    }
    result = _resolve_input("${outputs.report_a}\n${outputs.report_b}", state)
    assert result == "Line A\nLine B"


def test_resolve_input_mixed_text_and_refs():
    state = {
        "user_request": "hello",
        "outputs": {"x": "world"},
    }
    result = _resolve_input("req=${user_request}, out=${outputs.x}", state)
    assert result == "req=hello, out=world"


def test_full_pipeline_mocked():
    """Test the complete supervisor pipeline with mocks for all external dependencies"""
    # Mock intent classifier LLM response
    mock_classifier_response = MagicMock()
    mock_classifier_response.content = json.dumps({
        "classification": "relevant",
        "reason": "明确需求",
        "extracted": {
            "goal": "测试订单模块",
            "modules": ["订单"],
            "source_commit": "",
            "target_commit": "",
            "needs_code_analysis": True,
            "needs_case_review": True,
            "test_cases_provided": False,
            "missing_info": ["commit 范围"],
        },
    }, ensure_ascii=False)

    # Mock planner LLM response (now via llm.invoke, not with_structured_output)
    plan_json = json.dumps({
        "intent": "测试订单模块",
        "steps": [
            {"agent": "code_analyzer", "step_id": 1, "description": "分析订单模块代码变更", "input_mapping": {}, "output_key": "code_change_report"},
            {"agent": "case_reviewer", "step_id": 2, "description": "评审订单模块测试用例", "input_mapping": {}, "output_key": "review_results"}
        ],
        "confirmed": False,
    }, ensure_ascii=False)
    mock_planner_response = MagicMock()
    mock_planner_response.content = plan_json

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

        # classifier + planner + reflect + synthesize all use llm.invoke()
        mock_llm_instance.invoke.side_effect = [
            mock_classifier_response,
            mock_planner_response,
            mock_reflect_response,
            mock_synthesize_response,
        ]

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


def test_irrelevant_request_skips_planner():
    """End-to-end: irrelevant request should go intent_classifier → reply → END without planner"""
    mock_classifier_response = MagicMock()
    mock_classifier_response.content = '{"classification": "irrelevant", "reason": "打招呼"}'

    mock_reply_response = MagicMock()
    mock_reply_response.content = "您好！我是 Test Agents，专门用于分析代码变更..."

    with patch("test_agents.agents.supervisor.get_llm") as mock_supervisor_llm, \
         patch("test_agents.graph.builder.get_llm") as mock_builder_llm:
        mock_llm_instance = MagicMock()
        mock_supervisor_llm.return_value = mock_llm_instance
        mock_builder_llm.return_value = mock_llm_instance
        mock_llm_instance.invoke.side_effect = [
            mock_classifier_response,
            mock_reply_response,
        ]

        result = run_test_agents("hello")

    assert result.get("final_answer") == "您好！我是 Test Agents，专门用于分析代码变更..."
    assert not result.get("plan")


def test_ambiguous_request_gets_clarification():
    """End-to-end: ambiguous request should get a reply asking for more info"""
    mock_classifier_response = MagicMock()
    mock_classifier_response.content = '{"classification": "ambiguous", "reason": "信息不足"}'

    mock_reply_response = MagicMock()
    mock_reply_response.content = "请补充模块名和 commit 范围..."

    with patch("test_agents.agents.supervisor.get_llm") as mock_supervisor_llm, \
         patch("test_agents.graph.builder.get_llm") as mock_builder_llm:
        mock_llm_instance = MagicMock()
        mock_supervisor_llm.return_value = mock_llm_instance
        mock_builder_llm.return_value = mock_llm_instance
        mock_llm_instance.invoke.side_effect = [
            mock_classifier_response,
            mock_reply_response,
        ]

        result = run_test_agents("帮我看看测试")

    assert result.get("final_answer") == "请补充模块名和 commit 范围..."


def test_relevant_request_goes_full_pipeline():
    """End-to-end: relevant request should still go through full plan-and-solve flow"""
    mock_classifier_response = MagicMock()
    mock_classifier_response.content = json.dumps({
        "classification": "relevant",
        "reason": "明确需求",
        "extracted": {
            "goal": "分析订单模块代码变更",
            "modules": ["订单"],
            "source_commit": "",
            "target_commit": "",
            "needs_code_analysis": True,
            "needs_case_review": False,
            "test_cases_provided": False,
            "missing_info": ["commit 范围"],
        },
    }, ensure_ascii=False)

    plan_json = json.dumps({
        "intent": "测试订单模块",
        "steps": [
            {"agent": "code_analyzer", "step_id": 1, "description": "分析订单模块", "input_mapping": {}, "output_key": "code_change_report"},
        ],
        "confirmed": False,
    }, ensure_ascii=False)
    mock_planner_response = MagicMock()
    mock_planner_response.content = plan_json

    mock_reflect_response = MagicMock()
    mock_reflect_response.content = '{"assessment": "COMPLETE", "feedback": ""}'

    mock_synthesize_response = MagicMock()
    mock_synthesize_response.content = "分析完成"

    mock_code_analyzer_result = {
        "outputs": {"code_change_report": "代码变更分析完成"},
        "current_step_index": 1,
        "step_results": [{"step_id": 1, "agent": "code_analyzer", "status": "success", "output_key": "code_change_report"}],
    }

    with patch("test_agents.agents.supervisor.get_llm") as mock_supervisor_llm, \
         patch("test_agents.graph.builder.get_llm") as mock_builder_llm, \
         patch("test_agents.agents.supervisor.interrupt") as mock_interrupt, \
         patch("test_agents.graph.builder.code_analyzer_wrapper") as mock_code_analyzer_wrapper:

        mock_llm_instance = MagicMock()
        mock_supervisor_llm.return_value = mock_llm_instance
        mock_builder_llm.return_value = mock_llm_instance

        mock_llm_instance.invoke.side_effect = [
            mock_classifier_response,
            mock_planner_response,
            mock_reflect_response,
            mock_synthesize_response,
        ]

        mock_interrupt.return_value = {"confirmed": True}
        mock_code_analyzer_wrapper.return_value = mock_code_analyzer_result

        result = run_test_agents("请全面分析订单模块的代码变更并评审测试用例")

    assert result.get("outputs", {}).get("code_change_report") == "代码变更分析完成"
    assert result.get("final_answer") == "分析完成"


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
    assert mock_graph.invoke.call_args.args[0]["output_key"] == "code_change_report"


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
    assert mock_graph.invoke.call_args.args[0]["output_key"] == "review_results"


def test_save_experience_dedup(tmp_path):
    from test_agents.agents.supervisor import save_experience_node
    from unittest.mock import patch

    exp_file = tmp_path / "experience.md"
    with patch("test_agents.agents.supervisor.config.EXPERIENCE_FILE", str(exp_file)):
        state = {
            "user_request": "test",
            "plan": {"intent": "分析代码", "steps": [{"agent": "code_analyzer"}]},
            "step_results": [{"step_id": 1, "status": "success"}],
            "reflection_feedback": "",
        }
        # First save should write
        save_experience_node(state)
        assert "分析代码" in exp_file.read_text()

        # Second identical save should skip
        content_before = exp_file.read_text()
        save_experience_node(state)
        assert exp_file.read_text() == content_before


def test_direct_worker_invocation_data_analyst():
    """Test direct worker invocation for data analyst simple request"""
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "result": "## 缺陷趋势分析\n过去30天共发现缺陷 42 个，严重缺陷占比 15%...",
        "messages": [],
        "error": "no",
    }
    with patch("test_agents.main.WORKER_REGISTRY", {"data_analyst": mock_graph}):
        result = run_test_agents("分析过去30天支付模块的缺陷趋势")
    assert result["outputs"]["data_insight_report"] == "## 缺陷趋势分析\n过去30天共发现缺陷 42 个，严重缺陷占比 15%..."
    assert result["final_answer"] == "## 缺陷趋势分析\n过去30天共发现缺陷 42 个，严重缺陷占比 15%..."
    assert result["step_results"][0]["agent"] == "data_analyst"
    assert mock_graph.invoke.call_args.args[0]["output_key"] == "data_insight_report"


def test_full_pipeline_data_analyst():
    """Test the complete supervisor pipeline with data_analyst worker"""
    mock_classifier_response = MagicMock()
    mock_classifier_response.content = json.dumps({
        "classification": "relevant",
        "reason": "明确需求",
        "extracted": {
            "goal": "分析支付模块缺陷趋势",
            "modules": ["payment"],
            "source_commit": "",
            "target_commit": "",
            "needs_code_analysis": False,
            "needs_case_review": False,
            "needs_data_analysis": True,
            "test_cases_provided": False,
            "missing_info": [],
        },
    }, ensure_ascii=False)

    plan_json = json.dumps({
        "intent": "分析支付模块缺陷趋势",
        "steps": [
            {"agent": "data_analyst", "step_id": 1, "description": "查询过去30天支付模块的缺陷数据并分析趋势", "input_mapping": {"module_name": "payment", "time_range": "过去30天", "metrics": "缺陷数、严重缺陷占比"}, "output_key": "data_insight_report"}
        ],
        "confirmed": False,
    }, ensure_ascii=False)
    mock_planner_response = MagicMock()
    mock_planner_response.content = plan_json

    mock_reflect_response = MagicMock()
    mock_reflect_response.content = '{"assessment": "COMPLETE", "feedback": ""}'

    mock_synthesize_response = MagicMock()
    mock_synthesize_response.content = "支付模块过去30天缺陷趋势分析完成"

    mock_data_analyst_result = {
        "outputs": {"data_insight_report": "## 缺陷趋势\n过去30天共42个缺陷..."},
        "current_step_index": 1,
        "step_results": [
            {"step_id": 1, "agent": "data_analyst", "status": "success", "output_key": "data_insight_report"}
        ]
    }

    with patch("test_agents.agents.supervisor.get_llm") as mock_supervisor_llm, \
         patch("test_agents.graph.builder.get_llm") as mock_builder_llm, \
         patch("test_agents.agents.supervisor.interrupt") as mock_interrupt, \
         patch("test_agents.graph.builder.data_analyst_wrapper") as mock_data_analyst_wrapper:

        mock_llm_instance = MagicMock()
        mock_supervisor_llm.return_value = mock_llm_instance
        mock_builder_llm.return_value = mock_llm_instance

        mock_llm_instance.invoke.side_effect = [
            mock_classifier_response,
            mock_planner_response,
            mock_reflect_response,
            mock_synthesize_response,
        ]

        mock_interrupt.return_value = {"confirmed": True}
        mock_data_analyst_wrapper.return_value = mock_data_analyst_result

        result = run_test_agents("帮我分析一下过去30天支付模块的缺陷数据变化情况")

        assert "outputs" in result
        assert "data_insight_report" in result["outputs"]
        assert result["outputs"]["data_insight_report"] == "## 缺陷趋势\n过去30天共42个缺陷..."
        assert result.get("final_answer") == "支付模块过去30天缺陷趋势分析完成"
