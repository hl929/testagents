"""工具基类与自动注册表"""

from langchain_core.tools import BaseTool, render_text_description


class ToolRegistry:
    """工具注册表 - 自动收集所有 TestAgentTool 子类"""

    _tools: dict[str, BaseTool] = {}
    _tool_classes: dict[str, type] = {}

    @classmethod
    def register(cls, tool: BaseTool):
        cls._tools[tool.name] = tool

    @classmethod
    def _ensure_instantiated(cls):
        """将所有已注册的类定义懒实例化"""
        for name, tool_cls in list(cls._tool_classes.items()):
            if name not in cls._tools:
                cls._tools[name] = tool_cls()

    @classmethod
    def get_all(cls) -> list[BaseTool]:
        cls._ensure_instantiated()
        return list(cls._tools.values())

    @classmethod
    def get_by_name(cls, name: str) -> BaseTool | None:
        cls._ensure_instantiated()
        return cls._tools.get(name)

    @classmethod
    def get_tools_by_names(cls, names: list[str]) -> list[BaseTool]:
        cls._ensure_instantiated()
        return [cls._tools[n] for n in names if n in cls._tools]

    @classmethod
    def render_all(cls) -> str:
        """渲染所有工具的名称和描述，供 Planner prompt 使用"""
        return render_text_description(cls.get_all())


class TestAgentTool(BaseTool):
    """项目工具基类，子类定义时自动注册类到 ToolRegistry，使用时懒实例化"""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            ToolRegistry._tool_classes[getattr(cls, "name", cls.__name__)] = cls

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        ToolRegistry.register(self)
