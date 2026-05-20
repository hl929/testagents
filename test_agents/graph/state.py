"""State definitions for Test Agents v3 - Plan-and-Solve + Reflection"""

import operator
import re
from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import AnyMessage, add_messages
from pydantic import BaseModel, Field, field_validator


class PlanStep(BaseModel):
    step_id: int = Field(description="步骤序号，从 1 开始")
    agent: str = Field(description="执行 agent: code_analyzer / case_reviewer")
    description: str = Field(description="步骤描述")
    input_mapping: dict[str, str] = Field(default_factory=dict, description="agent入参 → state字段引用或常量")
    output_key: str = Field(default="", description="结果写入 outputs 的 key，空则按 agent 类型默认")


class ExecutionPlan(BaseModel):
    intent: str = Field(description="用户意图摘要")
    steps: list[PlanStep] = Field(default_factory=list, description="有序步骤列表")
    confirmed: bool = Field(default=False, description="用户是否确认")


class StepResult(BaseModel):
    step_id: int = Field(description="步骤序号")
    agent: str = Field(description="执行 agent")
    status: str = Field(description="success / failed")
    output_key: str = Field(description="结果写入主图 state 的哪个字段")
    error: str = Field(default="", description="错误信息")


class AnalysisTarget(BaseModel):
    module_name: str = Field(description="模块名称")
    source_commit: str = Field(description="源 commit SHA")
    target_commit: str = Field(description="目标 commit SHA")
    commit_msg: str = Field(default="", description="commit message")

    @field_validator("source_commit", "target_commit")
    @classmethod
    def validate_commit_sha(cls, value: str) -> str:
        if not value:
            return value
        if not re.match(r"^[a-f0-9]{7,40}$", value, re.IGNORECASE):
            raise ValueError(f"Invalid commit SHA: {value}. Must be 7-40 hex characters.")
        return value.lower()

    @field_validator("module_name")
    @classmethod
    def validate_module_name(cls, value: str) -> str:
        if not value:
            return value
        if ".." in value or value.startswith("/"):
            raise ValueError(f"Invalid module name: {value}")
        return value


class SupervisorState(TypedDict, total=False):
    user_request: str
    targets: list[dict]
    test_cases: list[dict]
    business_knowledge: str
    plan: Optional[dict]
    current_step_index: int
    step_results: Annotated[list, operator.add]
    needs_replan: bool
    reflection_feedback: Optional[str]
    max_plan_iterations: int
    plan_iterations: int
    confirm_retry_count: int
    max_confirm_retries: int
    outputs: Annotated[dict, operator.or_]
    final_answer: Optional[str]
    messages: Annotated[list[AnyMessage], add_messages]
    intent_classification: str
    intent_reason: str


class WorkerState(TypedDict, total=False):
    task: str
    messages: Annotated[list[AnyMessage], add_messages]
    error: str
    reflection_count: int
    max_reflections: int
    result: str
    output_key: str
