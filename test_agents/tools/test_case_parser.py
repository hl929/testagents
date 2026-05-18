"""测试用例解析工具"""

import json

from pydantic import BaseModel, Field

from test_agents.tools.base import TestAgentTool


class TestCaseParserTool(TestAgentTool):
    name: str = "parse_test_cases"
    description: str = "解析测试用例输入为结构化列表。input_data 为原始数据，input_format 为 json 或 text。"

    class InputSchema(BaseModel):
        input_data: str = Field(description="原始输入数据")
        input_format: str = Field(default="json", description="输入格式: json/text")

    args_schema: type = InputSchema

    def _run(self, input_data: str, input_format: str = "json") -> str:
        if not input_data:
            return "[]"

        if input_format == "json":
            result = self._parse_json(input_data)
        elif input_format == "text":
            result = self._parse_text(input_data)
        else:
            return f"错误: 不支持的格式 {input_format}"

        return json.dumps(result, ensure_ascii=False)

    def _parse_json(self, data: str) -> list[dict]:
        try:
            parsed = json.loads(data)
            if isinstance(parsed, list):
                return [self._normalize_case(item) for item in parsed]
            elif isinstance(parsed, dict):
                return [self._normalize_case(parsed)]
            else:
                return [{"error": "JSON 必须是对象或数组"}]
        except json.JSONDecodeError as e:
            return [{"error": f"JSON 解析失败: {e}"}]

    def _parse_text(self, data: str) -> list[dict]:
        lines = [line.strip() for line in data.split("\n") if line.strip()]
        return [{"case_id": f"TC{i+1:03d}", "title": line} for i, line in enumerate(lines)]

    def _normalize_case(self, item: dict) -> dict:
        return {
            "case_id": item.get("case_id", ""),
            "title": item.get("title", ""),
            "steps": item.get("steps", ""),
            "expected_result": item.get("expected_result", ""),
        }
