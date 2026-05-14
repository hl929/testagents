# Tools 模块 - 工具系统说明

本目录包含 HelloAgents 框架的工具系统实现，为 Agent 提供各种能力支持。

## 📁 目录结构

```
tools/
├── __init__.py           # 模块入口，导出主要组件
├── base.py               # Tool 基类和基础定义
├── registry.py           # ToolRegistry 工具注册表
├── chain.py              # ToolChain 工具链支持
├── async_executor.py     # 异步工具执行器
├── builtin/              # 内置工具集合
│   ├── calculator.py     # 计算器工具
│   ├── search_tool.py    # 搜索工具
│   ├── memory_tool.py    # 记忆工具
│   ├── rag_tool.py       # RAG 工具
│   ├── note_tool.py      # 笔记工具
│   ├── terminal_tool.py  # 终端工具
│   ├── mcp_wrapper_tool.py  # MCP 协议工具
│   ├── protocol_tools.py # 协议工具集合
│   ├── bfcl_evaluation_tool.py  # BFCL 评估工具
│   ├── gaia_evaluation_tool.py  # GAIA 评估工具
│   ├── llm_judge_tool.py        # LLM Judge 工具
│   ├── win_rate_tool.py         # Win Rate 工具
│   └── rl_training_tool.py      # RL 训练工具
└── readme.md             # 本文档
```

## 🎯 核心组件

### 1. Tool 基类 (`base.py`)
定义了所有工具的基础接口：

```python
class Tool(ABC):
    def __init__(self, name: str, description: str, expandable: bool = False):
        self.name = name
        self.description = description
        self.expandable = expandable
    
    @abstractmethod
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行工具"""
        pass
    
    @abstractmethod
    def get_parameters(self) -> List[ToolParameter]:
        """获取工具参数定义"""
        pass
```

**核心特性：**
- 支持工具展开（expandable）：一个工具可以展开为多个子工具
- `@tool_action` 装饰器：自动从方法生成子工具
- `ToolParameter`：参数类型定义
- `to_openai_schema()`：自动转换为 OpenAI Function Calling 格式

### 2. ToolRegistry (`registry.py`)
管理工具的注册和执行：

```python
class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._functions: Dict[str, Dict[str, Any]] = {}
    
    def register_tool(self, tool: Tool, auto_expand: bool = True):
        """注册 Tool 对象"""
        
    def register_function(self, name: str, description: str, func: Callable[[str], str]):
        """直接注册函数作为工具"""
        
    def execute_tool(self, name: str, input_text: str) -> str:
        """执行工具"""
        
    def get_tools_description(self) -> str:
        """获取所有工具描述字符串"""
```

### 3. ToolChain (`chain.py`)
支持工具的链式调用：

```python
class ToolChain:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.steps: List[Dict[str, Any]] = []
    
    def add_step(self, tool_name: str, input_template: str, output_key: str = None):
        """添加工具执行步骤"""
    
    def execute(self, registry: ToolRegistry, input_data: str, context: Dict[str, Any] = None) -> str:
        """执行工具链"""
```

### 4. AsyncToolExecutor (`async_executor.py`)
支持工具的异步并行执行：

```python
class AsyncToolExecutor:
    async def execute_tools_parallel(self, tasks: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """并行执行多个工具"""
    
    async def execute_tools_batch(self, tool_name: str, input_list: List[str]) -> List[Dict[str, Any]]:
        """批量执行同一个工具"""
```

## 🛠️ 内置工具详解

### 1. CalculatorTool (`calculator.py`)
提供数学计算能力：

**功能：**
- 支持基本运算（`+`, `-`, `*`, `/`, `**`）
- 支持数学函数（`sqrt`, `sin`, `cos`, `abs`, `round` 等）
- 支持常量（`pi`, `e`）

**使用示例：**
```python
tool = CalculatorTool()
result = tool.run({"input": "2 + 3 * 4"})  # "14"
result = tool.run({"input": "sqrt(16)"})  # "4.0"
```

### 2. SearchTool (`search_tool.py`)
提供多后端搜索能力：

**支持后端：**
- Tavily（推荐）
- SerpApi
- DuckDuckGo
- SearXNG
- Perplexity
- Hybrid（混合模式）

**功能特性：**
- 支持结构化和文本格式返回
- 支持获取完整页面内容
- 支持截断控制
- 支持最大结果数配置

**使用示例：**
```python
tool = SearchTool(backend="tavily", tavily_key="your_key")
result = tool.run({
    "input": "Python 教程",
    "max_results": 5,
    "mode": "text"
})
```

### 3. MemoryTool (`memory_tool.py`)
提供记忆管理能力：

**支持的记忆类型：**
- working（工作记忆）
- episodic（情景记忆）
- semantic（语义记忆）
- perceptual（感知记忆，支持图片/音频）

**支持的操作：**
- `add`：添加记忆
- `search`：搜索记忆
- `stats`：获取统计
- `update`：更新记忆
- `remove`：删除记忆
- `forget`：按策略遗忘
- `consolidate`：整合记忆
- `clear`：清空所有

**使用示例：**
```python
tool = MemoryTool()

# 添加记忆
tool.run({
    "action": "add",
    "content": "用户喜欢喝咖啡",
    "memory_type": "semantic",
    "importance": 0.8
})

# 搜索记忆
result = tool.run({
    "action": "search",
    "query": "用户喜欢的饮品",
    "limit": 3
})
```

### 4. RAGTool (`rag_tool.py`)
提供检索增强生成能力：

**功能特性：**
- 支持多种文档格式（PDF、Word、Excel、PPT、图片、音频等）
- 支持高级搜索（MQE、HyDE）
- 多命名空间隔离
- 智能问答（检索 + LLM 生成）
- 引用来源标注

**支持的操作：**
- `add_document`：添加文档
- `add_text`：添加文本
- `ask`：智能问答
- `search`：搜索知识库
- `stats`：获取统计
- `clear`：清空知识库

**使用示例：**
```python
tool = RAGTool()

# 添加文档
tool.run({
    "action": "add_document",
    "file_path": "document.pdf"
})

# 智能问答
result = tool.run({
    "action": "ask",
    "question": "什么是机器学习？",
    "limit": 5
})
```

### 5. TerminalTool (`terminal_tool.py`)
提供安全的命令行执行能力：

**安全特性：**
- 命令白名单（只允许安全的只读命令）
- 工作目录限制（沙箱）
- 超时控制
- 输出大小限制

**允许的命令：**
- 文件系统：`ls`, `dir`, `cat`, `type`, `head`, `tail`, `find`, `grep`
- 文本处理：`wc`, `sort`, `uniq`, `cut`, `awk`, `sed`
- 目录导航：`pwd`, `cd`
- 代码执行：`python`, `python3`, `node`, `bash`, `sh`, `powershell`, `cmd`

**使用示例：**
```python
# 自动检测操作系统
tool = TerminalTool(workspace="./project", os_type="auto")

# 列出文件
result = tool.run({"command": "ls -la"})  # Linux/Mac
result = tool.run({"command": "dir"})     # Windows

# 查看文件
result = tool.run({"command": "cat README.md"})

# 搜索代码
result = tool.run({"command": "grep -r 'TODO' src/"})
```

### 6. 其他内置工具
- `NoteTool`：结构化笔记工具
- `MCPTool`：MCP 协议工具（基于 MCP v1.15.0）
- `A2ATool`：A2A 协议工具（基于 python-a2a v0.5.10）
- `ANPTool`：ANP 协议工具（基于 agent-connect v0.3.7）
- `BFCLEvaluationTool`：BFCL 评估工具
- `GAIAEvaluationTool`：GAIA 评估工具
- `LLMJudgeTool`：LLM Judge 评估工具
- `WinRateTool`：Win Rate 评估工具
- `RLTrainingTool`：RL 训练工具

## 🔗 调用关系图

```
Agents (FunctionCallAgent, SimpleAgent, ReActAgent, etc.)
    │
    │ 使用
    ▼
ToolRegistry
    │
    ├─ 管理
    │  └─ Tool 基类
    │      ├─ CalculatorTool
    │      ├─ SearchTool
    │      ├─ MemoryTool
    │      ├─ RAGTool
    │      ├─ TerminalTool
    │      ├─ NoteTool
    │      ├─ MCPTool/A2ATool/ANPTool
    │      └─ Evaluation Tools
    │
    ├─ ToolChain
    │   └─ 支持工具链式调用
    │
    └─ AsyncToolExecutor
        └─ 支持工具异步并行执行
```

## 💡 使用示例

### 基本使用流程

```python
from agents.tools import (
    ToolRegistry,
    CalculatorTool,
    SearchTool,
    MemoryTool
)
from agents.agents import SimpleAgent, FunctionCallAgent

# 1. 创建工具注册表
registry = ToolRegistry()

# 2. 注册工具
registry.register_tool(CalculatorTool())
registry.register_tool(SearchTool())
registry.register_tool(MemoryTool())

# 3. 创建 Agent 并传入工具注册表
agent = SimpleAgent(
    name="助手",
    llm=your_llm,
    tool_registry=registry,
    enable_tool_calling=True
)

# 4. Agent 自动使用工具
response = agent.run("2 + 3 * 4 等于多少？搜索一下相关的数学教程。")
```

### 使用 ToolChain

```python
from agents.tools import ToolChain, ToolChainManager

# 创建工具链
chain = ToolChain(
    name="研究助手",
    description="搜索信息并进行分析"
)

# 添加步骤
chain.add_step(
    tool_name="search",
    input_template="{input}",
    output_key="search_result"
)

chain.add_step(
    tool_name="calculator",
    input_template="2 + 2",  # 可以使用上一步的输出变量
    output_key="calc_result"
)

# 注册并执行
manager = ToolChainManager(registry)
manager.register_chain(chain)
result = manager.execute_chain("研究助手", "机器学习")
```

### 使用异步执行器

```python
from agents.tools import AsyncToolExecutor, run_parallel_tools

# 并行执行多个任务
tasks = [
    {"tool_name": "search", "input_data": "Python"},
    {"tool_name": "search", "input_data": "JavaScript"},
    {"tool_name": "search", "input_data": "Go"}
]

results = await run_parallel_tools(registry, tasks)

# 批量执行同一个工具
results = await run_batch_tool(
    registry,
    tool_name="search",
    input_list=["Python", "JavaScript", "Go"]
)
```

## 📚 更多资源

- [Agent 模块说明](../agents/)
- [核心模块说明](../core/)
- [记忆系统说明](../memory/)
- [协议说明](../protocols/)
