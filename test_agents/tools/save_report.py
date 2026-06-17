"""Save report tool — writes generated Markdown test reports to disk."""

import os
import re
from datetime import datetime

from pydantic import BaseModel, Field

from test_agents.tools.base import TestAgentTool


_BUSINESS_LINE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_MAX_BYTES_PER_FILE = 10 * 1024 * 1024  # 10MB safety cap


class SaveReportTool(TestAgentTool):
    name: str = "save_report"
    description: str = (
        "保存生成的 Markdown 测试报告到本地目录。"
        "输入: content(报告内容), business_line(业务线), template_name(模板名)。"
        "输出: 保存的文件绝对路径。"
    )

    class InputSchema(BaseModel):
        content: str = Field(description="Markdown 报告内容")
        business_line: str = Field(description="业务线标识，仅允许字母数字下划线连字符")
        template_name: str = Field(description="模板名，仅允许字母数字下划线连字符")

    args_schema: type = InputSchema

    def _run(self, content: str, business_line: str, template_name: str) -> str:
        if not content:
            return "错误: 报告内容不能为空"

        if not _BUSINESS_LINE_RE.match(business_line):
            return (
                f"错误: 业务线名称 '{business_line}' 包含非法字符。"
                "仅允许字母、数字、下划线和连字符。"
            )

        if not _BUSINESS_LINE_RE.match(template_name):
            return (
                f"错误: 模板名称 '{template_name}' 包含非法字符。"
                "仅允许字母、数字、下划线和连字符。"
            )

        if len(content.encode("utf-8")) > _MAX_BYTES_PER_FILE:
            return (
                f"错误: 报告内容过大（>{_MAX_BYTES_PER_FILE // 1024 // 1024}MB），"
                "无法保存。请减少内容或拆分报告。"
            )

        reports_dir = os.path.join("reports", business_line)

        # Resolve real path to prevent symlink attacks BEFORE creating directories
        try:
            real_dir = os.path.realpath(reports_dir)
            real_root = os.path.realpath("reports")
            if not real_dir.startswith(real_root + os.sep) and real_dir != real_root:
                return "错误: 保存路径超出允许范围"
        except OSError as e:
            return f"错误: 路径解析失败 — {e}"

        try:
            os.makedirs(reports_dir, exist_ok=True)
        except OSError as e:
            return f"错误: 无法创建目录 {reports_dir} — {e}"

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-{template_name}.md"
        filepath = os.path.join(reports_dir, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return f"错误: 无法写入文件 {filepath} — {e}"

        return f"报告已保存: {os.path.abspath(filepath)}"
