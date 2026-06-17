"""Tests for test_report_generator worker and save_report tool."""

import json
import os
from unittest.mock import MagicMock, patch, mock_open

import pytest

from test_agents.agents.test_report_generator import (
    report_generator_wrapper,
    _preprocess_xlsx,
    _resolve_template_path,
    _build_data_context,
    _build_template_context,
)
from test_agents.tools.save_report import SaveReportTool


class TestPreprocessXlsx:
    def test_preprocess_small_xlsx(self, tmp_path):
        pd = pytest.importorskip("pandas")
        pytest.importorskip("openpyxl")

        file_path = tmp_path / "test.xlsx"
        df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        df.to_excel(file_path, index=False)

        result = _preprocess_xlsx(str(file_path))
        assert result is not None
        assert "1" in result
        assert "2" in result

    def test_preprocess_large_xlsx_returns_none(self, tmp_path):
        pd = pytest.importorskip("pandas")
        pytest.importorskip("openpyxl")

        file_path = tmp_path / "large.xlsx"
        # Create a file that exceeds cell cap when read
        df = pd.DataFrame({f"col_{i}": list(range(1000)) for i in range(120)})
        df.to_excel(file_path, index=False)

        result = _preprocess_xlsx(str(file_path))
        assert result is None

    def test_preprocess_pandas_not_installed(self, tmp_path):
        with patch.dict("sys.modules", {"pandas": None}):
            result = _preprocess_xlsx(str(tmp_path / "foo.xlsx"))
            assert result is None


class TestResolveTemplatePath:
    def test_resolve_template_path(self):
        assert _resolve_template_path("order", "summary") == os.path.join("templates", "order", "summary.md")


class TestBuildDataContext:
    def test_empty_path(self):
        assert _build_data_context("") == "(未提供)"

    def test_missing_file(self):
        assert "文件不存在" in _build_data_context("/nonexistent/file.txt")

    def test_small_text_file(self, tmp_path):
        file_path = tmp_path / "data.txt"
        file_path.write_text("hello world", encoding="utf-8")
        result = _build_data_context(str(file_path))
        assert "hello world" in result

    def test_xlsx_file_preprocess(self, tmp_path):
        pd = pytest.importorskip("pandas")
        pytest.importorskip("openpyxl")

        file_path = tmp_path / "data.xlsx"
        df = pd.DataFrame({"A": [1]})
        df.to_excel(file_path, index=False)

        result = _build_data_context(str(file_path))
        assert "已预处理为表格" in result

    def test_large_file_fallback(self, tmp_path):
        file_path = tmp_path / "big.txt"
        file_path.write_bytes(b"x" * (100 * 1024 + 1))
        result = _build_data_context(str(file_path))
        assert "文件较大" in result


class TestBuildTemplateContext:
    def test_missing_business_line_or_template(self):
        block, err = _build_template_context("", "summary")
        assert err == "缺少业务线或模板名"

    def test_template_not_found(self):
        block, err = _build_template_context("nonexistent", "nonexistent")
        assert err is not None
        assert "模板不存在" in err

    def test_template_found(self, tmp_path, monkeypatch):
        template_dir = tmp_path / "templates" / "order"
        template_dir.mkdir(parents=True)
        template_file = template_dir / "summary.md"
        template_file.write_text("# Report", encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        block, err = _build_template_context("order", "summary")
        assert err is None
        assert "# Report" in block


class TestSaveReportTool:
    def test_success(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = SaveReportTool()
        result = tool._run(content="# Report", business_line="order", template_name="summary")
        assert "报告已保存" in result
        assert os.path.isfile(os.path.join("reports", "order", os.listdir(os.path.join("reports", "order"))[0]))

    def test_empty_content(self):
        tool = SaveReportTool()
        result = tool._run(content="", business_line="order", template_name="summary")
        assert "不能为空" in result

    def test_invalid_business_line(self):
        tool = SaveReportTool()
        result = tool._run(content="# Report", business_line="order/123", template_name="summary")
        assert "非法字符" in result

    def test_invalid_template_name(self):
        tool = SaveReportTool()
        result = tool._run(content="# Report", business_line="order", template_name="summary..")
        assert "非法字符" in result

    def test_oversized_content(self):
        tool = SaveReportTool()
        huge = "x" * (10 * 1024 * 1024 + 1)
        result = tool._run(content=huge, business_line="order", template_name="summary")
        assert "过大" in result

    def test_symlink_attack(self, tmp_path, monkeypatch):
        # Create a real reports dir and a symlink inside it
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        evil_dir = tmp_path / "evil"
        evil_dir.mkdir()
        symlink = reports_dir / "evil_link"
        symlink.symlink_to(evil_dir)

        monkeypatch.chdir(tmp_path)
        tool = SaveReportTool()
        # os.path.realpath on reports/evil_link resolves to tmp_path/evil,
        # which does NOT start with tmp_path/reports/ — caught by the check
        result = tool._run(content="# Report", business_line="evil_link", template_name="summary")
        # Because the tool uses os.path.join("reports", business_line) and then checks realpath,
        # the symlink attack should be caught.
        # However, on some systems the mkdir may follow symlink. Let's verify.
        if "超出允许范围" in result:
            pass
        else:
            # If mkdir followed symlink, file may have been written to evil_dir.
            # Check that it did NOT land there (security expectation).
            assert not list(evil_dir.glob("*.md"))


class TestTestReportGeneratorWrapper:
    def test_template_missing_returns_error(self):
        mock_graph = MagicMock()
        with patch("test_agents.agents.test_report_generator.test_report_generator_graph", mock_graph):
            state = {
                "worker_input": {"output_key": "test_report"},
                "plan": {"steps": [{"step_id": 1, "agent": "test_report_generator", "input_mapping": {"business_line": "nonexistent", "template_name": "nonexistent"}}]},
                "current_step_index": 0,
                "outputs": {},
            }
            result = report_generator_wrapper(state)
            assert result["step_results"][0]["status"] == "failed"
            assert "模板不存在" in result["outputs"]["test_report"]
            # claude_cli should NOT be called when template is missing
            mock_graph.invoke.assert_not_called()

    def test_successful_invocation(self, tmp_path, monkeypatch):
        template_dir = tmp_path / "templates" / "order"
        template_dir.mkdir(parents=True)
        (template_dir / "summary.md").write_text("# Template", encoding="utf-8")
        data_file = tmp_path / "data.txt"
        data_file.write_text("test data", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "result": "# Generated Report",
            "messages": [],
            "error": "no",
        }

        with patch("test_agents.agents.test_report_generator.test_report_generator_graph", mock_graph):
            state = {
                "worker_input": {"output_key": "test_report", "task": "生成测试报告"},
                "plan": {"steps": [{"step_id": 1, "agent": "test_report_generator", "input_mapping": {"file_path": str(data_file), "business_line": "order", "template_name": "summary"}}]},
                "current_step_index": 0,
                "outputs": {},
            }
            result = report_generator_wrapper(state)
            assert result["step_results"][0]["status"] == "success"
            assert "# Generated Report" in result["outputs"]["test_report"]
            # Verify the enriched prompt was passed
            call_args = mock_graph.invoke.call_args[0][0]
            assert "order" in call_args["messages"][0].content
            assert "summary" in call_args["messages"][0].content

    def test_file_path_missing(self, tmp_path, monkeypatch):
        template_dir = tmp_path / "templates" / "order"
        template_dir.mkdir(parents=True)
        (template_dir / "summary.md").write_text("# Template", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "result": "# Generated Report",
            "messages": [],
            "error": "no",
        }

        with patch("test_agents.agents.test_report_generator.test_report_generator_graph", mock_graph):
            state = {
                "worker_input": {"output_key": "test_report", "task": "生成测试报告"},
                "plan": {"steps": [{"step_id": 1, "agent": "test_report_generator", "input_mapping": {"file_path": "", "business_line": "order", "template_name": "summary"}}]},
                "current_step_index": 0,
                "outputs": {},
            }
            result = report_generator_wrapper(state)
            assert result["step_results"][0]["status"] == "success"
            call_args = mock_graph.invoke.call_args[0][0]
            assert "(未提供)" in call_args["messages"][0].content
