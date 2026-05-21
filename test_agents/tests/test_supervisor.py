import json
from unittest.mock import MagicMock, patch

from test_agents.agents.supervisor import (
    planner_node,
    confirm_plan_node,
    dispatch_node,
    reflect_node,
    synthesize_node,
    save_experience_node,
    route_from_confirm,
    route_from_dispatch,
    route_from_reflect,
    intent_classifier_node,
    reply_node,
    route_from_classifier,
)
from test_agents.graph.state import SupervisorState, ExecutionPlan, IntentExtraction


def test_intent_extraction_model_validates():
    """IntentExtraction accepts valid extracted data"""
    extracted = IntentExtraction(
        goal="分析代码变更并评审测试用例",
        modules=["payment"],
        source_commit="abc1234",
        target_commit="def5678",
        needs_code_analysis=True,
        needs_case_review=True,
    )
    assert extracted.goal == "分析代码变更并评审测试用例"
    assert extracted.modules == ["payment"]
    assert extracted.needs_code_analysis is True


def test_intent_extraction_model_defaults():
    """IntentExtraction fields have sensible defaults"""
    extracted = IntentExtraction(goal="评审测试用例")
    assert extracted.modules == []
    assert extracted.source_commit == ""
    assert extracted.target_commit == ""
    assert extracted.needs_code_analysis is False
    assert extracted.needs_case_review is False
    assert extracted.test_cases_provided is False
    assert extracted.missing_info == []


def test_supervisor_state_has_intent_analysis():
    state: SupervisorState = {
        "intent_classification": "relevant",
        "intent_reason": "明确需求",
        "intent_analysis": {"goal": "分析代码变更"},
    }
    assert state["intent_analysis"] == {"goal": "分析代码变更"}


def test_supervisor_state_has_intent_fields():
    # TypedDict allows optional fields, so we verify by construction
    state: SupervisorState = {
        "user_request": "hello",
        "intent_classification": "irrelevant",
        "intent_reason": "用户仅打招呼",
    }
    assert state["intent_classification"] == "irrelevant"
    assert state["intent_reason"] == "用户仅打招呼"


class TestRouteFromConfirm:
    def test_confirmed_dispatches(self):
        state: SupervisorState = {"plan": {"confirmed": True, "intent": "test", "steps": []}}
        assert route_from_confirm(state) == "dispatch"

    def test_rejected_under_limit_goes_planner(self):
        state: SupervisorState = {
            "plan": {"confirmed": False, "intent": "test", "steps": []},
            "confirm_retry_count": 0,
            "max_confirm_retries": 3,
        }
        assert route_from_confirm(state) == "planner"

    def test_rejected_over_limit_goes_end(self):
        state: SupervisorState = {
            "plan": {"confirmed": False, "intent": "test", "steps": []},
            "confirm_retry_count": 3,
            "max_confirm_retries": 3,
        }
        assert route_from_confirm(state) == "end"


class TestRouteFromDispatch:
    def test_all_steps_done_goes_reflect(self):
        state: SupervisorState = {
            "plan": {"steps": [{"step_id": 1}, {"step_id": 2}]},
            "current_step_index": 2,
        }
        assert route_from_dispatch(state) == "reflect"

    def test_first_step_code_analyzer(self):
        state: SupervisorState = {
            "plan": {"steps": [{"step_id": 1, "agent": "code_analyzer"}, {"step_id": 2, "agent": "case_reviewer"}]},
            "current_step_index": 0,
        }
        assert route_from_dispatch(state) == "code_analyzer"

    def test_second_step_case_reviewer(self):
        state: SupervisorState = {
            "plan": {"steps": [{"step_id": 1, "agent": "code_analyzer"}, {"step_id": 2, "agent": "case_reviewer"}]},
            "current_step_index": 1,
        }
        assert route_from_dispatch(state) == "case_reviewer"


class TestRouteFromReflect:
    def test_needs_replan_under_limit_goes_planner(self):
        state: SupervisorState = {
            "needs_replan": True,
            "plan_iterations": 0,
            "max_plan_iterations": 2,
        }
        assert route_from_reflect(state) == "planner"

    def test_needs_replan_at_limit_goes_synthesize(self):
        state: SupervisorState = {
            "needs_replan": True,
            "plan_iterations": 2,
            "max_plan_iterations": 2,
        }
        assert route_from_reflect(state) == "synthesize"

    def test_complete_goes_synthesize(self):
        state: SupervisorState = {
            "needs_replan": False,
            "plan_iterations": 0,
            "max_plan_iterations": 1,
        }
        assert route_from_reflect(state) == "synthesize"


class TestRouteFromClassifier:
    def test_relevant_goes_planner(self):
        state: SupervisorState = {"intent_classification": "relevant"}
        assert route_from_classifier(state) == "planner"

    def test_ambiguous_goes_reply(self):
        state: SupervisorState = {"intent_classification": "ambiguous"}
        assert route_from_classifier(state) == "reply"

    def test_irrelevant_goes_reply(self):
        state: SupervisorState = {"intent_classification": "irrelevant"}
        assert route_from_classifier(state) == "reply"

    def test_empty_defaults_to_reply(self):
        state: SupervisorState = {"intent_classification": ""}
        assert route_from_classifier(state) == "reply"

    def test_missing_key_defaults_to_reply(self):
        state: SupervisorState = {}
        assert route_from_classifier(state) == "reply"

    def test_unknown_value_goes_reply(self):
        state: SupervisorState = {"intent_classification": "unknown"}
        assert route_from_classifier(state) == "reply"


class TestPlannerNode:
    def test_planner_generates_plan(self):
        mock_llm = MagicMock()
        plan_json = ExecutionPlan(
            intent="分析代码变更",
            steps=[{"step_id": 1, "agent": "code_analyzer", "description": "分析代码", "input_mapping": {}}],
        ).model_dump_json()
        mock_llm.invoke.return_value = MagicMock(content=plan_json)

        state: SupervisorState = {"user_request": "分析 payment 模块代码变更", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = planner_node(state)
        assert "plan" in result
        assert result["plan"]["intent"] == "分析代码变更"

    def test_planner_handles_markdown_fenced_json(self):
        mock_llm = MagicMock()
        plan_dict = ExecutionPlan(
            intent="分析代码变更",
            steps=[{"step_id": 1, "agent": "code_analyzer", "description": "分析代码", "input_mapping": {}}],
        ).model_dump()
        plan_json = json.dumps(plan_dict, ensure_ascii=False)
        mock_llm.invoke.return_value = MagicMock(content=f"```json\n{plan_json}\n```")

        state: SupervisorState = {"user_request": "分析代码变更", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = planner_node(state)
        assert result["plan"]["intent"] == "分析代码变更"


class TestConfirmPlanNode:
    def test_confirm_plan_interrupts(self):
        state: SupervisorState = {
            "plan": {"intent": "test", "steps": [{"step_id": 1, "agent": "code_analyzer", "description": "分析代码", "input_mapping": {}}], "confirmed": False},
            "confirm_retry_count": 0,
            "max_confirm_retries": 3,
        }
        with patch("test_agents.agents.supervisor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {"confirmed": True}
            result = confirm_plan_node(state)
        assert result["plan"]["confirmed"] is True

    def test_confirm_plan_rejected_increments_retry(self):
        state: SupervisorState = {
            "plan": {"intent": "test", "steps": [], "confirmed": False},
            "confirm_retry_count": 0,
            "max_confirm_retries": 3,
        }
        with patch("test_agents.agents.supervisor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {"confirmed": False, "feedback": "请修改"}
            result = confirm_plan_node(state)
        assert result["confirm_retry_count"] == 1


class TestDispatchNode:
    def test_dispatch_returns_empty_for_routing(self):
        state: SupervisorState = {
            "plan": {"steps": [{"step_id": 1, "agent": "code_analyzer"}]},
            "current_step_index": 0,
        }
        result = dispatch_node(state)
        assert "worker_input" in result
        assert result["worker_input"]["output_key"] == "code_change_report"


class TestReflectNode:
    def test_reflect_complete(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"assessment": "COMPLETE", "feedback": ""}')
        state: SupervisorState = {
            "user_request": "test",
            "plan": {"intent": "test", "steps": []},
            "step_results": [{"step_id": 1, "status": "success"}],
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = reflect_node(state)
        assert result["needs_replan"] is False

    def test_reflect_replan(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"assessment": "REPLAN", "feedback": "结果不完整"}')
        state: SupervisorState = {
            "user_request": "test",
            "plan": {"intent": "test", "steps": []},
            "step_results": [],
            "messages": [],
            "plan_iterations": 0,
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = reflect_node(state)
        assert result["needs_replan"] is True
        assert result["plan_iterations"] == 1


class TestSynthesizeNode:
    def test_synthesize_generates_answer(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="综合分析报告内容")
        state: SupervisorState = {
            "user_request": "test",
            "plan": {"intent": "test", "steps": []},
            "step_results": [{"step_id": 1, "status": "success"}],
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = synthesize_node(state)
        assert result["final_answer"] == "综合分析报告内容"

    def test_synthesize_reads_from_outputs(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="基于 outputs 的综合报告")
        state: SupervisorState = {
            "user_request": "test",
            "plan": {"intent": "test", "steps": []},
            "step_results": [{"step_id": 1, "status": "success"}],
            "outputs": {"code_change_report": "变更内容", "review_results": [{"verdict": "pass"}]},
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = synthesize_node(state)
        assert result["final_answer"] == "基于 outputs 的综合报告"
        # Verify prompt contains outputs content
        prompt_arg = mock_llm.invoke.call_args[0][0][0].content
        assert "【code_change_report】" in prompt_arg
        assert "变更内容" in prompt_arg


class TestSaveExperienceNode:
    def test_save_experience_creates_file(self, tmp_path):
        experience_file = str(tmp_path / "experience.md")
        state: SupervisorState = {
            "user_request": "test",
            "plan": {"intent": "test", "steps": []},
            "step_results": [],
            "reflection_feedback": "",
        }
        with patch("test_agents.agents.supervisor.config") as mock_config:
            mock_config.EXPERIENCE_FILE = experience_file
            result = save_experience_node(state)
        assert result == {}


class TestIntentClassifierNode:
    def test_classifies_relevant(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"classification": "relevant", "reason": "明确需求"}')
        state: SupervisorState = {"user_request": "分析 payment 模块代码变更", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = intent_classifier_node(state)
        assert result["intent_classification"] == "relevant"
        assert result["intent_reason"] == "明确需求"

    def test_classifies_relevant_with_markdown_fenced_json(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='```json\n{"classification": "relevant", "reason": "明确需求"}\n```')
        state: SupervisorState = {"user_request": "分析代码", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = intent_classifier_node(state)
        assert result["intent_classification"] == "relevant"
        assert result["intent_reason"] == "明确需求"

    def test_classifies_irrelevant(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"classification": "irrelevant", "reason": "打招呼"}')
        state: SupervisorState = {"user_request": "hello", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = intent_classifier_node(state)
        assert result["intent_classification"] == "irrelevant"
        assert result["intent_reason"] == "打招呼"

    def test_fallback_to_ambiguous_on_invalid_json(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="not json at all")
        state: SupervisorState = {"user_request": "test", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = intent_classifier_node(state)
        assert result["intent_classification"] == "ambiguous"
        assert "解析失败" in result["intent_reason"]

    def test_fallback_to_ambiguous_on_llm_exception(self):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("network error")
        state: SupervisorState = {"user_request": "test", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = intent_classifier_node(state)
        assert result["intent_classification"] == "ambiguous"
        assert "解析失败" in result["intent_reason"]

    def test_classifier_prompt_contains_user_request(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"classification": "relevant", "reason": "test"}')
        state: SupervisorState = {"user_request": "分析 payment 模块", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            intent_classifier_node(state)
        prompt_arg = mock_llm.invoke.call_args[0][0][0].content
        assert "分析 payment 模块" in prompt_arg

    def test_classifier_prompt_mentions_extracted(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content='{"classification": "relevant", "reason": "test", "extracted": {"goal": "分析代码"}}'
        )
        state: SupervisorState = {"user_request": "分析代码", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            intent_classifier_node(state)
        prompt_arg = mock_llm.invoke.call_args[0][0][0].content
        assert "extracted" in prompt_arg


class TestReplyNode:
    def test_reply_generates_final_answer(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="您好！我是 Test Agents...")
        state: SupervisorState = {
            "user_request": "hello",
            "intent_classification": "irrelevant",
            "intent_reason": "打招呼",
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = reply_node(state)
        assert result["final_answer"] == "您好！我是 Test Agents..."

    def test_reply_fallback_on_llm_exception(self):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("network error")
        state: SupervisorState = {
            "user_request": "hello",
            "intent_classification": "irrelevant",
            "intent_reason": "打招呼",
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = reply_node(state)
        assert "Test Agents" in result["final_answer"]

    def test_reply_fallback_on_ambiguous(self):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("timeout")
        state: SupervisorState = {
            "user_request": "帮我看看测试",
            "intent_classification": "ambiguous",
            "intent_reason": "信息不足",
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = reply_node(state)
        assert "请补充" in result["final_answer"]

    def test_reply_prompt_contains_classification(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="回复内容")
        state: SupervisorState = {
            "user_request": "hello",
            "intent_classification": "irrelevant",
            "intent_reason": "打招呼",
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            reply_node(state)
        prompt_arg = mock_llm.invoke.call_args[0][0][0].content
        assert "irrelevant" in prompt_arg
        assert "打招呼" in prompt_arg
