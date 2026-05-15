"""业务知识查询工具"""

import json
import os
from typing import Dict, Any


class BusinessKnowledgeTool:
    """根据模块名查询相关业务知识"""

    def __init__(self, knowledge_dir: str = ""):
        self.knowledge_dir = knowledge_dir or os.path.join(os.path.dirname(__file__), "..", "knowledge")
        self.name = "business_knowledge"
        self.description = "查询模块相关的业务知识"

    def run(self, parameters: Dict[str, Any]) -> str:
        """查询业务知识"""
        module_name = parameters.get("module_name", "")

        if not module_name:
            return ""

        # 尝试从本地 JSON 知识库加载
        knowledge_file = os.path.join(self.knowledge_dir, f"{module_name}.json")
        if os.path.exists(knowledge_file):
            try:
                with open(knowledge_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("description", "")
            except Exception:
                pass

        # 返回空字符串，不阻塞流程
        return ""

    def get_parameters(self) -> list[dict]:
        return [
            {"name": "module_name", "type": "string", "description": "模块名称", "required": True},
        ]
