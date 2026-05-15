"""测试用例解析工具"""

import json
from typing import Dict, Any


class TestCaseParserTool:
    """统一解析单条和批量用例输入"""

    def __init__(self):
        self.name = "test_case_parser"
        self.description = "解析测试用例输入，统一为结构化列表"

    def run(self, parameters: Dict[str, Any]) -> list[dict]:
        """解析用例输入"""
        input_data = parameters.get("input_data", "")
        format_type = parameters.get("format", "json")

        if not input_data:
            return []

        if format_type == "json":
            return self._parse_json(input_data)
        elif format_type == "text":
            return self._parse_text(input_data)
        else:
            raise ValueError(f"不支持的格式: {format_type}")

    def _parse_json(self, data: str) -> list[dict]:
        """解析 JSON 格式"""
        try:
            parsed = json.loads(data)
            if isinstance(parsed, list):
                return [self._normalize_case(item) for item in parsed]
            elif isinstance(parsed, dict):
                return [self._normalize_case(parsed)]
            else:
                raise ValueError("JSON 必须是对象或数组")
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败: {e}")

    def _parse_text(self, data: str) -> list[dict]:
        """解析纯文本格式（简单分隔）"""
        lines = [line.strip() for line in data.split("\n") if line.strip()]
        return [{"case_id": f"TC{i+1:03d}", "title": line} for i, line in enumerate(lines)]

    def _normalize_case(self, item: dict) -> dict:
        """标准化用例格式"""
        return {
            "case_id": item.get("case_id", ""),
            "title": item.get("title", ""),
            "steps": item.get("steps", ""),
            "expected_result": item.get("expected_result", ""),
        }

    def get_parameters(self) -> list[dict]:
        return [
            {"name": "input_data", "type": "string", "description": "原始输入数据", "required": True},
            {"name": "format", "type": "string", "description": "输入格式: json/text", "required": False},
        ]
