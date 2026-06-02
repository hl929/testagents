import os

import pytest

from test_agents.tools.schema_loader import SchemaDescriptionTool
from test_agents.config import config


class TestSchemaDescriptionTool:
    def test_describe_specific_table(self, tmp_path, monkeypatch):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "defects.md").write_text("# defects schema", encoding="utf-8")
        (schema_dir / "coverage.md").write_text("# coverage schema", encoding="utf-8")

        monkeypatch.setattr(config, "SCHEMA_DIR", str(schema_dir))

        tool = SchemaDescriptionTool()
        result = tool._run(table_name="defects")

        assert result == "# defects schema"

    def test_describe_missing_table_returns_list(self, tmp_path, monkeypatch):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "defects.md").write_text("# defects", encoding="utf-8")
        (schema_dir / "coverage.md").write_text("# coverage", encoding="utf-8")

        monkeypatch.setattr(config, "SCHEMA_DIR", str(schema_dir))

        tool = SchemaDescriptionTool()
        result = tool._run(table_name="nonexistent")

        assert "未找到表 'nonexistent' 的描述文件" in result
        assert "defects" in result
        assert "coverage" in result

    def test_describe_all_tables(self, tmp_path, monkeypatch):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "defects.md").write_text("# defects", encoding="utf-8")
        (schema_dir / "coverage.md").write_text("# coverage", encoding="utf-8")

        monkeypatch.setattr(config, "SCHEMA_DIR", str(schema_dir))

        tool = SchemaDescriptionTool()
        result = tool._run(table_name="")

        assert "# 可用数据表概览" in result
        assert "defects" in result
        assert "coverage" in result
        assert "如需查看某张表的详细结构" in result

    def test_empty_schema_dir(self, tmp_path, monkeypatch):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        monkeypatch.setattr(config, "SCHEMA_DIR", str(schema_dir))

        tool = SchemaDescriptionTool()
        result = tool._run(table_name="")

        assert result == "暂无表结构描述文件。"

    def test_missing_schema_dir(self, tmp_path, monkeypatch):
        schema_dir = tmp_path / "nonexistent"

        monkeypatch.setattr(config, "SCHEMA_DIR", str(schema_dir))

        tool = SchemaDescriptionTool()
        result = tool._run(table_name="defects")

        assert f"Schema 描述目录不存在: {schema_dir}" in result
