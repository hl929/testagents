"""LangChain tool adapters - wraps existing tools as @tool functions"""

import json

from langchain_core.tools import tool

from test_agents.tools.claude_cli import ClaudeCliTool
from test_agents.tools.test_case_parser import TestCaseParserTool
from test_agents.tools.business_knowledge import BusinessKnowledgeTool


@tool
def claude_cli(prompt: str, model: str = "") -> str:
    """调用 Claude CLI 执行分析任务。prompt 为完整提示词，model 为可选模型名。"""
    return ClaudeCliTool().run({"prompt": prompt, "model": model})


@tool
def parse_test_cases(input_data: str, input_format: str = "json") -> str:
    """解析测试用例输入为结构化列表。input_data 为原始数据，input_format 为 json 或 text。"""
    result = TestCaseParserTool().run({"input_data": input_data, "format": input_format})
    return json.dumps(result, ensure_ascii=False)


@tool
def query_business_knowledge(module_name: str) -> str:
    """查询模块相关的业务知识。module_name 为模块名称。"""
    return BusinessKnowledgeTool().run({"module_name": module_name})
