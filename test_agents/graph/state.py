"""GraphState 定义 - 使用 Pydantic 进行严格验证"""

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TestAgentState(BaseModel):
    """测试智能体群的状态定义"""

    # 用户输入
    module_name: str = Field(description="待分析的模块名称")
    source_commit: str = Field(description="源 commit ID")
    target_commit: str = Field(description="目标 commit ID")
    commit_msg: str = Field(default="", description="commit message")
    test_cases: list[dict] = Field(default_factory=list, description="待评审的测试用例")
    business_knowledge: str = Field(default="", description="业务背景知识")

    # 中间产物
    code_change_report: str = Field(default="", description="代码分析结果")
    review_results: list[dict] = Field(default_factory=list, description="用例评审结果")

    # 控制流
    next_step: str = Field(default="", description="Supervisor 决策")
    messages: list[dict] = Field(default_factory=list, description="对话历史")

    # 错误信息
    error: str = Field(default="", description="错误信息")

    @field_validator("source_commit", "target_commit")
    @classmethod
    def validate_commit_sha(cls, value: str) -> str:
        """验证 commit SHA 格式，防止命令注入"""
        if not value:
            return value
        if not re.match(r"^[a-f0-9]{7,40}$", value, re.IGNORECASE):
            raise ValueError(f"Invalid commit SHA: {value}. Must be 7-40 hex characters.")
        return value.lower()

    @field_validator("module_name")
    @classmethod
    def validate_module_name(cls, value: str) -> str:
        """验证模块名，防止路径遍历"""
        if not value:
            return value
        if ".." in value or value.startswith("/"):
            raise ValueError(f"Invalid module name: {value}")
        return value
