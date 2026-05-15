import pytest
from test_agents.tools.test_case_parser import TestCaseParserTool
from test_agents.tools.business_knowledge import BusinessKnowledgeTool


def test_parse_json_array():
    tool = TestCaseParserTool()
    result = tool.run({
        "input_data": '[{"case_id": "TC001", "title": "test"}]',
        "format": "json",
    })
    assert len(result) == 1
    assert result[0]["case_id"] == "TC001"


def test_parse_json_single():
    tool = TestCaseParserTool()
    result = tool.run({
        "input_data": '{"case_id": "TC001", "title": "test"}',
        "format": "json",
    })
    assert len(result) == 1


def test_parse_text():
    tool = TestCaseParserTool()
    result = tool.run({
        "input_data": "Test case 1\nTest case 2",
        "format": "text",
    })
    assert len(result) == 2
    assert result[0]["case_id"] == "TC001"


def test_parse_invalid_json():
    tool = TestCaseParserTool()
    with pytest.raises(ValueError, match="JSON 解析失败"):
        tool.run({"input_data": "invalid json", "format": "json"})


def test_business_knowledge_empty():
    tool = BusinessKnowledgeTool(knowledge_dir="/tmp/nonexistent")
    result = tool.run({"module_name": "order"})
    assert result == ""
