import pytest
from test_agents.graph.state import (
    PlanStep, ExecutionPlan, StepResult, AnalysisTarget,
    SupervisorState, WorkerState,
)


class TestPlanStep:
    def test_create_plan_step(self):
        step = PlanStep(
            step_id=1,
            agent="code_analyzer",
            description="分析 payment 模块代码变更",
            input_mapping={"module_name": "payment", "source_commit": "abc1234", "target_commit": "def5678"},
        )
        assert step.step_id == 1
        assert step.agent == "code_analyzer"
        assert step.input_mapping["module_name"] == "payment"

    def test_input_mapping_default_empty(self):
        step = PlanStep(step_id=1, agent="code_analyzer", description="test")
        assert step.input_mapping == {}


class TestExecutionPlan:
    def test_create_plan(self):
        step = PlanStep(step_id=1, agent="code_analyzer", description="分析代码")
        plan = ExecutionPlan(intent="分析代码变更", steps=[step])
        assert plan.intent == "分析代码变更"
        assert len(plan.steps) == 1
        assert plan.confirmed is False

    def test_plan_serialization_roundtrip(self):
        step = PlanStep(step_id=1, agent="code_analyzer", description="分析代码",
                        input_mapping={"module_name": "payment"})
        plan = ExecutionPlan(intent="分析", steps=[step])
        d = plan.model_dump()
        assert d["steps"][0]["input_mapping"]["module_name"] == "payment"
        restored = ExecutionPlan.model_validate(d)
        assert restored.steps[0].input_mapping["module_name"] == "payment"

    def test_confirmed_default_false(self):
        plan = ExecutionPlan(intent="test", steps=[])
        assert plan.confirmed is False


class TestAnalysisTarget:
    def test_valid_target(self):
        target = AnalysisTarget(
            module_name="payment", source_commit="abc1234", target_commit="def5678"
        )
        assert target.module_name == "payment"
        assert target.source_commit == "abc1234"

    def test_invalid_commit_sha(self):
        with pytest.raises(ValueError, match="Invalid commit SHA"):
            AnalysisTarget(module_name="payment", source_commit="invalid!", target_commit="def5678")

    def test_path_traversal_module(self):
        with pytest.raises(ValueError, match="Invalid module name"):
            AnalysisTarget(module_name="../../etc", source_commit="abc1234", target_commit="def5678")

    def test_commit_sha_normalized_lowercase(self):
        target = AnalysisTarget(module_name="pay", source_commit="ABC1234", target_commit="DEF5678")
        assert target.source_commit == "abc1234"

    def test_default_commit_msg(self):
        target = AnalysisTarget(module_name="pay", source_commit="abc1234", target_commit="def5678")
        assert target.commit_msg == ""


class TestStepResult:
    def test_create_step_result(self):
        result = StepResult(step_id=1, agent="code_analyzer", status="success", output_key="code_change_report")
        assert result.status == "success"
        assert result.error == ""

    def test_failed_step_result(self):
        result = StepResult(step_id=1, agent="code_analyzer", status="failed", output_key="code_change_report", error="timeout")
        assert result.status == "failed"
        assert result.error == "timeout"


class TestWorkerState:
    def test_worker_state_is_dict(self):
        state: WorkerState = {
            "task": "分析代码",
            "messages": [],
            "error": "no",
            "reflection_count": 0,
            "max_reflections": 0,
            "result": "",
            "output_key": "code_change_report",
        }
        assert state["task"] == "分析代码"
        assert state["error"] == "no"
