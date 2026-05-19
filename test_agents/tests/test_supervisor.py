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
)
from test_agents.graph.state import SupervisorState, ExecutionPlan


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


class TestPlannerNode:
    def test_planner_generates_plan(self):
        mock_llm = MagicMock()
        plan_dict = ExecutionPlan(
            intent="分析代码变更",
            steps=[{"step_id": 1, "agent": "code_analyzer", "description": "分析代码", "input_mapping": {}}],
        ).model_dump()
        mock_llm.with_structured_output.return_value.invoke.return_value = plan_dict

        state: SupervisorState = {"user_request": "分析 payment 模块代码变更", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = planner_node(state)
        assert "plan" in result
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
        assert result == {}


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
