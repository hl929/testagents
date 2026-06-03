"""Schema 描述加载工具"""

import os
import re

from pydantic import BaseModel, Field

from test_agents.tools.base import TestAgentTool
from test_agents.config import config


class SchemaDescriptionTool(TestAgentTool):
    name: str = "describe_schema"
    description: str = (
        "返回本地 Markdown 文件中的数据库表结构描述。"
        "table_name 为表名，留空则返回可用数据表概览。"
    )

    class InputSchema(BaseModel):
        table_name: str = Field(default="", description="表名，留空返回概览")

    args_schema: type = InputSchema

    def _run(self, table_name: str = "") -> str:
        schema_dir = config.SCHEMA_DIR

        if not os.path.isdir(schema_dir):
            return f"Schema 描述目录不存在: {schema_dir}"

        md_files = sorted(
            [f for f in os.listdir(schema_dir) if f.endswith(".md")]
        )

        if not md_files:
            return "暂无表结构描述文件。"

        table_names = [os.path.splitext(f)[0] for f in md_files]

        if not table_name:
            overview_lines = "\n".join(f"- {name}" for name in table_names)
            return (
                "# 可用数据表概览\n\n"
                f"{overview_lines}\n\n"
                "如需查看某张表的详细结构，请传入 table_name。"
            )

        # 防止路径遍历：只允许字母、数字、下划线
        if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
            return f"Invalid table name: {table_name}. Only alphanumeric and underscore allowed."

        target_file = os.path.join(schema_dir, f"{table_name}.md")
        if os.path.exists(target_file):
            with open(target_file, "r", encoding="utf-8") as f:
                return f.read()

        available_lines = "\n".join(f"- {name}" for name in table_names)
        return (
            f"未找到表 '{table_name}' 的描述文件。\n\n"
            f"可用表列表：\n{available_lines}"
        )
