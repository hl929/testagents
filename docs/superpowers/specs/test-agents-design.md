***

# 测试智能体群（Test Agents）设计文档 — Plan-and-Solve + Reflection 范式

## 1. 项目概述

基于 LangGraph 的分层多智能体测试系统。用户以自然语言描述需求，监督者自动规划执行步骤，按序调度 Worker Agent 完成任务，全步骤完成后反思评估，经验持久记录。

**架构范式：**

- **监督者**：Plan-and-Solve + 反思（全步骤完成后 LLM 评估，不完整则 replan）
- **执行者**：ReAct + 反思（LLM 评估结果质量，不通过则重试，受 max\_reflections 控制）
- **Worker 子图**通过 wrapper 函数包装后作为主图节点注册，wrapper 负责 `SupervisorState → WorkerState` 转换及结果聚合
- 支持监督者调度和直接调用 Worker 两种模式

## 2. 架构设计

### 2.1 模式选型

采用 **Intent Classification + Plan-and-Solve + Reflection** 分层架构：

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Supervisor 主图                                  │
│                                                                           │
│  ┌──────────────────┐   ┌──────────┐   ┌──────────┐   ┌───────────┐    │
│  │intent_classifier │──→│ planner  │──→│ dispatch │──→│ reflect   │    │
│  │ (分类+意图提取)    │   │ (分解任务) │   │ (路由分派) │   │ (整体反思) │    │
│  └────────┬─────────┘   └──────────┘   └────┬─────┘   └─────┬────┘    │
│           │ irrelevant / ambiguous          │               │          │
│           ▼                                 │               │          │
│      ┌──────────┐                           │               │          │
│      │  reply   │                           │               │          │
│      │ (友好回复) │                           │               │          │
│      └────┬─────┘                           │               │          │
│           │                                 │               │          │
│           ▼                                 ▼               ▼          │
│          END                         ┌───────────┐   ┌───────────┐    │
│                                      │ synthesize│   │save_exper-│    │
│                                      │ (汇总结果) │   │ ience     │    │
│                                      └─────┬─────┘   └─────┬─────┘    │
│                                            │               │          │
│                                            ▼               ▼          │
│                                           END             END          │
│       ↑                                    │                          │
│       │     ┌─────────┴─────────┐         │                           │
│       │     ▼                   ▼         │                           │
│       │  ┌──────────────┐  ┌──────────────┐                          │
│       │  │code_analyzer │  │case_reviewer │                          │
│       │  │ (ReAct子图)   │  │ (ReAct子图)   │                          │
│       │  └──────┬───────┘  └──────┬───────┘                          │
│       │         │                 │                                   │
│       │    ┌────┴────────────────┴────┐                              │
│       │    │        outputs 汇聚        │                              │
│       │    │  ┌────────────────────┐  │                              │
│       │    │  │ code_change_report │  │                              │
│       │    │  │ review_results     │  │                              │
│       │    │  │ ... (动态扩展)      │  │                              │
│       │    │  └────────────────────┘  │                              │
│       │    └──────────────────────────┘                              │
│       │                     ↑                                         │
│  ─────┼─────────────────────┼─────────────────────────────────────   │
│       │    Tool 层          │                                         │
│       │         ▼           │                                          │
│       │  ┌──────────────┐  │                                           │
│       │  │ ClaudeCliTool│  │                                           │
│       │  └──────────────┘  │  ┌──────────────┐                         │
│       │                   └──→│ TestCasePar- │                         │
│       │                      │ serTool      │                         │
│       │                      │ BusinessKn-  │                         │
│       │                      │ owledgeTool  │                         │
│       │                      └──────────────┘                         │
│       └────────────────────────────────────────────────────────────────│
└──────────────────────────────────────────────────────────────────────────┘
```

**调用层次：** `Planner → Dispatch → Worker(ReAct子图) → Tool`

**双重调用模式：**

| 调用模式        | 实现方式                              | 适用场景                 |
| ----------- | --------------------------------- | -------------------- |
| 监督者→Worker  | Worker 子图经 wrapper 包装后作为主图节点，dispatch 路由 | 复杂任务需要拆解时            |
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
├── observability/               # 可观测性子包（详见 §13）
│   ├── __init__.py              # 导出 setup_logging / new_trace / flush_metrics / make_run_config / ObservabilityCallback
│   ├── context.py               # ContextVar(trace_id) + new_trace / get_trace_id
│   ├── logger.py                # setup_logging：注册 Filter/Handler，幂等
│   ├── filters.py               # ContextInjectFilter：注入 trace_id 到 LogRecord
│   ├── handlers.py              # JsonlMultiHandler：主日志 + per-trace 双写
│   ├── callback.py              # ObservabilityCallback(BaseCallbackHandler)：拦截 node/llm/tool 事件
│   └── metrics.py               # MetricsCollector：trace 维度聚合，flush 到 metrics.jsonl
├── tools/                       # 公共工具层
│   ├── __init__.py
│   ├── base.py                  # TestAgentTool 基类 + ToolRegistry 自动注册表
│   ├── claude_cli.py
│   ├── test_case_parser.py
│   ├── business_knowledge.py
│   └── fs/                      # 本地文件系统工具子包
│       ├── __init__.py
│       ├── _rg.py               # ripgrep subprocess 共享封装
│       ├── read_file.py         # ReadFileTool
│       ├── list_dir.py          # ListDirTool
│       ├── grep.py              # GrepTool
│       └── glob.py              # GlobTool
├── graph/                       # 图编排
│   ├── __init__.py
│   ├── state.py                 # SupervisorState + WorkerState（重新设计）
│   └── builder.py               # 主图构建与编译（重构）
├── prompts/                     # 提示词模板
│   ├── intent_classifier.md     # 意图分类提示词
│   ├── reply.md                 # 无关/模糊请求回复提示词
│   ├── supervisor.md            # 监督者各阶段提示词（planner / reflect / synthesize）
│   ├── worker_reflect.md        # Worker 反思提示词（新增）
│   ├── code_analyzer.md
│   └── case_reviewer.md
├── config.py                    # 配置
├── main.py                      # 入口（改为接收 user_request + 直接调用路由）
├── data/                            # 运行时数据
│   └── reflection_experience.md      # 经验记录文档（运行时生成）
├── logs/                             # 可观测性输出（详见 §13）
│   ├── app-YYYY-MM-DD.jsonl          # 主日志，按天滚动
│   ├── metrics.jsonl                 # 每次执行追加一行 summary
│   └── traces/<trace_id>.jsonl       # 每个 trace 一个文件
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


class IntentExtraction(BaseModel):
    goal: str                              # 用户核心意图
    modules: list[str] = []                # 涉及的模块名列表
    source_commit: str = ""                # 源 commit SHA
    target_commit: str = ""                # 目标 commit SHA
    needs_code_analysis: bool = False      # 是否需要代码变更分析
    needs_case_review: bool = False        # 是否需要测试用例评审
    test_cases_provided: bool = False      # 用户是否提供了测试用例
    missing_info: list[str] = []           # 缺少的关键信息


class SupervisorState(TypedDict):
    # === 用户输入 ===
    user_request: str                     # 自然语言需求（唯一输入）

    # === Planner 提取的参数 ===
    targets: list[AnalysisTarget]         # 分析目标列表（支持多模块）
    test_cases: list[dict]
    business_knowledge: str

    # === Plan-and-Solve ===
    # 实际存储为 dict（planner_node 内通过 ExecutionPlan.model_dump() 序列化后写入），
    # 以便 LangGraph state 直接序列化/反序列化。
    plan: Optional[dict]                  # LLM 生成的计划（JSON 序列化存储）
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

    # === Dispatch → Worker wrapper 中间传递 ===
    worker_input: Optional[dict]            # dispatch 节点构建的 WorkerState 输入，由 wrapper 取出后传入子图

    # === 最终输出 ===
    final_answer: Optional[str]

    # === 意图分类 ===
    intent_classification: str              # "relevant" / "ambiguous" / "irrelevant"
    intent_reason: str                      # 分类理由
    intent_analysis: Optional[dict]         # 结构化意图提取（仅 relevant 时有值，IntentExtraction.model_dump()）

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

dispatch 节点与 Worker wrapper 节点配合完成双向映射：

**主图 → 子图（由 dispatch 构建 worker_input）：**

```python
# dispatch_node 内
worker_input = {
    "task": plan_step.description,
    "messages": [construct_agent_message(plan_step, state)],
    "error": "no",
    "reflection_count": 0,
    "max_reflections": 0,  # 默认不重试
    "output_key": plan_step.output_key or agent_default_output_key(plan_step.agent),
    "result": "",
}
return {"worker_input": worker_input}  # 写入 SupervisorState，由下游 wrapper 取出
```

**子图执行（由 wrapper 调用）：**

```python
# code_analyzer_wrapper / case_reviewer_wrapper 内
worker_input = state.get("worker_input")
result = worker_graph.invoke(worker_input)  # 调用编译后的子图
```

**子图 → 主图（由 wrapper 聚合结果）：**
子图执行完后，wrapper 从 `WorkerState.result` 取结果，写入主图 `outputs[output_key]`，并追加 `step_results` 与递增 `current_step_index`。

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

### 4.1 Intent Classifier 节点

**职责：** 在正式进入规划流程前，判断用户请求是否与系统能力相关，并对 `relevant` 请求提取结构化意图信息。

**输入：** `state["user_request"]`
**输出：** `{"intent_classification": "relevant", "intent_reason": "...", "intent_analysis": {...}}`

**三分类规则：**

| 分类 | 含义 | extracted | 示例 |
|---|---|---|---|
| `relevant` | 明确涉及代码分析或测试用例评审 | 输出 `IntentExtraction` | "分析 payment 模块代码变更" |
| `ambiguous` | 提到相关关键词但不明确具体需求 | 不输出（null） | "帮我看看测试" |
| `irrelevant` | 完全无关 | 不输出（null） | "hello"、"今天天气怎样" |

**输出格式：**

relevant 时输出结构化提取：
```json
{
  "classification": "relevant",
  "reason": "明确提到代码分析，包含模块名和 commit 范围",
  "extracted": {
    "goal": "分析代码变更并评审测试用例",
    "modules": ["payment"],
    "source_commit": "abc1234",
    "target_commit": "def5678",
    "needs_code_analysis": true,
    "needs_case_review": true,
    "test_cases_provided": false,
    "missing_info": []
  }
}
```

ambiguous / irrelevant 时不输出 `extracted`：
```json
{"classification": "ambiguous", "reason": "提到测试但未说明具体模块"}
```

**实现逻辑：**
1. 使用 `load_prompt("intent_classifier", user_request=user_request)` 生成 prompt
2. 调用 LLM，期望返回 JSON
3. `relevant` 时解析 `extracted` 字段，通过 `IntentExtraction.model_validate()` 校验后写入 `intent_analysis`
4. `extracted` 解析失败时 `intent_analysis = None`，`classification` 保持不变
5. 分类解析失败时默认 `classification = "ambiguous"`

**降级策略：**

| 场景 | 行为 |
|---|---|
| LLM 返回非 JSON | `classification = "ambiguous"`, `intent_analysis = None` |
| JSON 缺少 `classification` 字段 | 同上 |
| LLM 调用失败（网络/超时） | 捕获异常，默认 `classification = "ambiguous"`，不中断流程 |
| `classification = "relevant"` 但 `extracted` 缺失 | `intent_analysis = None`，planner 自行理解 user_request |
| `extracted` 字段不合法 | `IntentExtraction.model_validate()` 失败，`intent_analysis = None` |

**提示词：** `prompts/intent_classifier.md`

### 4.2 Reply 节点

**职责：** 对无关或模糊请求生成友好回复，直接结束流程。

**输入：** `state["user_request"]`, `state["intent_classification"]`, `state["intent_reason"]`
**输出：** `{"final_answer": "..."}`

**实现逻辑：**
1. 使用 `load_prompt("reply", user_request=..., classification=..., reason=...)` 生成 prompt
2. 调用 LLM 生成一段自然、友好的回复
3. 回复写入 `final_answer`

**回复策略：**
- `irrelevant`：礼貌说明系统能力范围，举例可用请求格式
- `ambiguous`：说明理解到用户可能有相关需求，但信息不足，请补充具体模块名 / commit / 用例

**提示词：** `prompts/reply.md`

### 4.3 Planner 节点

**职责：**

1. 基于 `intent_analysis`（辅助）或 `user_request`（原始），理解用户意图
2. 提取参数（targets 列表、test_cases、business_knowledge 等）
3. 生成 `ExecutionPlan`，包含有序步骤列表

**输出：** 更新 state 的 `plan`、`targets`、`test_cases`、`business_knowledge`

**与 Intent Classifier 的协作：**

- `intent_analysis` 非空时，planner 直接参考其中的 goal、modules、commit 范围生成步骤，无需重新理解用户需求
- `intent_analysis` 为 None 时，planner 根据原始 `user_request` 自行理解（回退到旧行为）
- `intent_analysis` 是辅助参考，非强制依赖

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

**说明：** dispatch 节点为纯路由逻辑，根据 `current_step_index` 和 `plan.steps[i].agent` 选择下游 Worker，不调用 LLM，无需 prompt 模板。

### 4.5 Reflect 节点（监督者反思）

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

### 4.7 SaveExperience 节点（经验记录）

**职责：** 将规划与执行经验写入持久化文档

**逻辑：**

```
1. 读取本次 plan + step_results + reflection_feedback
2. LLM 生成经验摘要（意图→规划→结果→反思）
3. 写入 data/reflection_experience.md
4. 去重：使用字符串包含匹配，检查新经验的 `intent` 和 `steps_desc` 是否已存在于文档中，重复则不追加
```

**经验文档格式：**

每条经验使用统一的 `## 经验` 标题（不带序号），通过追加方式累加：

```markdown
# 任务规划反思经验

## 经验
- **意图**: 分析代码变更并评审测试用例
- **规划**: [code_analyzer, case_reviewer]
- **结果**: step 1: success; step 2: success
- **反思**: 无

## 经验
- **意图**: 分析 payment 模块代码变更
- **规划**: [code_analyzer]
- **结果**: step 1: failed
- **反思**: 需在规划阶段验证参数有效性
```

**说明：**

- 标题统一为 `## 经验`，不带序号。新条目通过字符串追加方式写入，无需重排已有条目，简化文件读写逻辑
- 解析时使用 `split("## 经验\n")` 即可逐条切分
- **规划** 字段以英文逗号分隔 agent 名（如 `code_analyzer, case_reviewer`）
- **结果** 字段汇总每一步的 `step_id` 和 `status`

**当前阶段：** 只记录经验，不在规划时引用。后续可扩展为 planner 读取经验辅助规划。

### 4.8 Synthesize 节点（汇总）

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

### 4.9 Worker 子图（ReAct + 反思）

每个 Worker（code\_analyzer / case\_reviewer）是独立的 ReAct + Reflection 子图，经 wrapper 函数包装后注册为主图节点。wrapper 负责状态转换（`SupervisorState` → `WorkerState`）和结果聚合（`WorkerState.result` → `SupervisorState.outputs`）。

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

**code\_analyzer 子图工具：** `ClaudeCliTool`、`ReadFileTool`、`ListDirTool`、`GrepTool`、`GlobTool`
**case\_reviewer 子图工具：** `ClaudeCliTool`、`TestCaseParserTool`、`BusinessKnowledgeTool`

**子图构建工厂：**

```python
def build_worker_graph(tools: list, llm, llm_with_tools) -> CompiledGraph:
    """构建 ReAct + Reflection Worker 子图

    参数：
    - tools: 子图绑定的工具列表（供 ToolNode 执行）
    - llm: 原生 LLM 实例（供 reflect 节点做质量评估，无需工具绑定）
    - llm_with_tools: 已绑定 tools 的 LLM 实例（供 agent 节点生成响应/工具调用）

    需注入两个 LLM 实例的原因：agent 节点需要 bind_tools 后的 LLM 来生成 tool_calls；
    reflect 节点只做纯文本评估，使用未绑定工具的 LLM 更高效、避免误调用工具。
    """
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
code_analyzer_graph = build_worker_graph(code_analyzer_tools, llm, llm_with_ca_tools)
case_reviewer_graph = build_worker_graph(case_reviewer_tools, llm, llm_with_cr_tools)

# 通过 wrapper 函数注册为主图节点
# wrapper 内部将 SupervisorState.worker_input 传入子图，执行后聚合结果回 outputs
supervisor_graph.add_node("code_analyzer", code_analyzer_wrapper)
supervisor_graph.add_node("case_reviewer", case_reviewer_wrapper)
```

**Worker Wrapper 结果处理：**

- `code_analyzer_wrapper`：直接将 Worker 返回的文本写入 `outputs["code_change_report"]`。
- `case_reviewer_wrapper`：额外执行结构化解析——提取 Markdown 代码围栏内的 JSON，将文本反序列化为 `list[dict]` 后写入 `outputs["review_results"]`；解析失败时回退为 `[{"case_id": "N/A", "verdict": "parse_error"}]`，保证下游始终拿到结构化数据。

**提示词：** `prompts/worker_reflect.md`

## 5. 图编排（Graph Builder）

### 5.1 节点与边

```python
graph = StateGraph(SupervisorState)

# 添加节点
graph.add_node("intent_classifier", intent_classifier_node)
graph.add_node("reply", reply_node)
graph.add_node("planner", planner_node)
graph.add_node("confirm_plan", confirm_plan_node)
graph.add_node("dispatch", dispatch_node)
graph.add_node("code_analyzer", code_analyzer_graph)      # Worker 子图
graph.add_node("case_reviewer", case_reviewer_graph)      # Worker 子图
graph.add_node("reflect", supervisor_reflect_node)
graph.add_node("synthesize", synthesize_node)
graph.add_node("save_experience", save_experience_node)

# 固定边
graph.add_edge("code_analyzer", "dispatch")                # Worker 完成后回 dispatch
graph.add_edge("case_reviewer", "dispatch")                # Worker 完成后回 dispatch
graph.add_edge("synthesize", "save_experience")
graph.add_edge("save_experience", END)
graph.add_edge("reply", END)                               # 无关/模糊请求直接结束

# 条件边 1：intent_classifier 后路由
graph.add_conditional_edges(
    "intent_classifier",
    route_from_classifier,
    {
        "planner": "planner",
        "reply": "reply"
    }
)

# 条件边 2：planner 后路由（首次→confirm_plan，重新规划→confirm_plan）
graph.add_conditional_edges(
    "planner",
    lambda state: "confirm_plan",
    {"confirm_plan": "confirm_plan"}
)

# 条件边 3：confirm_plan 后路由（确认→dispatch，拒绝未超限→planner，拒绝超限→END）
graph.add_conditional_edges(
    "confirm_plan",
    route_from_confirm,
    {
        "dispatch": "dispatch",
        "planner": "planner",
        "end": END
    }
)

# 条件边 4：dispatch 路由到 Worker 或 reflect
graph.add_conditional_edges(
    "dispatch",
    route_from_dispatch,
    {
        "code_analyzer": "code_analyzer",
        "case_reviewer": "case_reviewer",
        "reflect": "reflect"
    }
)

# 条件边 5：reflect 后路由（replan / synthesize）
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
def route_from_classifier(state: SupervisorState) -> Literal["planner", "reply"]:
    """intent_classifier 后路由：相关→planner，无关/模糊→reply"""
    classification = state.get("intent_classification", "")
    if classification == "relevant":
        return "planner"
    return "reply"


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
START → IntentClassifier
    ├─ 判断请求是否与系统能力相关
    ├─ relevant    → 提取结构化意图（intent_analysis）→ 进入 Planner
    ├─ ambiguous   → Reply（引导用户补充信息）→ END
    └─ irrelevant  → Reply（说明系统能力范围）→ END
    ↓
Planner
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
    ├─ 字符串包含去重判断
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
| `read_file`                | `ReadFileTool`          | 读取文件并附带 `cat -n` 行号，仅接受绝对路径；二进制 / 大文件自动保护 | code\_analyzer                 |
| `list_dir`                 | `ListDirTool`           | 树形列出目录，跳过 `.git`/`node_modules`/`__pycache__`/`.venv`，最多 500 条 | code\_analyzer                 |
| `grep`                     | `GrepTool`              | 基于 ripgrep 的正则内容搜索，支持 `include` glob 与 `case_insensitive`，最多 100 条匹配 | code\_analyzer                 |
| `glob`                     | `GlobTool`              | 基于 `rg --files --glob` 的文件名匹配，按 mtime 倒序，最多 200 条 | code\_analyzer                 |

### 6.4 使用方式

**Worker 绑定工具：**

```python
# agents/code_analyzer.py
from test_agents.tools.base import ToolRegistry

_code_analyzer_tools = ToolRegistry.get_tools_by_names(
    ["claude_cli", "read_file", "list_dir", "grep", "glob"]
)

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
├── business_knowledge.py    # BusinessKnowledgeTool(TestAgentTool)
└── fs/                      # 本地文件系统工具子包
    ├── __init__.py          # 占位
    ├── _rg.py               # ripgrep subprocess 共享封装 (run_rg / RgNotInstalled)
    ├── read_file.py         # ReadFileTool(TestAgentTool)
    ├── list_dir.py          # ListDirTool(TestAgentTool)
    ├── grep.py              # GrepTool(TestAgentTool)
    └── glob.py              # GlobTool(TestAgentTool)
```

### 6.7 本地文件系统工具子包（fs/）

为 `code_analyzer` 增加跨仓库源码探索能力，让 Worker 不必绕道 `claude_cli` 即可访问任意绝对路径（如 `/mnt/d/obs_node/`）。完整设计见 `docs/superpowers/specs/2026-05-21-local-fs-tools-design.md`。

**设计要点：**

- **只读**：4 个工具均只读，不提供 `write_file` / `edit` / `shell` 等可破坏性接口
- **仅接受绝对路径**：所有工具内部首先校验 `os.path.isabs(path)`，避免相对路径的歧义与跨 cwd 行为不确定
- **不维护会话级 cwd**：保持工具无状态，与 LangGraph 子图并发 / 重试天然兼容
- **不限制路径范围**：依赖操作系统权限做隔离，而非应用层白名单（避免 TerminalTool 风格的"可绕过白名单"陷阱）
- **subprocess 安全**：grep / glob 使用 `subprocess.run([...])` list 形式，禁用 `shell=True`，并在参数中加 `--` 终止符防止 `pattern` 以 `-` 开头被误解析为 flag
- **统一截断**：每个工具有独立的 `max_results` / `_DEFAULT_LIMIT` 截断阈值（read 2000 行 / list 500 条 / grep 100 条 / glob 200 条），输出末尾附 `⚠️ ... 超过 N, 仅显示前 N 条`
- **LLM 友好错误**：所有错误以 `错误: <中文 + 建议>` 字符串形式返回，由 Worker 反思决定重试或换路径，工具本身不抛异常

**`_rg.py` 共享封装：**

- 定位 `rg` 二进制 (`shutil.which("rg")`)；未找到时抛 `RgNotInstalled` 并带平台安装提示
- 统一 30 秒超时，转换 `subprocess.TimeoutExpired` 为 `TimeoutError`
- `grep` / `glob` 各自捕获 `RgNotInstalled` / `TimeoutError` / 通用 `Exception`，转为 LLM 友好错误

**Worker 绑定：**

- `code_analyzer = [claude_cli, read_file, list_dir, grep, glob]`
- `case_reviewer` 不变（保持 `[claude_cli, parse_test_cases, query_business_knowledge]`）

**Prompt 配套：** `prompts/code_analyzer.md` 已更新，列出 5 个工具能力与一个 6 步工作流模板，指导 LLM 在分析跨仓库代码时先 `list_dir` / `glob` 探索、再 `read_file` / `grep` 查证、最后 `claude_cli` 拉 `git diff`。

## 7. 错误处理

| 场景             | 处理方式                                                 |
| -------------- | ---------------------------------------------------- |
| Intent Classifier 返回非 JSON | 默认 `classification = "ambiguous"`，`intent_analysis = None`，reply_node 生成引导消息 |
| Intent Classifier LLM 调用失败 | 捕获异常，默认 `classification = "ambiguous"`，`intent_analysis = None`，不中断流程 |
| Intent Classifier extracted 解析失败 | `classification` 保持不变，`intent_analysis = None`，planner 回退到自行理解 user_request |
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
| fs 工具传入非绝对路径 | 返回 `错误: ... 必须是绝对路径，收到: ...`，由 Worker 反思决定重试 |
| fs 工具路径不存在 / 类型不符 | 返回 `错误: 文件不存在 / 路径是目录, 请用 list_dir / ...`，引导 LLM 换工具或换路径 |
| `read_file` 读到二进制 / 超大文件 | 二进制返回拒绝错误；> 5 MB 文件强制截断到前 2000 行并附 `⚠️ 文件过大` |
| `grep` / `glob` 未安装 ripgrep | 返回 `错误: 未找到 ripgrep。请安装：apt install ripgrep / brew install ripgrep / scoop install ripgrep` |
| `grep` / `glob` ripgrep 超时（默认 30s） | 返回 `错误: ripgrep 超时（30s），考虑缩小 path 或使用更精确的 include 过滤` |
| `grep` 无匹配 / `glob` 无文件 | rg 退出码 1 → 返回 `未找到匹配` / `未找到匹配文件`（视为正常结果，非错误） |
| `list_dir` 遇符号链接到目录 | 显示为 `name -> (symlink)`，不递归，避免环回

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

**系统依赖：ripgrep**

`grep` / `glob` 工具基于 ripgrep。按平台安装：

- WSL/Ubuntu/Debian：`sudo apt install ripgrep`
- macOS：`brew install ripgrep`
- Windows (scoop)：`scoop install ripgrep`
- Windows (winget)：`winget install BurntSushi.ripgrep.MSVC`

未安装时 `grep` / `glob` 会返回带平台命令提示的友好错误，不影响 `read_file` / `list_dir` 与其他工具的正常使用。

**可观测性（observability）零新增依赖：** 基于 Python 标准库 `logging` + `contextvars` + LangGraph 自带 `langchain_core.callbacks.BaseCallbackHandler` 实现，requirements.txt 不变。详见 §13。

## 11. 与之前版本的关键差异

| 维度        | v1（Supervisor 模式） | v2（Plan-and-Solve）      | v3（Plan-and-Solve + Reflection）    |
| --------- | ----------------- | ----------------------- | ---------------------------------- |
| 用户输入      | CLI 结构化参数         | 自然语言 user\_request      | 自然语言 user\_request                 |
| 监督者范式     | 硬编码 if-else 路由    | Planner + Executor      | Planner + Dispatch + Reflect       |
| 监督者反思     | 无                 | 无                       | 全步骤完成后 LLM 评估，可 replan             |
| Worker 范式 | 简单执行              | 简单执行                    | ReAct + 反思子图                       |
| Worker 反思 | 无                 | 无                       | LLM 评估结果质量，可重试                     |
| 子图集成      | 无                 | 无                       | Worker 子图经 wrapper 包装后作为主图节点注册  |
| 经验记录      | 无                 | 无                       | 规划与执行经验持久记录                        |
| 直接调用      | 不支持               | 不支持                     | main.py 中直接调 worker\_app           |
| 用户确认      | 无                 | 有（interrupt）            | 有（interrupt）                       |
| 参数来源      | 用户直接提供            | Planner 从自然语言提取         | Planner 从自然语言提取                    |
| 步骤间数据传递   | 隐式                | 显式 input\_mapping + ${} | 显式 input\_mapping + ${outputs.xxx} |
| 结果汇聚      | 固定字段（硬编码）         | 固定字段（硬编码）               | 通用 `outputs` 字典（配置驱动）              |
| code\_analyzer 工具 | 仅 `claude_cli` | 仅 `claude_cli` | `claude_cli` + 本地 fs 工具（`read_file` / `list_dir` / `grep` / `glob`，后两者基于 ripgrep），支持跨仓库源码探索 |
| 可观测性 | 无 | 无 | 自建 logging + LangGraph callback 拦截，零新增依赖，详见 §13 |

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
| 去重方式 | 字符串包含匹配（检查 intent 与 steps_desc 是否已存在）              |
| 存储位置 | data/reflection\_experience.md |
| 当前使用 | 只记录，不引用                        |
| 未来扩展 | planner 读取经验辅助规划               |


## 13. 可观测性（Observability）

为 Test Agents v3 建立**自建、内网友好、零新增依赖**的可观测体系。完整设计与所有 finding 落点见 `docs/superpowers/specs/2026-05-22-observability-design.md`（取代已搁置的 `2026-05-20-langgraph-tracing-design.md`）。

### 13.1 目标

1. **定位问题** —— worker 报错、reflect 拒绝、计划反复 replan 时能快速追到根因
2. **性能/成本分析** —— 每个 LLM 调用耗时与 token、claude_cli 调用时长、worker 总耗时
3. **行为可解释性** —— 完整复盘 supervisor 的决策、worker 的工具调用序列

### 13.2 约束

- 部署在内网，**禁止任何数据出网**（排除 LangSmith 等 SaaS）
- **不引入新基础设施**（排除自托管 LangFuse、Postgres、Prometheus）
- 不引入新 Python 第三方依赖，全部基于标准库 + LangGraph 自带 callback

### 13.3 总体架构

```
main.py: run_test_agents(user_request)
  ├─ setup_logging()                        ← 模块导入时一次
  └─ return _with_observability(target_func, user_request, kind)
       ├─ new_trace(user_request)           ← 生成 trace_id，存入 ContextVar
       ├─ result = target_func(make_run_config())
       │            （config 携带 ObservabilityCallback）
       ├─ flush_metrics(status, final_answer_length)  ← 追加 metrics.jsonl
       └─ close_trace_writer()              ← 关闭 per-trace 文件 + 清理跨事件 dict
              ↓
   LangGraph 引擎执行（自动触发 callback，业务代码改动 0 处）
              ↓
   ObservabilityCallback（BaseCallbackHandler 子类）
     ├─ on_chain_start/end/error   → node.enter / node.exit + replan 推断
     ├─ on_chat_model_start/end    → llm.call + tokens（主路径）
     ├─ on_llm_start/end           → llm.call（兼容 completion 模型）
     └─ on_tool_start/end/error    → tool.call + duration_ms
              ↓
   JsonlMultiHandler
     ├─ TimedRotatingFileHandler → logs/app-YYYY-MM-DD.jsonl
     └─ per-trace writer (LRU 64) → logs/traces/<trace_id>.jsonl
              ↓
   trace 结束：MetricsCollector.flush(trace_id) → logs/metrics.jsonl 追加一行
```

### 13.4 业务代码改动量

| 文件 | 改动 |
|---|---|
| `test_agents/main.py` | 模块导入时调用 `setup_logging()`；抽出 `_with_observability(target_func, user_request, kind)` 包装函数，`_run_supervisor` 与 `_run_direct_worker` 都通过它调用，保证两条路径都有 trace_id |
| `test_agents/config.py` | 新增 6 个环境变量：`TEST_AGENTS_LOG_LEVEL`（默认 `INFO`，含 `OFF` 总开关）、`TEST_AGENTS_LOG_DIR`（默认 `logs/`）、`TEST_AGENTS_LOG_TRACE_FILES`（默认 `true`）、`TEST_AGENTS_LOG_TRACES_KEEP`（默认 `1000`）、`TEST_AGENTS_LOG_RETAIN_DAYS`（默认 `30`）、`TEST_AGENTS_LOG_TRACE_HANDLES`（默认 `64`） |
| `test_agents/agents/supervisor.py` / `worker_base.py` | **0 处改动**。callback 自动拦截每个节点和 `llm.invoke` |
| `test_agents/tools/base.py` 及全部子类 | **0 处改动**。callback 自动拦截每次工具调用 |
| `test_agents/graph/builder.py` | **0 处改动**。callback 通过 `app.invoke(state, config={"callbacks": [...]} )` 注入，编译时不绑定 |

### 13.5 trace_id / span_id 传递

- **`trace_id`**：`_with_observability` 入口 `new_trace(user_request)` 生成（格式 `tr_<8 字符 hex>`），存入 `trace_id_var: ContextVar[str]`。confirm_plan interrupt 跨多次 `app.invoke` 时，`MetricsCollector` 是全局 dict，状态正确累积。
- **`span_id`**：由 `ObservabilityCallback._spans: dict[UUID, str]` 在 enter 事件时生成。`parent_span_id` 通过 `parent_run_id` 查同一个 dict。不使用 `ContextVar` 传递 span_id。
- **dict 生命周期**：所有出口（on_chain_end/error、on_chat_model_end、on_llm_end/error、on_tool_end/error）都 `pop(run_id, None)`；`close_trace_writer()` 额外清 `_last_node_per_trace[trace_id]`。
- 当前实现**不支持多线程并发执行**、**不支持嵌套 `new_trace`**。

### 13.6 日志级别与总开关

| 级别 | 节点 enter/exit | LLM 调用 | 工具调用 | state 快照 |
|---|---|---|---|---|
| `OFF` | `setup_logging` 不注册 Handler，`make_run_config()` 返回 `{"callbacks": [], ...}`。整套观测体系彻底失活 | — | — | — |
| `INFO`（默认） | ✓ + 摘要 | ✓ + tokens + 耗时 | ✓ + 摘要 + 耗时 | ✗ |
| `DEBUG` | ✓ + 摘要 | ✓ + prompt/response 全文（2KB） | ✓ + input/output 全文（2KB） | ✗ |
| `TRACE`（自定义=5） | ✓ + state 快照 | ✓ + state 快照 | 同 DEBUG | ✓ |

### 13.7 输出文件

```
logs/
  app-2026-05-22.jsonl       # 主日志（按天滚动，默认保留 30 天）
  metrics.jsonl              # 每次执行追加一行 summary（不滚动）
  traces/
    tr_8a3f2c1d.jsonl        # per-trace 完整事件序列
    ...
```

清理：

- 主日志：`TimedRotatingFileHandler(when='midnight', backupCount=TEST_AGENTS_LOG_RETAIN_DAYS)`
- per-trace 文件：`setup_logging()` 启动时按 mtime 降序保留最新 `TEST_AGENTS_LOG_TRACES_KEEP` 份
- per-trace 句柄：LRU 容量 `TEST_AGENTS_LOG_TRACE_HANDLES`
- `metrics.jsonl`：不自动清理

### 13.8 日志行格式（JSON Lines）

```json
{
  "ts": "2026-05-22T10:30:45.123Z",
  "level": "INFO",
  "trace_id": "tr_8a3f2c1d",
  "span_id": "sp_b21c4a90",
  "parent_span_id": "sp_a1f0e234",
  "event": "node.enter|node.exit|llm.call|tool.call|error|callback.failed",
  "node": "planner", "tool": "claude_cli",
  "duration_ms": 1234, "status": "ok|error",
  "model": "gpt-4o", "tokens": {"prompt": 123, "completion": 45, "total": 168},
  "input_summary": "...", "output_summary": "...",
  "error": {"type": "TimeoutError", "message": "...", "traceback": "..."}
}
```

- `input_summary` / `output_summary`：截断到前 200 字符（INFO 起）
- `input_full` / `output_full`：截断到 2000 字符（DEBUG/TRACE 才出现）
- 不可序列化对象 → `str(obj)` + `___unserializable___: true` 标记
- 序列化策略按事件源类型分发（dict / list[BaseMessage] / str 各自处理）

### 13.9 metrics.jsonl 行格式

```json
{
  "trace_id": "tr_8a3f2c1d",
  "ts_start": "...", "ts_end": "...", "duration_ms": 27333,
  "user_request": "分析订单模块代码变更",
  "status": "ok|error|aborted",
  "node_count": 7, "llm_call_count": 5, "tool_call_count": 12,
  "replan_count": 0, "final_answer_length": 1024,
  "error": null
}
```

**status 三态**：`ok` 流程完成并有 final_answer；`error` 异常抛出（含 KeyboardInterrupt）；`aborted` 流程完成但无 final_answer（confirm_retry 超限）。

### 13.10 错误处理原则

**可观测系统的故障绝不允许影响业务执行。** 所有 callback 方法包 try/except、写一条 `event: callback.failed` 后吞掉；JsonlMultiHandler 写盘失败降级 `sys.__stderr__`；MetricsCollector flush 失败静默；trace_id 未 set 时主日志正常写、不写 per-trace 文件。详细错误矩阵见独立 spec §12。

### 13.11 与 §7 错误处理的关系

§7 表只描述**业务层**错误，不重复 observability 错误处理（独立 spec §12 全覆盖）。一条规则：**observability 自身的任何故障对业务都是不可感知的**，所以不会出现在 §7 的"用户感知"列。

### 13.12 非目标（YAGNI）

- 不做 Prometheus / OpenTelemetry 指标导出
- 不做实时 Web UI（如需可视化未来再加 LangFuse 自托管）
- 不做日志加密、不做脱敏
- 不做集中式日志收集（ELK / Loki）
- 不做告警 / 通知机制
- 不做异步 QueueHandler
- 不支持多线程并发执行
- 不在 `build_graph` 默认绑定 callback
- 不支持嵌套 `new_trace`
