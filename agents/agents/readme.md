# Agents 模块 - 智能体实现

本目录包含 HelloAgents 框架的各种 Agent 实现，提供不同范式的智能体能力。

## 📁 目录结构

```
agents/
├── __init__.py              # 模块入口，导出所有 Agent 类
├── simple_agent.py          # SimpleAgent：简单对话 Agent
├── function_call_agent.py   # FunctionCallAgent：OpenAI 函数调用 Agent
├── react_agent.py           # ReActAgent：推理与行动结合 Agent
├── reflection_agent.py      # ReflectionAgent：自我反思 Agent
├── plan_solve_agent.py      # PlanAndSolveAgent：规划与执行 Agent
└── tool_aware_agent.py      # ToolAwareSimpleAgent：增强的 SimpleAgent
```

## 🎯 核心 Agent 介绍

### 1. SimpleAgent (simple_agent.py)

**简单对话 Agent，支持可选的工具调用**

这是最基础的 Agent 实现，特点包括：
- 支持纯对话模式和工具调用模式
- 自定义工具调用格式：`[TOOL_CALL:tool_name:parameters]`
- 支持多轮工具调用迭代
- 内置智能参数解析和类型转换
- 支持流式输出（stream_run）

**使用示例：**
```python
from agents.agents import SimpleAgent
from agents.tools import ToolRegistry, CalculatorTool

# 创建工具注册表并注册工具
registry = ToolRegistry()
registry.register_tool(CalculatorTool())

# 创建 Agent
agent = SimpleAgent(
    name="数学助手",
    llm=your_llm,
    system_prompt="你是一个数学助手",
    tool_registry=registry,
    enable_tool_calling=True
)

# 使用 Agent
response = agent.run("计算 2 + 3 * 4")
```

**便捷方法：**
- `add_tool(tool)`: 直接添加工具到 Agent
- `remove_tool(tool_name)`: 移除工具
- `list_tools()`: 列出所有可用工具
- `has_tools()`: 检查是否有可用工具

---

### 2. FunctionCallAgent (function_call_agent.py)

**基于 OpenAI 原生函数调用机制的 Agent**

这是更强大的工具调用实现，特点包括：
- 使用 OpenAI 官方 Function Calling API
- 自动将工具描述转换为 JSON Schema
- 支持并行工具调用
- 支持配置默认工具选择策略
- 支持多轮迭代执行

**使用示例：**
```python
from agents.agents import FunctionCallAgent

agent = FunctionCallAgent(
    name="研究助手",
    llm=your_llm,
    system_prompt="你是一个研究助手",
    tool_registry=registry,
    enable_tool_calling=True,
    default_tool_choice="auto",  # "auto" | "none" | {"type": "function", ...}
    max_tool_iterations=5
)

response = agent.run("搜索 Python 的最新版本，然后计算它发布了多少天")
```

---

### 3. ReActAgent (react_agent.py)

**ReAct (Reasoning and Acting) Agent - 推理与行动结合的智能体**

这是经典的 Agent 范式，特点包括：
- 显式的思考（Thought）和行动（Action）分离
- 清晰的工作流程可视化
- 支持自定义提示词模板
- 特别适合需要外部信息的研究任务

**工作流程：**
```
Thought: 分析问题，制定策略
Action: 调用工具获取信息
Observation: 记录工具返回结果
...（迭代）
Action: Finish[最终答案]
```

**使用示例：**
```python
from agents.agents import ReActAgent

agent = ReActAgent(
    name="研究助手",
    llm=your_llm,
    tool_registry=registry,
    max_steps=5,
    custom_prompt=None  # 可自定义提示词
)

response = agent.run("查找 2024 年最热门的 AI 模型，然后比较它们的性能")
```

---

### 4. ReflectionAgent (reflection_agent.py)

**自我反思与迭代优化的智能体**

这是专注于质量迭代的 Agent 范式，特点包括：
- 初始尝试 → 自我反思 → 迭代优化 的工作流
- 内置 Memory 模块记录执行轨迹
- 支持自定义提示词模板（initial/reflect/refine）
- 特别适合代码生成、文档写作、分析报告等任务

**工作流程：**
```
1. 初始执行：根据任务生成初步结果
2. 反思阶段：审视结果，找出问题和改进空间
3. 优化阶段：根据反馈改进结果
4. 迭代循环：重复直到满意或达到最大迭代次数
```

**使用示例：**
```python
from agents.agents import ReflectionAgent

agent = ReflectionAgent(
    name="写作助手",
    llm=your_llm,
    max_iterations=3,
    custom_prompts={
        "initial": "自定义初始提示词...",
        "reflect": "自定义反思提示词...",
        "refine": "自定义优化提示词..."
    }
)

response = agent.run("写一篇关于 AI 伦理的 500 字文章")
```

---

### 5. PlanAndSolveAgent (plan_solve_agent.py)

**分解规划与逐步执行的智能体**

这是专注于复杂任务分解的 Agent 范式，特点包括：
- 两步架构：Planner（规划器）+ Executor（执行器）
- 将复杂问题分解为简单步骤
- 维护执行历史和上下文
- 特别适合多步骤推理、数学问题、复杂分析等任务

**工作流程：**
```
Planner: 生成步骤列表 → ["步骤1", "步骤2", "步骤3", ...]
Executor: 按步骤逐步执行 → 完成任务
```

**使用示例：**
```python
from agents.agents import PlanAndSolveAgent

agent = PlanAndSolveAgent(
    name="问题解决专家",
    llm=your_llm,
    custom_prompts={
        "planner": "自定义规划器提示词...",
        "executor": "自定义执行器提示词..."
    }
)

response = agent.run("解决这个数学问题：若 a + b = 5, a * b = 6，求 a² + b²")
```

---

### 6. ToolAwareSimpleAgent (tool_aware_agent.py)

**SimpleAgent 子类，记录工具调用情况**

这是 SimpleAgent 的增强版本，特点包括：
- 继承 SimpleAgent 的所有功能
- 新增工具调用监听器回调
- 增强的工具调用解析（支持嵌套参数）
- 支持流式输出中的工具调用
- 自动参数清理和规范化

**使用示例：**
```python
from agents.agents import ToolAwareSimpleAgent

# 定义监听器
def tool_listener(call_info):
    print(f"🔧 工具调用: {call_info['tool_name']}")
    print(f"   参数: {call_info['parsed_parameters']}")
    print(f"   结果: {call_info['result']}")

# 创建 Agent
agent = ToolAwareSimpleAgent(
    name="研究助手",
    llm=your_llm,
    tool_registry=registry,
    enable_tool_calling=True,
    tool_call_listener=tool_listener
)

# 使用 Agent
response = agent.run("搜索 AI 的最新新闻")
```

---

## 🔗 调用关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                          Agent 基类                              │
│                   (core/agent.py)                               │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ - name: str                                               │ │
│  │ - llm: HelloAgentsLLM                                     │ │
│  │ - _history: List[Message]                                 │ │
│  │ - run(input_text: str) -> str                            │ │
│  │ - add_message(message: Message)                          │ │
│  │ - clear_history()                                         │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ▲
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        │                     │                     │
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  SimpleAgent  │    │ FunctionCall  │    │   ReActAgent  │
│               │    │    Agent      │    │               │
│ - 自定义格式  │    │ - OpenAI API  │    │ - Thought →  │
│   工具调用    │    │ - JSON Schema │    │   Action →   │
│ - 智能解析    │    │ - 并行调用    │    │   Observation│
└───────────────┘    └───────────────┘    └───────────────┘
        ▲
        │
        │
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  ToolAware    │    │ Reflection    │    │ PlanAndSolve  │
│  SimpleAgent  │    │    Agent      │    │    Agent      │
│               │    │               │    │               │
│ - 工具监听器  │    │ - 反思迭代    │    │ - Planner +  │
│ - 增强解析    │    │ - Memory      │    │   Executor    │
│ - 流式支持    │    │               │    │               │
└───────────────┘    └───────────────┘    └───────────────┘

所有 Agent 都可以使用 ToolRegistry 来管理工具：

┌─────────────────────────────────────────────────────────────────┐
│                        ToolRegistry                              │
│                   (tools/registry.py)                            │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ - register_tool(tool)                                      │ │
│  │ - register_function(name, desc, func)                      │ │
│  │ - execute_tool(name, input)                                │ │
│  │ - get_tools_description()                                  │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                          ▲
                          │
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        │                 │                 │
   ┌────────┐      ┌────────┐       ┌────────┐
   │ Tool 1 │      │ Tool 2 │  ...  │ Tool N │
   └────────┘      └────────┘       └────────┘
  (Calculator)    (SearchTool)    (TerminalTool)
    etc...
```

## 📊 Agent 选择指南

| 场景/需求 | 推荐 Agent | 理由 |
|----------|------------|------|
| 简单对话，偶尔使用工具 | SimpleAgent | 轻量级，易于使用 |
| 复杂工具调用，需要并行执行 | FunctionCallAgent | 利用 OpenAI 原生能力 |
| 需要显式的推理过程 | ReActAgent | Thought → Action → Observation |
| 需要迭代优化结果 | ReflectionAgent | 反思 → 改进循环 |
| 多步骤推理，复杂任务分解 | PlanAndSolveAgent | 规划 + 执行分离 |
| 需要记录工具调用 | ToolAwareSimpleAgent | 内置监听器 |

## 💡 使用建议

1. **从 SimpleAgent 开始**：它是最基础的实现，易于理解和使用

2. **工具调用优先考虑 FunctionCallAgent**：利用 OpenAI 的原生能力，更稳定可靠

3. **研究任务用 ReActAgent**：可以清楚看到 Agent 的思考过程

4. **创造性任务用 ReflectionAgent**：需要迭代优化的任务效果更好

5. **数学/多步骤推理用 PlanAndSolveAgent**：分解问题降低复杂度

## 📚 更多资源

- [Tools 模块文档](../tools/readme.md)
- [Core 模块文档](../core)
- [Memory 模块文档](../memory)
