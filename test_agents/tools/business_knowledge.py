"""业务知识查询工具"""

import json
import os

from pydantic import BaseModel, Field

from test_agents.tools.base import TestAgentTool
from test_agents.config import config


class BusinessKnowledgeTool(TestAgentTool):
    name: str = "query_business_knowledge"
    description: str = "查询模块相关的业务知识。module_name 为模块名称。"

    class InputSchema(BaseModel):
        module_name: str = Field(description="模块名称")

    args_schema: type = InputSchema

    def _run(self, module_name: str) -> str:
        if not module_name:
            return ""

        knowledge_dir = config.KNOWLEDGE_DIR or os.path.join(os.path.dirname(__file__), "..", "knowledge")
        knowledge_file = os.path.join(knowledge_dir, f"{module_name}.json")

        if os.path.exists(knowledge_file):
            try:
                with open(knowledge_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("description", "")
            except Exception:
                pass

        return ""
