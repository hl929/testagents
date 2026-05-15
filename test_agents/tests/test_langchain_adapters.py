import json
from unittest.mock import patch, MagicMock

from test_agents.tools.langchain_adapters import claude_cli, parse_test_cases, query_business_knowledge


def test_claude_cli_adapter_invocation():
    with patch("test_agents.tools.langchain_adapters.ClaudeCliTool") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.run.return_value = "analysis result"
        mock_cls.return_value = mock_instance
        result = claude_cli.invoke({"prompt": "test prompt"})
        assert result == "analysis result"
        mock_instance.run.assert_called_once_with({"prompt": "test prompt", "model": ""})


def test_parse_test_cases_adapter_json():
    result = parse_test_cases.invoke({"input_data": '[{"case_id": "TC001", "title": "test"}]', "input_format": "json"})
    parsed = json.loads(result)
    assert len(parsed) == 1
    assert parsed[0]["case_id"] == "TC001"


def test_parse_test_cases_adapter_text():
    result = parse_test_cases.invoke({"input_data": "Test case 1\nTest case 2", "input_format": "text"})
    parsed = json.loads(result)
    assert len(parsed) == 2
    assert parsed[0]["case_id"] == "TC001"


def test_query_business_knowledge_adapter():
    result = query_business_knowledge.invoke({"module_name": "nonexistent_module"})
    assert result == ""


def test_tools_are_langchain_tools():
    from langchain_core.tools import BaseTool
    assert isinstance(claude_cli, BaseTool)
    assert isinstance(parse_test_cases, BaseTool)
    assert isinstance(query_business_knowledge, BaseTool)
