***

# 测试智能体群（Test Agents）设计文档 — Plan-and-Solve + Reflection 范式

## 1. 项目概述

基于 LangGraph 的分层多智能体测试系统。用户以自然语言描述需求，监督者自动规划执行步骤，按序调度 Worker Agent 完成任务，全步骤完成后反思评估，经验持久记录。

**架构范式：**

- **监督者**：Plan-and-Solve + 反思（全步骤完成后 LLM 评估，不完整则 replan）
- **执行者**：ReAct + 反思（LLM 评估结果质量，不通过则重试，受 max\_reflections 控制）
- **Worker 子图**作为主图节点注册，LangGraph 原生支持子图追踪
- 支持监督者调度和直接调用 Worker 两种模式

## 2. 架构设计

### 2.1 模式选型

采用 **Plan-and-Solve + Reflection** 分层架构：

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Supervisor 主图                                  │
│                                                                           │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌───────────┐            │
│  │ planner  │──→│ dispatch │──→│ reflect  │──→│ synthesize│            │
│  │ (分解任务) │   │ (路由分派) │   │ (整体反思) │   │ (汇总结果) │            │
│  └──────────┘   └────┬─────┘   └─────┬────┘   └─────┬─────┘            │
│       ↑               │               │               │                   │
│       │     ┌─────────┴─────────┐    │ replan        │                   │
│       │     ▼                   ▼    └───────────────┘                   │
│       │  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐         │
│       │  │code_analyzer │  │case_reviewer │  │save_experience│         │
│       │  │ (ReAct子图)   │  │ (ReAct子图)   │  │ (经验记录)     │         │
│       │  └──────┬───────┘  └──────┬───────┘  └───────────────┘         │
│       │         │                 │                                     │
│       │    ┌────┴────────────────┴────┐                                │
│       │    │        outputs 汇聚        │                                │
│       │    │  ┌────────────────────┐  │                                │
│       │    │  │ code_change_report │  │                                │
│       │    │  │ review_results     │  │                                │
│       │    │  │ ... (动态扩展)      │  │                                │
│       │    │  └────────────────────┘  │                                │
│       │    └──────────────────────────┘                                │
│       │                     ↑                                           │
│  ─────┼─────────────────────┼─────────────────────────────────────    │
│       │    Tool 层          │                                          │
│       │         ▼           │                                           │
│       │  ┌──────────────┐  │                                            │
│       │  │ ClaudeCliTool│  │                                            │
│       │  └──────────────┘  │  ┌──────────────┐                          │
│       │                   └──→│ TestCasePar- │                          │
│       │                      │ serTool      │                          │
│       │                      │ BusinessKn-  │                          │
│       │                      │ owledgeTool  │                          │
│       │                      └──────────────┘                          │
│       └────────────────────────────────────────────────────────────────│
└──────────────────────────────────────────────────────────────────────────┘
```

**调用层次：** `Planner → Dispatch → Worker(ReAct子图) → Tool`

**双重调用模式：**

| 调用模式        | 实现方式                              | 适用场景                 |
| ----------- | --------------------------------- | -------------------- |
| 监督者→Worker  | Worker 子图作为主图节点，dispatch 路由       | 复杂任务需要拆解时            |
| 直接调用 Worker | main.py 中直接 `worker_app.invoke()` | 简单任务，用户明确指定某 Agent 时 |

### 2.2 目录结构

```
test_agents/
├── agents/                      # 智能体定义
│   ├── __init__.py
│   ├── supervisor.py            # 监督者：planner + dispatch + reflect + synthesize + save_experience
│   ├── worker_base.py           # Worker 子图构建工厂（ReAct + 反思）
│   ├── code_analyzer.py         # 代码分析智能体（Worker 子图定义 + 工具绑定）
│   └── case_reviewer.py         # 用例评审智能体（Worker 子图定义 + 工具绑定）
├── tools/                       # 公共工具层
│   ├── __init__.py
│   ├── base.py                  # TestAgentTool 基类 + ToolRegistry 自动注册表
│   ├── claude_cli.py
│   ├── test_case_parser.py
│   └── business_knowledge.py
├── graph/                       # 图编排
│   ├── __init__.py
│   ├── state.py                 # SupervisorState + WorkerState（重新设计）
│   └── builder.py               # 主图构建与编译（重构）
├── skills/                      # Claude CLI Skills（不变）
│   ├── code_analysis_skill/
│   └── case_review_skill/
├── prompts/                     # 提示词模板
│   ├── supervisor.md            # 监督者各阶段提示词（planner / reflect / synthesize）
│   ├── worker_reflect.md        # Worker 反思提示词（新增）
│   ├── code_analyzer.md
│   └── case_reviewer.md
├── config.py                    # 配置
├── main.py                      # 入口（改为接收 user_request + 直接调用路由）
├── data/                            # 运行时数据
│   └── reflection_experience.md      # 经验记录文档（运行时生成）
```

## 3. 状态设计

### 3.1 主图状态（SupervisorState）

```python
from typing import Annotated, TypedDict, Literal, Optional, List
from langgraph.graph.message import AnyMessage, add_messages
import operator


class PlanStep(BaseModel):
    step_id: int                          # 步骤序号，从 1 开始
    agent: str                            # code_analyzer / case_reviewer
    description: str                      # 步骤描述
    input_mapping: dict[str, str]         # agent入参 → state字段引用或常量
    output_key: str = ""                  # 结果写入 outputs 的 key，空则按 agent 类型默认


class ExecutionPlan(BaseModel):
    intent: str                           # 用户意图摘要
    steps: list[PlanStep]                 # 有序步骤列表
    confirmed: bool = False               # 用户是否确认


class StepResult(BaseModel):
    step_id: int
    agent: str
    status: str                           # success / failed
    output_key: str                       # 结果写入主图 state 的哪个字段
    error: str = ""


class AnalysisTarget(BaseModel):
    module_name: str                      # 模块名称
    source_commit: str                    # 源 commit SHA
    target_commit: str                    # 目标 commit SHA
    commit_msg: str = ""                  # commit message


class SupervisorState(TypedDict):
    # === 用户输入 ===
    user_request: str                     # 自然语言需求（唯一输入）

    # === Planner 提取的参数 ===
    targets: list[AnalysisTarget]         # 分析目标列表（支持多模块）
    test_cases: list[dict]
    business_knowledge: str

    # === Plan-and-Solve ===
    plan: Optional[ExecutionPlan]         # LLM 生成的计划（JSON 序列化存储）
    current_step_index: int               # 当前执行步骤索引（0-based）
    step_results: Annotated[list, operator.add]  # reducer 聚合各步骤结果

    # === 反思相关 ===
    needs_replan: bool                    # 是否需要重新规划
    reflection_feedback: Optional[str]    # 反思反馈内容
    max_plan_iterations: int              # 防死循环，默认 1（不重新规划）
    plan_iterations: int                  # 当前已规划次数

    # === 计划确认相关 ===
    confirm_retry_count: int              # 确认重试次数，默认 0
    max_confirm_retries: int              # 最大确认重试次数，默认 3

    # === 通用结果汇聚（所有 Worker 产出统一写入此处）===
    outputs: Annotated[dict, operator.or_]  # key → value，Worker 按 output_key 写入

    # === 最终输出 ===
    final_answer: Optional[str]

    # === 消息历史 ===
    messages: Annotated[list[AnyMessage], add_messages]
```

### 3.2 Worker 子图状态（WorkerState）

```python
class WorkerState(TypedDict):
    # === 任务输入（dispatch 传入）===
    task: str                             # 当前步骤的子任务描述
    messages: Annotated[list[AnyMessage], add_messages]

    # === 反思相关 ===
    error: str                            # "yes" / "no"
    reflection_count: int
    max_reflections: int                  # 默认 0（不重试）

    # === 输出 ===
    result: str                           # 执行结果
    output_key: str                       # 结果写入主图 state 的哪个字段
```

### 3.3 主图与子图的状态映射

dispatch 节点负责双向映射：

**主图 → 子图：**

```python
worker_input = {
    "task": plan_step.description,
    "messages": [construct_agent_message(plan_step, state)],
    "error": "no",
    "reflection_count": 0,
    "max_reflections": 0,  # 默认不重试
    "output_key": plan_step.output_key or agent_default_output_key(plan_step.agent),
    "result": "",
}
```

**子图 → 主图：**
子图执行完后，dispatch 从 WorkerState.result 取结果，写入主图 `outputs[output_key]`。

### 3.4 多模块聚合规则

当有多个 code\_analyzer 步骤时，每个步骤产出写入 `outputs["code_change_report"]`（或 Planner 指定的其他 key）。dispatch 节点负责聚合：

- 同 `output_key` 的多份结果自动拼接，用 `## 模块: {module_name}` 标题分隔
- 不同 `output_key` 的结果隔离存储，互不影响
- 下游步骤通过 `input_mapping` 引用 `${outputs.code_change_report}` 或 `${outputs.code_change_report_payment}` 读取

### 3.5 input\_mapping 规则

| 形式         | 示例                                           | 含义                 |
| ---------- | -------------------------------------------- | ------------------ |
| 字符串常量      | `"payment"`                                  | 直接传给 agent         |
| Outputs 引用 | `"${outputs.code_change_report}"`            | 从 outputs 字典中取值    |
| 多 key 拼接   | `"${outputs.report_a}\n${outputs.report_b}"` | 拼接多个 outputs 值传给下游 |

## 4. 节点设计

### 4.1 Planner 节点

**职责：**

1. 解析 `user_request`，理解用户意图
2. 提取参数（targets 列表、test\_cases、business\_knowledge 等）
3. 生成 `ExecutionPlan`，包含有序步骤列表

**输出：** 更新 state 的 `plan`、`targets`、`test_cases`、`business_knowledge`

**Prompt 设计要点：**

- 告知 LLM 可用的 agent 列表及其能力、入参需求：

| Agent           | 能力     | 必需入参                                                   | 产出字段                 |
| --------------- | ------ | ------------------------------------------------------ | -------------------- |
| `code_analyzer` | 分析代码变更 | module\_name, source\_commit, target\_commit           | code\_change\_report |
| `case_reviewer` | 评审测试用例 | code\_change\_report, test\_cases, business\_knowledge | review\_results      |

- 要求 LLM 输出严格 JSON 格式的 ExecutionPlan
- LLM 根据用户意图选择最少步骤组合
- 多模块时为每个模块生成一个 code\_analyzer 步骤

**示例 1：** 用户说"分析 payment 模块从 abc1234 到 def5678 的代码变更并评审测试用例"

Planner 提取 targets：

```json
"targets": [
  {"module_name": "payment", "source_commit": "abc1234", "target_commit": "def5678", "commit_msg": ""}
]
```

生成的 plan：

```json
{
  "intent": "分析代码变更并评审测试用例",
  "steps": [
    {
      "step_id": 1,
      "agent": "code_analyzer",
      "description": "分析 payment 模块 abc1234→def5678 的代码变更",
      "input_mapping": {
        "module_name": "payment",
        "source_commit": "abc1234",
        "target_commit": "def5678"
      }
    },
    {
      "step_id": 2,
      "agent": "case_reviewer",
      "description": "基于变更报告评审测试用例",
      "input_mapping": {
        "code_change_report": "${code_change_report}",
        "test_cases": "${test_cases}",
        "business_knowledge": "${business_knowledge}"
      }
    }
  ],
  "confirmed": false
}
```

**示例 2：** 用户说"分析 payment 和 order 模块的代码变更"

Planner 提取 targets：

```json
"targets": [
  {"module_name": "payment", "source_commit": "abc1234", "target_commit": "def5678", "commit_msg": ""},
  {"module_name": "order", "source_commit": "abc1234", "target_commit": "def5678", "commit_msg": ""}
]
```

生成的 plan：

```json
{
  "intent": "分析 payment 和 order 模块的代码变更",
  "steps": [
    {
      "step_id": 1,
      "agent": "code_analyzer",
      "description": "分析 payment 模块 abc1234→def5678 的代码变更",
      "input_mapping": {
        "module_name": "payment",
        "source_commit": "abc1234",
        "target_commit": "def5678"
      }
    },
    {
      "step_id": 2,
      "agent": "code_analyzer",
      "description": "分析 order 模块 abc1234→def5678 的代码变更",
      "input_mapping": {
        "module_name": "order",
        "source_commit": "abc1234",
        "target_commit": "def5678"
      }
    }
  ],
  "confirmed": false
}
```

**提示词：** `prompts/planner.md`

### 4.2 ConfirmPlan 节点

**职责：** 暂停 graph 执行，展示计划给用户确认

**逻辑：**

- 展示 `plan.intent` 和每个步骤的 `description`
- 用户确认 → `plan.confirmed = True`，继续执行
- 用户拒绝 → 用户提供反馈建议，回到 planner 重新规划，再次提交确认
- 最多重试 3 次（`max_confirm_retries`），仍未确认则取消任务，设置 `error` 并终止

**状态字段：**

```python
confirm_retry_count: int        # 当前确认重试次数，默认 0
max_confirm_retries: int        # 最大确认重试次数，默认 3
```

**流程：**

```
ConfirmPlan
    ├─ 用户确认 → plan.confirmed = True → dispatch
    └─ 用户拒绝 → confirm_retry_count += 1
        ├─ 未超限 → 用户反馈写回 state → planner（重新规划）→ ConfirmPlan（再次确认）
        └─ 超限 → error = "用户多次拒绝计划，任务取消" → END
```

**实现方式：** 使用 LangGraph 的 `interrupt` 机制实现 human-in-the-loop，在 `main.py` 中捕获中断、展示计划、获取用户确认或拒绝反馈后 `Command(resume=...)` 继续

### 4.3 Dispatch 节点

**职责：** 按 `plan.steps[current_step_index]` 路由到对应 Worker 子图

**逻辑：**

```
1. plan 未确认 → 返回等待
2. current_step_index >= len(plan.steps) → 所有步骤完成 → 路由到 reflect
3. 读取 plan.steps[current_step_index]
4. 构建 WorkerState 输入（主图 → 子图映射）
5. 路由到对应 Worker 子图节点
6. Worker 执行完毕 → current_step_index += 1 → 回到步骤2
```

**路由映射：**

| plan.steps\[i].agent | Graph 节点        |
| -------------------- | --------------- |
| `code_analyzer`      | `code_analyzer` |
| `case_reviewer`      | `case_reviewer` |

**提示词：** `prompts/dispatch.md`

### 4.4 Reflect 节点（监督者反思）

**职责：** 全部步骤执行完后，LLM 评估整体结果是否完整正确

**触发条件：** `current_step_index >= len(plan.steps)`

**逻辑：**

```
1. LLM 评估：plan 的所有 step_results 是否完整正确地解决了 user_request
2. 评估结果：
   - COMPLETE → needs_replan = False → 进入 synthesize
   - REPLAN → needs_replan = True → 回到 planner（受 max_plan_iterations 限制）
3. 超过 max_plan_iterations → 强制进入 synthesize
4. 无论结果如何，记录规划与执行经验
```

**提示词：** `prompts/supervisor_reflect.md`

### 4.5 SaveExperience 节点（经验记录）

**职责：** 将规划与执行经验写入持久化文档

**逻辑：**

```
1. 读取本次 plan + step_results + reflection_feedback
2. LLM 生成经验摘要（意图→规划→结果→反思）
3. 写入 data/reflection_experience.md
4. 去重：LLM 判断新经验是否与已有经验语义重复，重复则不更新
```

**经验文档格式：**

```markdown
# 任务规划反思经验

## 经验 1
- **意图**: 分析代码变更并评审测试用例
- **规划**: [code_analyzer → case_reviewer]
- **结果**: 完成，LLM 评估 COMPLETE
- **反思**: 无

## 经验 2
- **意图**: 分析 payment 模块代码变更
- **规划**: [code_analyzer]
- **结果**: code_change_report 为空，因为 commit SHA 无效
- **反思**: 需在规划阶段验证参数有效性
```

**当前阶段：** 只记录经验，不在规划时引用。后续可扩展为 planner 读取经验辅助规划。

### 4.6 Synthesize 节点（汇总）

**职责：** 遍历 `outputs` 汇总所有 Worker 结果，生成最终输出

**逻辑：**

```
1. 读取 state["outputs"]，按 key 分组整理
2. 对每个 output_key，提取内容摘要（超长自动截断）
3. LLM 基于 outputs 内容 + step_results 综合回答 user_request
4. 输出 final_answer
```

**Prompt 输入：**

```python
output_summaries = []
for key, value in outputs.items():
    summary = f"【{key}】\n{str(value)[:3000]}"
    output_summaries.append(summary)

prompt = load_prompt(
    "synthesize",
    user_request=user_request,
    step_results=json.dumps(step_results, ensure_ascii=False),
    outputs="\n\n---\n\n".join(output_summaries),
)
```

**提示词：** `prompts/synthesize.md`（模板内不再硬编码 `code_change_report`，改为遍历 `outputs` 动态渲染）

### 4.7 Worker 子图（ReAct + 反思）

每个 Worker（code\_analyzer / case\_reviewer）是独立的 ReAct + Reflection 子图，作为主图节点注册。

**子图内部结构：**

```
START → agent → (有工具调用?) → tools → agent (循环)
                ↓ (无工具调用)
                reflect → (质量不通过?) → agent (重试，max_reflections 控制)
                ↓ (质量通过或超次)
                END → 返回 result
```

**节点：**

1. `agent` — LLM 绑定工具，处理 messages，决定调用工具或直接回答
2. `tools` — ToolNode，执行工具调用
3. `reflect` — LLM 评估结果质量

**反思逻辑（reflect 节点）：**

```
1. 检查 max_reflections，如果为 0 → 跳过反思，直接通过
2. LLM 评估结果质量
3. 通过 → error = "no"
4. 不通过 → error = "yes", reflection_count += 1, 反馈写回 messages
5. 超过 max_reflections → 强制通过
```

**条件路由（reflect 后）：**

```python
def worker_route(state: WorkerState) -> Literal["agent", "__end__"]:
    if state["error"] == "no":
        return "__end__"
    if state.get("reflection_count", 0) >= state.get("max_reflections", 0):
        return "__end__"  # 超次强制结束
    return "agent"  # 重试
```

**code\_analyzer 子图工具：** `ClaudeCliTool`
**case\_reviewer 子图工具：** `ClaudeCliTool`、`TestCaseParserTool`、`BusinessKnowledgeTool`

**子图构建工厂：**

```python
def build_worker_graph(tools: list) -> CompiledGraph:
    """构建 ReAct + Reflection Worker 子图"""
    graph = StateGraph(WorkerState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("reflect", worker_reflect)
    
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", "__end__": "reflect"})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("reflect", worker_route, {"agent": "agent", "__end__": END})
    
    return graph.compile()
```

**子图编译与注册：**

```python
code_analyzer_graph = build_worker_graph(code_analyzer_tools)
case_reviewer_graph = build_worker_graph(case_reviewer_tools)

# 作为主图节点注册
supervisor_graph.add_node("code_analyzer", code_analyzer_graph)
supervisor_graph.add_node("case_reviewer", case_reviewer_graph)
```

**提示词：** `prompts/worker_reflect.md`

## 5. 图编排（Graph Builder）

### 5.1 节点与边

```python
graph = StateGraph(SupervisorState)

# 添加节点
graph.add_node("planner", planner_node)
graph.add_node("confirm_plan", confirm_plan_node)
graph.add_node("dispatch", dispatch_node)
graph.add_node("code_analyzer", code_analyzer_graph)      # Worker 子图
graph.add_node("case_reviewer", case_reviewer_graph)      # Worker 子图
graph.add_node("reflect", supervisor_reflect_node)
graph.add_node("synthesize", synthesize_node)
graph.add_node("save_experience", save_experience_node)

# 固定边
graph.add_edge(START, "planner")
graph.add_edge("code_analyzer", "dispatch")                # Worker 完成后回 dispatch
graph.add_edge("case_reviewer", "dispatch")                # Worker 完成后回 dispatch
graph.add_edge("synthesize", "save_experience")
graph.add_edge("save_experience", END)

# 条件边 1：planner 后路由（首次→confirm_plan，重新规划→confirm_plan）
graph.add_conditional_edges(
    "planner",
    lambda state: "confirm_plan",
    {"confirm_plan": "confirm_plan"}
)

# 条件边 2：confirm_plan 后路由（确认→dispatch，拒绝未超限→planner，拒绝超限→END）
graph.add_conditional_edges(
    "confirm_plan",
    route_from_confirm,
    {
        "dispatch": "dispatch",
        "planner": "planner",
        "end": END
    }
)

# 条件边 3：dispatch 路由到 Worker 或 reflect
graph.add_conditional_edges(
    "dispatch",
    route_from_dispatch,
    {
        "code_analyzer": "code_analyzer",
        "case_reviewer": "case_reviewer",
        "reflect": "reflect"
    }
)

# 条件边 4：reflect 后路由（replan / synthesize）
graph.add_conditional_edges(
    "reflect",
    route_from_reflect,
    {
        "planner": "planner",        # replan
        "synthesize": "synthesize"   # 完成
    }
)
```

### 5.2 条件路由函数

```python
def route_from_confirm(state: SupervisorState) -> Literal["dispatch", "planner", "end"]:
    """confirm_plan 后路由：确认→dispatch，拒绝→planner（重试），超限→end"""
    if state.get("plan") and state["plan"].confirmed:
        return "dispatch"
    if state.get("confirm_retry_count", 0) >= state.get("max_confirm_retries", 3):
        return "end"  # 超限取消
    return "planner"  # 拒绝但未超限，重新规划


def route_from_dispatch(state: SupervisorState) -> Literal["code_analyzer", "case_reviewer", "reflect"]:
    """dispatch 后路由：还有步骤→Worker，全部完成→reflect"""
    if state["current_step_index"] >= len(state["plan"].steps):
        return "reflect"
    agent = state["plan"].steps[state["current_step_index"]].agent
    return agent


def route_from_reflect(state: SupervisorState) -> Literal["planner", "synthesize"]:
    """reflect 后路由：需要 replan→planner，完成→synthesize"""
    if state.get("needs_replan") and state.get("plan_iterations", 0) < state.get("max_plan_iterations", 1):
        return "planner"
    return "synthesize"
```

### 5.3 完整执行流程

```
用户输入 user_request（自然语言）
    ↓
START → Planner
    ├─ 解析 user_request
    ├─ 提取参数
    └─ 生成 ExecutionPlan
    ↓
ConfirmPlan（interrupt，等待用户确认）
    ├─ 展示计划
    └─ 用户确认 → plan.confirmed = True
    ↓
Dispatch
    ↓ 读取 plan.steps[0] → code_analyzer 子图
    ↓
CodeAnalyzer（ReAct 子图）
    ├─ agent: LLM + ClaudeCliTool
    ├─ tools: 执行工具调用
    ├─ reflect: 评估结果质量（max_reflections=0 默认跳过）
    └─ 返回 result → code_change_report
    ↓
Dispatch
    ↓ 读取 plan.steps[1] → case_reviewer 子图
    ↓
CaseReviewer（ReAct 子图）
    ├─ agent: LLM + ClaudeCliTool + TestCaseParserTool + BusinessKnowledgeTool
    ├─ tools: 执行工具调用
    ├─ reflect: 评估结果质量
    └─ 返回 result → review_results
    ↓
Dispatch
    ↓ current_step_index >= len(steps) → reflect
    ↓
Reflect（监督者反思）
    ├─ LLM 评估整体结果
    ├─ COMPLETE → synthesize
    └─ REPLAN → planner（受 max_plan_iterations 限制）
    ↓
Synthesize
    ├─ 汇总 step_results
    └─ 生成 final_answer
    ↓
SaveExperience
    ├─ 记录规划与执行经验
    ├─ LLM 去重判断
    └─ 写入 reflection_experience.md
    ↓
END → 输出 final_answer
```

### 5.4 直接调用模式

```python
# main.py 中
def is_simple_request(user_request: str) -> bool:
    """判断是否为简单请求，可直接调用单个 Worker。
    MVP 阶段用关键词匹配，后续可改为 LLM 判断。"""
    single_agent_keywords = {
        "code_analyzer": ["分析代码", "代码变更", "code change", "git diff"],
        "case_reviewer": ["评审用例", "测试用例评审", "case review"],
    }
    ...

if is_simple_request(user_request):
    # 直接调用 Worker 子图
    worker_input = {
        "task": user_request,
        "messages": [{"role": "user", "content": user_request}],
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": "code_change_report",  # 根据 Worker 类型
        "result": "",
    }
    result = worker_app.invoke(worker_input)
    # 直接调用模式下，结果写入统一的 outputs 结构
    outputs = {"code_change_report": result.get("result", "")}
    # 最终答案直接取自 outputs
    final_answer = outputs.get("code_change_report", "")
else:
    # 走监督者主图
    result = supervisor_app.invoke({
        "user_request": user_request,
        "current_step_index": 0,
        "step_results": [],
        "outputs": {},
        "needs_replan": False,
        "plan_iterations": 0,
        "max_plan_iterations": 1,
        "messages": [],
        ...
    })
```

## 6. 工具层设计

### 6.1 架构变更

v3 重构工具层，采用 **TestAgentTool 基类 + ToolRegistry 自动注册表** 模式，消除 v1/v2 的 `@tool` 适配层：

```
v1/v2（三层）:
  原始工具类(ClaudeCliTool) → @tool适配器(langchain_adapters.py) → bind_tools

v3（两层）:
  TestAgentTool子类 ──→ ToolRegistry ──→ bind_tools / render_all()
```

工具直接继承 LangChain `BaseTool`，**工具本身即是 LangChain 工具**，无需额外适配层。

### 6.2 核心组件

#### TestAgentTool（工具基类）

所有项目工具统一继承 `TestAgentTool(BaseTool)`，子类定义时自动注册类到 `ToolRegistry`：

```python
class TestAgentTool(BaseTool):
    """项目工具基类，子类定义时自动注册类到 ToolRegistry，使用时懒实例化"""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            ToolRegistry._tool_classes[getattr(cls, "name", cls.__name__)] = cls

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        ToolRegistry.register(self)
```

工具定义示例：

```python
class ClaudeCliTool(TestAgentTool):
    name: str = "claude_cli"
    description: str = "调用 Claude CLI 执行分析任务。prompt 为完整提示词，model 为可选模型名。"

    class InputSchema(BaseModel):
        prompt: str = Field(description="传递给 Claude CLI 的完整提示词")
        model: str = Field(default="", description="指定模型（可选）")

    args_schema: type = InputSchema

    def _run(self, prompt: str, model: str = "") -> str:
        ...
```

#### ToolRegistry（自动注册表）

统一管理所有工具实例，提供查询和渲染接口：

```python
class ToolRegistry:
    _tools: dict[str, BaseTool] = {}       # 已实例化的工具
    _tool_classes: dict[str, type] = {}    # 已注册的工具类（懒实例化）

    @classmethod
    def get_all(cls) -> list[BaseTool]: ...

    @classmethod
    def get_by_name(cls, name: str) -> BaseTool | None: ...

    @classmethod
    def get_tools_by_names(cls, names: list[str]) -> list[BaseTool]: ...

    @classmethod
    def render_all(cls) -> str: ...         # 渲染工具描述供 Planner prompt 使用
```

**懒实例化机制：** 子类定义时只注册类定义（`__init_subclass__`），首次调用 `get_all` / `get_by_name` / `get_tools_by_names` 时才实例化，避免 import 时的副作用。

### 6.3 工具列表

| 工具                         | 类名                      | 描述                  | 绑定 Worker                      |
| -------------------------- | ----------------------- | ------------------- | ------------------------------ |
| `claude_cli`               | `ClaudeCliTool`         | 封装 `claude -p` 调用   | code\_analyzer, case\_reviewer |
| `parse_test_cases`         | `TestCaseParserTool`    | 统一解析 JSON/Text 用例输入 | case\_reviewer                 |
| `query_business_knowledge` | `BusinessKnowledgeTool` | 按模块名查询本地业务知识        | case\_reviewer                 |

### 6.4 使用方式

**Worker 绑定工具：**

```python
# agents/code_analyzer.py
from test_agents.tools.base import ToolRegistry

_code_analyzer_tools = ToolRegistry.get_tools_by_names(["claude_cli"])

# agents/case_reviewer.py
_case_reviewer_tools = ToolRegistry.get_tools_by_names([
    "claude_cli", "parse_test_cases", "query_business_knowledge"
])
```

**Planner 动态注入工具描述：**

```python
# agents/supervisor.py - planner_node
from test_agents.tools.base import ToolRegistry

tools_info = ToolRegistry.render_all()
prompt = load_prompt("planner", user_request=user_request, tools_info=tools_info)
```

`render_all()` 内部调用 LangChain 的 `render_text_description()` 从工具的 `name` + `description` + `args` 自动生成，无需在 prompt 中硬编码。

### 6.5 新增工具流程

新增工具只需两步，无需修改 Worker 或 Prompt 文件：

1. **新增工具类** — 在 `tools/` 下新建 `TestAgentTool` 子类，自动注册到 `ToolRegistry`
2. **Worker 绑定** — 在对应 Worker 的 `get_tools_by_names` 列表中添加工具名

Planner prompt 中的 `{tools_info}` 由 `ToolRegistry.render_all()` 动态生成，自动包含新工具描述。

### 6.6 目录结构

```
tools/
├── __init__.py              # 触发 import，自动注册所有工具类
├── base.py                  # TestAgentTool + ToolRegistry
├── claude_cli.py            # ClaudeCliTool(TestAgentTool)
├── test_case_parser.py      # TestCaseParserTool(TestAgentTool)
└── business_knowledge.py    # BusinessKnowledgeTool(TestAgentTool)
```

## 7. Skill 层设计

与 v1 相同，无变更。

## 8. 错误处理

| 场景             | 处理方式                                                 |
| -------------- | ---------------------------------------------------- |
| Planner 无法理解意图 | `plan` 为 None，返回错误提示要求用户补充说明                         |
| Planner 输出格式异常 | 重试一次，仍失败则 error 终止                                   |
| 用户拒绝计划         | 返回修改意图或终止                                            |
| Worker 步骤失败    | 记录 step\_results，dispatch 继续下一步                      |
| Worker 反思超次    | max\_reflections 到达后强制通过                             |
| 监督者反思 REPLAN   | 回 planner 重规划，max\_plan\_iterations 到达后强制 synthesize |
| Worker 子图内工具异常 | ToolNode 捕获，返回错误消息给 agent 重试                         |
| 经验写入失败         | 静默跳过，不影响主流程                                          |
| 用例格式错误         | TestCaseParserTool 返回结构化错误                           |
| 业务知识库未命中       | 返回空字符串继续执行                                           |

### 3.6 通用 outputs 机制详解

#### 设计动机

随着测试领域 Agent 数量增长（测试计划生成、缺陷分析、覆盖率评估、自动化脚本生成等），固定字段模式会导致 `SupervisorState` 线性膨胀，每新增一个 Agent 需改三处（State + wrapper + synthesize）。`outputs` 机制将结果汇聚从**硬编码**转为**配置驱动**。

#### 核心规则

1. **写入规则**：Worker wrapper 执行完成后，将结果写入 `outputs[step.output_key]`
2. **聚合规则**：同 `output_key` 的多次写入自动拼接（用分隔符区分来源）
3. **读取规则**：下游 Worker 通过 `input_mapping` 中的 `${outputs.xxx}` 引用

#### 实现要点

1. `SupervisorState` 中仅保留 `outputs`，移除 `code_change_report`、`review_results` 等固定字段
2. Worker wrapper 统一写入 `outputs[output_key]`，不再回写旧字段
3. `input_mapping` 解析器支持 `${outputs.xxx}` 语法，从 `outputs` 字典取值
4. synthesize 节点遍历 `outputs` 生成汇总报告
5. 所有测试同步更新，mock state 中使用 `outputs` 替代旧字段

#### 示例：多 Agent 协作的数据流

```
用户：分析 payment 和 order 模块的代码变更，生成测试计划并评审

Planner 生成 plan：
  Step 1: code_analyzer (payment) → outputs["report_payment"]
  Step 2: code_analyzer (order)   → outputs["report_order"]
  Step 3: test_plan_generator     → outputs["test_plan"]
       input: "${outputs.report_payment}\n${outputs.report_order}"
  Step 4: case_reviewer           → outputs["review_results"]
       input: "${outputs.test_plan}"

Synthesize 遍历 outputs：
  【report_payment】xxx
  【report_order】xxx
  【test_plan】xxx
  【review_results】xxx
  → 生成 final_answer
```

## 9. 扩展性

### 9.1 增加 Worker（基于 outputs 机制）

新增 Worker 时，**无需修改** **`SupervisorState`** **定义**，只需三步：

1. **新增 agent 文件** — 实现 Worker wrapper，指定 `output_key`（如 `test_plan_generator` → `output_key="test_plan"`）
2. **在 dispatch 路由中注册** — `route_from_dispatch` 增加 agent → node 的映射
3. **在 Planner prompt 中补充能力描述** — 告知 LLM 新 agent 的能力、入参和 `output_key`

Worker 执行结果自动写入 `outputs[output_key]`，synthesize 节点无需修改即可遍历到新结果。

### 9.2 同类型 Worker 多实例执行

当需要多个 `code_analyzer` 分析不同模块时：

- **聚合模式**（默认）：所有实例共用 `output_key="code_change_report"`，结果自动拼接
- **隔离模式**：Planner 为每个实例分配不同 `output_key`（如 `code_change_report_payment`、`code_change_report_order`），下游步骤通过 `input_mapping` 按需引用

```json
{
  "steps": [
    {"agent": "code_analyzer", "output_key": "report_payment", "input_mapping": {"module_name": "payment"}},
    {"agent": "code_analyzer", "output_key": "report_order", "input_mapping": {"module_name": "order"}},
    {"agent": "case_reviewer", "output_key": "review_results", "input_mapping": {
      "code_change_report": "${outputs.report_payment}\n${outputs.report_order}"
    }}
  ]
}
```

### 9.3 其他扩展

- **替换模型**：通过 `config.py` 统一配置
- **新增 Tool**：在 `tools/` 下新增，在对应 Worker 子图中绑定
- **经验引用**：后续可扩展 planner 读取 `reflection_experience.md` 辅助规划
- **条件分支**：未来可在 ExecutionPlan 中增加条件步骤，dispatch 评估条件后决定路由

## 10. 依赖

```
langgraph
langchain-core
langchain-openai
pydantic
```

Claude CLI 需单独安装并配置到 PATH 中。

## 11. 与之前版本的关键差异

| 维度        | v1（Supervisor 模式） | v2（Plan-and-Solve）      | v3（Plan-and-Solve + Reflection）    |
| --------- | ----------------- | ----------------------- | ---------------------------------- |
| 用户输入      | CLI 结构化参数         | 自然语言 user\_request      | 自然语言 user\_request                 |
| 监督者范式     | 硬编码 if-else 路由    | Planner + Executor      | Planner + Dispatch + Reflect       |
| 监督者反思     | 无                 | 无                       | 全步骤完成后 LLM 评估，可 replan             |
| Worker 范式 | 简单执行              | 简单执行                    | ReAct + 反思子图                       |
| Worker 反思 | 无                 | 无                       | LLM 评估结果质量，可重试                     |
| 子图集成      | 无                 | 无                       | Worker 子图作为主图节点注册                  |
| 经验记录      | 无                 | 无                       | 规划与执行经验持久记录                        |
| 直接调用      | 不支持               | 不支持                     | main.py 中直接调 worker\_app           |
| 用户确认      | 无                 | 有（interrupt）            | 有（interrupt）                       |
| 参数来源      | 用户直接提供            | Planner 从自然语言提取         | Planner 从自然语言提取                    |
| 步骤间数据传递   | 隐式                | 显式 input\_mapping + ${} | 显式 input\_mapping + ${outputs.xxx} |
| 结果汇聚      | 固定字段（硬编码）         | 固定字段（硬编码）               | 通用 `outputs` 字典（配置驱动）              |

## 12. 反思与经验机制详解

### 12.1 监督者反思（层级间反思）

| 项目    | 说明                                                  |
| ----- | --------------------------------------------------- |
| 触发条件  | 所有步骤执行完成后                                           |
| 评估方式  | LLM 评估 plan + step\_results 是否完整正确地解决 user\_request |
| 通过处理  | needs\_replan=False → synthesize                    |
| 不通过处理 | needs\_replan=True → 回 planner 重规划                  |
| 安全限制  | max\_plan\_iterations（默认 1，即不重新规划）防止死循环             |

### 12.2 Worker 反思（层级内反思）

| 项目    | 说明                                   |
| ----- | ------------------------------------ |
| 触发条件  | agent 执行完（无工具调用后）                    |
| 评估方式  | LLM 评估结果质量                           |
| 通过处理  | error="no" → 子图结束                    |
| 不通过处理 | error="yes" → 反馈写回 messages，agent 重试 |
| 安全限制  | max\_reflections（默认 0，即默认不重试）        |

### 12.3 经验记录

| 项目   | 说明                             |
| ---- | ------------------------------ |
| 触发条件 | 每次 synthesize 后                |
| 记录内容 | 意图、规划、结果、反思反馈                  |
| 去重方式 | LLM 语义判断是否与已有经验重复              |
| 存储位置 | data/reflection\_experience.md |
| 当前使用 | 只记录，不引用                        |
| 未来扩展 | planner 读取经验辅助规划               |

