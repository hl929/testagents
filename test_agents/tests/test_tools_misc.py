import json
import pytest
from test_agents.tools.test_case_parser import TestCaseParserTool
from test_agents.tools.business_knowledge import BusinessKnowledgeTool


def test_parse_json_array():
    tool = TestCaseParserTool()
    result = tool.invoke({"input_data": '[{"case_id": "TC001", "title": "test"}]', "input_format": "json"})
    parsed = json.loads(result)
    assert len(parsed) == 1
    assert parsed[0]["case_id"] == "TC001"


def test_parse_json_single():
    tool = TestCaseParserTool()
    result = tool.invoke({"input_data": '{"case_id": "TC001", "title": "test"}', "input_format": "json"})
    parsed = json.loads(result)
    assert len(parsed) == 1


def test_parse_text():
    tool = TestCaseParserTool()
    result = tool.invoke({"input_data": "Test case 1\nTest case 2", "input_format": "text"})
    parsed = json.loads(result)
    assert len(parsed) == 2
    assert parsed[0]["case_id"] == "TC001"


def test_parse_invalid_json():
    tool = TestCaseParserTool()
    result = tool.invoke({"input_data": "invalid json", "input_format": "json"})
    parsed = json.loads(result)
    assert "error" in parsed[0]


def test_business_knowledge_empty():
    tool = BusinessKnowledgeTool(knowledge_dir="/tmp/nonexistent")
    result = tool.invoke({"module_name": "order"})
    assert result == ""
