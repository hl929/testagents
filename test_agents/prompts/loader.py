"""Prompt 模板加载器"""

import os

_PROMPTS_DIR = os.path.dirname(__file__)


def load_prompt(name: str, **kwargs) -> str:
    """加载 prompt 模板并填充变量

    Args:
        name: 模板名称（不含 .md 后缀），如 "code_analyzer"
        **kwargs: 模板变量

    Returns:
        填充后的 prompt 字符串
    """
    path = os.path.join(_PROMPTS_DIR, f"{name}.md")
    with open(path, "r", encoding="utf-8") as f:
        template = f.read()
    class _Defaults(dict):
        def __missing__(self, key):
            return f"{{{key}}}"

    return template.format_map(_Defaults(kwargs))
