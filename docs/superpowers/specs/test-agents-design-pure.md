# 测试智能体群（Test Agents）设计文档

## 1. 项目概述

基于 LangGraph 的分层多智能体测试系统。用户以自然语言描述需求，监督者自动规划执行步骤，按序调度 Worker Agent 完成任务，全步骤完成后反思评估，经验持久记录。

**架构范式：**
- **监督者**：Plan-and-Solve + 反思（全步骤完成后 LLM 评估，不完整则重新规划）
- **执行者**：ReAct + 反思（LLM 评估结果质量，不通过则重试）
- Worker 子图通过包装函数集成到主图，负责状态转换及结果聚合
- 支持监督者调度和直接调用 Worker 两种模式

## 2. 架构设计

### 2.1 模式选型

采用 **Intent Classification + Plan-and-Solve + Reflection** 分层架构：
## 架构层次详解
### 第一层：Supervisor 主图层
这是系统的核心控制层，负责整体任务规划和调度：
核心节点：
- Intent Classifier（意图分类器） ：判断用户请求是否与系统能力相关，提取结构化意图信息
- Planner（规划器） ：理解用户意图，提取参数，生成有序执行计划
- ConfirmPlan（计划确认） ：展示计划给用户确认，支持 human-in-the-loop
- Dispatch（调度器） ：按计划步骤路由到对应 Worker 子图
- Reflect（监督者反思） ：全部步骤执行完后，评估整体结果是否完整正确
- Synthesize（汇总器） ：遍历所有 Worker 结果，生成最终输出
- SaveExperience（经验记录） ：将规划与执行经验写入持久化文档
- Reply（友好回复） ：对无关或模糊请求生成友好回复，直接结束流程

### 第二层：Worker 子图层
这是实际执行具体任务的层，每个 Worker 都是独立的 ReAct + Reflection 子图：
Worker 类型：
- Code Analyzer（代码分析智能体） ：分析代码变更，绑定工具包括 ClaudeCliTool、ReadFileTool、ListDirTool、GrepTool、GlobTool
- Case Reviewer（用例评审智能体） ：评审测试用例，绑定工具包括 ClaudeCliTool、TestCaseParserTool、BusinessKnowledgeTool
子图内部结构：
- Agent 节点 ：LLM 绑定工具，处理消息，决定调用工具或直接回答
- Tools 节点 ：执行工具调用
- Reflect 节点 ：LLM 评估结果质量，支持重试机制

### 第三层：Outputs 汇聚层
这是 Worker 结果的统一汇聚层，实现配置驱动的结果管理：
核心机制：
- 动态扩展 ：支持新增 Agent 的结果自动汇聚
- Key-Value 存储 ：所有 Worker 产出统一写入 outputs[key]
- 聚合规则 ：同 output_key 的多份结果自动拼接，用标题分隔
- 跨步骤引用 ：下游步骤通过 ${outputs.xxx} 语法引用上游结果
典型产出：
- code_change_report ：代码变更报告
- review_results ：测试用例评审结果
- 支持动态扩展的其他产出字段

### 第四层：Tool 工具层
这是系统的基础设施层，提供各种工具能力：
工具分类：
- AI 分析工具 ：ClaudeCliTool，调用 Claude CLI 执行分析任务
- 测试用例工具 ：TestCaseParserTool，统一解析 JSON/Text 用例输入
- 业务知识工具 ：BusinessKnowledgeTool，按模块名查询本地业务知识
- 文件系统工具 ：ReadFileTool（读取文件）、ListDirTool（列出目录）、GrepTool（内容搜索）、GlobTool（文件名匹配）

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

**调用层次：** Planner → Dispatch → Worker(ReAct子图) → Tool

**双重调用模式：**

| 调用模式 | 实现方式 | 适用场景 |
| --- | --- | --- |
| 监督者→Worker | Worker 子图经包装后作为主图节点，dispatch 路由 | 复杂任务需要拆解时 |
| 直接调用 Worker | 直接调用 worker_app.invoke() | 简单任务，用户明确指定某 Agent 时 |

### 2.2 目录结构

```
test_agents/
├── agents/                      # 智能体定义
│   ├── supervisor.py            # 监督者：planner + dispatch + reflect + synthesize + save_experience
│   ├── worker_base.py           # Worker 子图构建工厂（ReAct + 反思）
│   ├── code_analyzer.py         # 代码分析智能体
│   └── case_reviewer.py         # 用例评审智能体
├── observability/               # 可观测性子包
│   ├── context.py               # 上下文管理
│   ├── logger.py                # 日志配置
│   ├── filters.py               # 日志过滤器
│   ├── handlers.py              # 日志处理器
│   ├── callback.py              # LangGraph 回调
│   └── metrics.py               # 指标收集
├── tools/                       # 公共工具层
│   ├── base.py                  # 工具基类 + 自动注册表
│   ├── claude_cli.py
│   ├── test_case_parser.py
│   ├── business_knowledge.py
│   └── fs/                      # 本地文件系统工具子包
│       ├── read_file.py
│       ├── list_dir.py
│       ├── grep.py
│       └── glob.py
├── graph/                       # 图编排
│   ├── state.py                 # 状态定义
│   └── builder.py               # 主图构建与编译
├── prompts/                     # 提示词模板
│   ├── intent_classifier.md
│   ├── reply.md
│   ├── supervisor.md
│   ├── worker_reflect.md
│   ├── code_analyzer.md
│   └── case_reviewer.md
├── config.py                    # 配置
├── main.py                      # 入口
├── data/                        # 运行时数据
│   └── reflection_experience.md # 经验记录文档
└── logs/                        # 可观测性输出
    ├── app-YYYY-MM-DD.jsonl     # 主日志
    ├── metrics.jsonl            # 指标汇总
    └── traces/<trace_id>.jsonl  # 每个 trace 单独文件
```

## 3. 状态设计

### 3.1 主图状态（SupervisorState）

| 类别 | 字段 | 说明 |
| --- | --- | --- |
| 用户输入 | user_request | 自然语言需求 |
| 规划参数 | targets | 分析目标列表（支持多模块） |
| 规划参数 | test_cases | 测试用例 |
| 规划参数 | business_knowledge | 业务知识 |
| Plan-and-Solve | plan | LLM 生成的执行计划 |
| Plan-and-Solve | current_step_index | 当前执行步骤索引 |
| Plan-and-Solve | step_results | 各步骤结果聚合 |
| 反思相关 | needs_replan | 是否需要重新规划 |
| 反思相关 | reflection_feedback | 反思反馈内容 |
| 反思相关 | max_plan_iterations | 最大规划迭代次数 |
| 反思相关 | plan_iterations | 当前已规划次数 |
| 确认相关 | confirm_retry_count | 确认重试次数 |
| 确认相关 | max_confirm_retries | 最大确认重试次数 |
| 结果汇聚 | outputs | 所有 Worker 产出统一汇聚 |
| 中间传递 | worker_input | Worker 子图输入 |
| 最终输出 | final_answer | 最终回答 |
| 意图分类 | intent_classification | 分类结果（relevant/ambiguous/irrelevant） |
| 意图分类 | intent_reason | 分类理由 |
| 意图分类 | intent_analysis | 结构化意图提取 |
| 消息历史 | messages | 对话消息 |

### 3.2 Worker 子图状态（WorkerState）

| 类别 | 字段 | 说明 |
| --- | --- | --- |
| 任务输入 | task | 当前步骤的子任务描述 |
| 任务输入 | messages | 对话消息 |
| 反思相关 | error | 是否有错误 |
| 反思相关 | reflection_count | 反思次数 |
| 反思相关 | max_reflections | 最大反思次数 |
| 输出 | result | 执行结果 |
| 输出 | output_key | 结果写入主图的 key |

### 3.3 状态映射机制

**主图 → 子图：** dispatch 节点构建 worker_input，包含任务描述、消息、初始状态等

**子图 → 主图：** wrapper 从子图结果提取数据，写入主图 outputs，并更新步骤状态

### 3.4 多模块聚合规则

- 同 output_key 的多份结果自动拼接，用标题分隔
- 不同 output_key 的结果隔离存储
- 下游步骤通过 input_mapping 引用上游结果

### 3.5 input_mapping 规则

| 形式 | 示例 | 含义 |
| --- | --- | --- |
| 字符串常量 | "payment" | 直接传给 agent |
| Outputs 引用 | "${outputs.code_change_report}" | 从 outputs 字典中取值 |
| 多 key 拼接 | "${outputs.report_a}\n${outputs.report_b}" | 拼接多个 outputs 值 |

## 4. 节点设计

### 4.1 Intent Classifier 节点

**职责：** 判断用户请求是否与系统能力相关，并提取结构化意图信息

**三分类规则：**

| 分类 | 含义 | 示例 |
| --- | --- | --- |
| relevant | 明确涉及代码分析或测试用例评审 | "分析 payment 模块代码变更" |
| ambiguous | 提到相关关键词但不明确具体需求 | "帮我看看测试" |
| irrelevant | 完全无关 | "hello"、"今天天气怎样" |

**降级策略：** 遇到异常时默认分类为 ambiguous，不中断流程

### 4.2 Reply 节点

**职责：** 对无关或模糊请求生成友好回复，直接结束流程

**回复策略：**
- irrelevant：礼貌说明系统能力范围，举例可用请求格式
- ambiguous：说明理解到用户可能有相关需求，但信息不足，请补充具体信息

### 4.3 Planner 节点
**职责：**
1. 理解用户意图
2. 提取参数（targets、test_cases、business_knowledge 等）
3. 生成有序执行计划

**可用 Agent 能力：**
| Agent | 能力 | 必需入参 | 产出字段 |
| --- | --- | --- | --- |
| code_analyzer | 分析代码变更 | module_name, source_commit, target_commit | code_change_report |
| case_reviewer | 评审测试用例 | code_change_report, test_cases, business_knowledge | review_results |

### 4.4 ConfirmPlan 节点
**职责：** 展示计划给用户确认
**流程：**
- 用户确认 → 继续执行
- 用户拒绝 → 用户提供反馈建议，回到 planner 重新规划
- 最多重试 3 次，仍未确认则取消任务

### 4.5 Dispatch 节点

**职责：** 按计划步骤路由到对应 Worker 子图

**路由逻辑：**
1. 计划未确认 → 返回等待
2. 所有步骤完成 → 路由到 reflect
3. 读取当前步骤 → 构建 Worker 输入 → 路由到对应 Worker

### 4.6 Reflect 节点（监督者反思）

**职责：** 全部步骤执行完后，评估整体结果是否完整正确

**逻辑：**
1. LLM 评估所有步骤结果是否完整解决用户需求
2. COMPLETE → 进入 synthesize
3. REPLAN → 回到 planner（受 max_plan_iterations 限制）
4. 记录规划与执行经验

### 4.7 SaveExperience 节点（经验记录）

**职责：** 将规划与执行经验写入持久化文档

**经验文档格式：**
```markdown
## 经验
- **意图**: 分析代码变更并评审测试用例
- **规划**: [code_analyzer, case_reviewer]
- **结果**: step 1: success; step 2: success
- **反思**: 无
```

### 4.8 Synthesize 节点（汇总）

**职责：** 遍历 outputs 汇总所有 Worker 结果，生成最终输出

**逻辑：**
1. 读取 outputs，按 key 分组整理
2. 对每个 output_key，提取内容摘要
3. 综合回答用户请求
4. 输出 final_answer

### 4.9 Worker 子图（ReAct + 反思）

**子图内部结构：**
```
START → agent → (有工具调用?) → tools → agent (循环)
                ↓ (无工具调用)
                reflect → (质量不通过?) → agent (重试)
                ↓ (质量通过或超次)
                END → 返回 result
```

**反思逻辑：**
1. 检查 max_reflections，如果为 0 → 跳过反思
2. LLM 评估结果质量
3. 通过 → 结束子图
4. 不通过 → 反馈写回，重试（受 max_reflections 控制）

**工具绑定：**
- code_analyzer：ClaudeCliTool、ReadFileTool、ListDirTool、GrepTool、GlobTool
- case_reviewer：ClaudeCliTool、TestCaseParserTool、BusinessKnowledgeTool

## 5. 图编排

### 5.1 完整执行流程

```
用户输入 user_request（自然语言）
    ↓
START → IntentClassifier
    ├─ relevant    → 提取结构化意图 → Planner
    ├─ ambiguous   → Reply → END
    └─ irrelevant  → Reply → END
    ↓
Planner → 生成 ExecutionPlan
    ↓
ConfirmPlan（等待用户确认）
    ├─ 用户确认 → plan.confirmed = True
    ↓
Dispatch
    ↓ 读取步骤 → 对应 Worker 子图
    ↓
CodeAnalyzer / CaseReviewer（ReAct 子图）
    ├─ agent: LLM + 工具
    ├─ tools: 执行工具调用
    ├─ reflect: 评估结果质量
    └─ 返回 result
    ↓
Dispatch（循环直到所有步骤完成）
    ↓
Reflect（监督者反思）
    ├─ COMPLETE → synthesize
    └─ REPLAN → planner
    ↓
Synthesize → 生成 final_answer
    ↓
SaveExperience → 记录经验
    ↓
END → 输出 final_answer
```

### 5.2 条件路由规则

| 节点 | 路由条件 | 目标节点 |
| --- | --- | --- |
| IntentClassifier | classification == "relevant" | planner |
| IntentClassifier | 其他 | reply |
| ConfirmPlan | plan.confirmed == True | dispatch |
| ConfirmPlan | 未确认且未超限 | planner |
| ConfirmPlan | 未确认且超限 | END |
| Dispatch | 还有步骤 | 对应 Worker |
| Dispatch | 所有步骤完成 | reflect |
| Reflect | needs_replan 且未超限 | planner |
| Reflect | 其他 | synthesize |

### 5.3 直接调用模式

简单请求可绕过监督者，直接调用单个 Worker 子图。判断依据：
- 关键词匹配（如"分析代码"→code_analyzer，"评审用例"→case_reviewer）
- 结果直接写入统一的 outputs 结构

## 6. 工具层设计

### 6.1 架构模式

采用 **TestAgentTool 基类 + ToolRegistry 自动注册表** 模式：

```
TestAgentTool子类 ──→ ToolRegistry ──→ bind_tools / render_all()
```

工具直接继承 LangChain BaseTool，无需额外适配层。

### 6.2 核心组件

**TestAgentTool（工具基类）：**
- 所有项目工具统一继承
- 子类定义时自动注册到 ToolRegistry
- 支持懒实例化机制

**ToolRegistry（自动注册表）：**
- 统一管理所有工具实例
- 提供查询和渲染接口
- 首次调用时才实例化，避免 import 时的副作用

### 6.3 工具列表

| 工具 | 描述 | 绑定 Worker |
| --- | --- | --- |
| claude_cli | 调用 Claude CLI 执行分析任务 | code_analyzer, case_reviewer |
| parse_test_cases | 统一解析 JSON/Text 用例输入 | case_reviewer |
| query_business_knowledge | 按模块名查询本地业务知识 | case_reviewer |
| read_file | 读取文件并附带行号 | code_analyzer |
| list_dir | 树形列出目录 | code_analyzer |
| grep | 基于 ripgrep 的正则内容搜索 | code_analyzer |
| glob | 文件名匹配 | code_analyzer |

### 6.4 新增工具流程

1. 在 tools/ 下新建 TestAgentTool 子类，自动注册到 ToolRegistry
2. 在对应 Worker 的工具列表中添加工具名
3. Planner prompt 自动包含新工具描述

### 6.5 本地文件系统工具设计要点

- **只读**：所有工具均只读，不提供写操作
- **仅接受绝对路径**：避免相对路径的歧义
- **无状态**：保持工具无状态，与并发/重试兼容
- **安全执行**：禁用 shell=True，防止参数注入
- **统一截断**：每个工具有独立的截断阈值
- **LLM 友好错误**：错误以自然语言形式返回

## 7. 错误处理

| 场景 | 处理方式 |
| --- | --- |
| Intent Classifier 返回非 JSON | 默认 classification = "ambiguous" |
| Intent Classifier LLM 调用失败 | 捕获异常，默认 classification = "ambiguous" |
| Planner 无法理解意图 | 返回错误提示要求用户补充说明 |
| Planner 输出格式异常 | 重试一次，仍失败则终止 |
| 用户拒绝计划 | 返回修改意图或终止 |
| Worker 步骤失败 | 记录结果，继续下一步 |
| Worker 反思超次 | 强制通过 |
| 监督者反思 REPLAN | 回 planner 重规划，超限后强制 synthesize |
| 工具异常 | 捕获，返回错误消息给 agent 重试 |
| 经验写入失败 | 静默跳过，不影响主流程 |
| fs 工具传入非绝对路径 | 返回错误，由 Worker 反思决定重试 |
| read_file 读到二进制/超大文件 | 返回拒绝错误或强制截断 |
| grep/glob 未安装 ripgrep | 返回友好错误提示 |

## 8. 通用 outputs 机制

### 8.1 设计动机

将结果汇聚从硬编码转为配置驱动，支持灵活扩展 Agent。

### 8.2 核心规则

1. **写入规则**：Worker 执行完成后，将结果写入 outputs[step.output_key]
2. **聚合规则**：同 output_key 的多次写入自动拼接
3. **读取规则**：下游 Worker 通过 input_mapping 引用

### 8.3 示例：多 Agent 协作

```
用户：分析 payment 和 order 模块的代码变更，生成测试计划并评审

Planner 生成 plan：
  Step 1: code_analyzer (payment) → outputs["report_payment"]
  Step 2: code_analyzer (order)   → outputs["report_order"]
  Step 3: test_plan_generator     → outputs["test_plan"]
       input: "${outputs.report_payment}\n${outputs.report_order}"
  Step 4: case_reviewer           → outputs["review_results"]
       input: "${outputs.test_plan}"

Synthesize 遍历 outputs 生成 final_answer
```

## 9. 扩展性

### 9.1 增加 Worker

无需修改 SupervisorState 定义，只需三步：
1. 新增 agent 文件，实现 Worker wrapper，指定 output_key
2. 在 dispatch 路由中注册新 agent
3. 在 Planner prompt 中补充能力描述

### 9.2 同类型 Worker 多实例执行

- **聚合模式**：所有实例共用同一 output_key，结果自动拼接
- **隔离模式**：为每个实例分配不同 output_key，下游按需引用

### 9.3 其他扩展

- **替换模型**：通过 config.py 统一配置
- **新增 Tool**：在 tools/ 下新增，在对应 Worker 中绑定
- **经验引用**：未来可扩展 planner 读取经验辅助规划
- **条件分支**：未来可在 ExecutionPlan 中增加条件步骤

## 10. 依赖

| 依赖类型 | 说明 |
| --- | --- |
| Python 依赖 | langgraph、langchain-core、langchain-openai、pydantic |
| CLI 工具 | Claude CLI（需单独安装配置） |
| 系统依赖 | ripgrep（grep/glob 工具需要） |

## 11. 版本演进

| 维度 | v1 | v2 | v3 |
| --- | --- | --- | --- |
| 用户输入 | CLI 结构化参数 | 自然语言 | 自然语言 |
| 监督者范式 | 硬编码路由 | Planner + Executor | Planner + Dispatch + Reflect |
| 监督者反思 | 无 | 无 | 全步骤完成后 LLM 评估 |
| Worker 范式 | 简单执行 | 简单执行 | ReAct + 反思子图 |
| Worker 反思 | 无 | 无 | LLM 评估结果质量 |
| 子图集成 | 无 | 无 | Worker 子图包装后注册 |
| 经验记录 | 无 | 无 | 规划与执行经验持久记录 |
| 直接调用 | 不支持 | 不支持 | 支持 |
| 用户确认 | 无 | 有 | 有 |
| 参数来源 | 用户直接提供 | Planner 提取 | Planner 提取 |
| 结果汇聚 | 固定字段 | 固定字段 | 通用 outputs 字典 |
| code_analyzer 工具 | 仅 claude_cli | 仅 claude_cli | claude_cli + 本地 fs 工具 |
| 可观测性 | 无 | 无 | 自建 logging + callback |

## 12. 反思与经验机制

### 12.1 监督者反思（层级间反思）

| 项目 | 说明 |
| --- | --- |
| 触发条件 | 所有步骤执行完成后 |
| 评估方式 | LLM 评估 plan + step_results 是否完整解决需求 |
| 通过处理 | 进入 synthesize |
| 不通过处理 | 回 planner 重规划 |
| 安全限制 | max_plan_iterations 防止死循环 |

### 12.2 Worker 反思（层级内反思）

| 项目 | 说明 |
| --- | --- |
| 触发条件 | agent 执行完（无工具调用后） |
| 评估方式 | LLM 评估结果质量 |
| 通过处理 | 子图结束 |
| 不通过处理 | 反馈写回，agent 重试 |
| 安全限制 | max_reflections 控制重试次数 |

### 12.3 经验记录

| 项目 | 说明 |
| --- | --- |
| 触发条件 | 每次 synthesize 后 |
| 记录内容 | 意图、规划、结果、反思反馈 |
| 去重方式 | 字符串包含匹配 |
| 存储位置 | data/reflection_experience.md |
| 当前使用 | 只记录，不引用 |
| 未来扩展 | planner 读取经验辅助规划 |

## 13. 可观测性

### 13.1 目标

1. **定位问题**：快速追踪 worker 报错、reflect 拒绝、计划反复 replan 的根因
2. **性能/成本分析**：每个 LLM 调用耗时与 token、工具调用时长
3. **行为可解释性**：完整复盘 supervisor 的决策、worker 的工具调用序列

### 13.2 约束

- 部署在内网，禁止任何数据出网
- 不引入新基础设施
- 不引入新 Python 第三方依赖

### 13.3 总体架构

```
main.py: run_test_agents(user_request)
  ├─ setup_logging()
  └─ _with_observability(target_func, user_request, kind)
       ├─ new_trace(user_request) → 生成 trace_id
       ├─ target_func(make_run_config())
       ├─ flush_metrics() → 追加 metrics.jsonl
       └─ close_trace_writer()
              ↓
   LangGraph 引擎执行（自动触发 callback）
              ↓
   ObservabilityCallback
     ├─ on_chain_start/end/error   → node.enter / node.exit
     ├─ on_chat_model_start/end    → llm.call
     └─ on_tool_start/end/error    → tool.call
              ↓
   JsonlMultiHandler
     ├─ 主日志 → logs/app-YYYY-MM-DD.jsonl
     └─ per-trace writer → logs/traces/<trace_id>.jsonl
              ↓
   MetricsCollector.flush() → logs/metrics.jsonl
```

### 13.4 输出文件

```
logs/
  app-2026-05-22.jsonl       # 主日志（按天滚动）
  metrics.jsonl              # 每次执行追加一行 summary
  traces/
    tr_8a3f2c1d.jsonl        # per-trace 完整事件序列
```

### 13.5 日志级别

| 级别 | 节点事件 | LLM 调用 | 工具调用 | state 快照 |
| --- | --- | --- | --- | --- |
| OFF | 不注册 Handler，观测体系失活 | — | — | — |
| INFO | ✓ + 摘要 | ✓ + tokens + 耗时 | ✓ + 摘要 + 耗时 | ✗ |
| DEBUG | ✓ + 摘要 | ✓ + prompt/response 全文 | ✓ + input/output 全文 | ✗ |
| TRACE | ✓ + state 快照 | ✓ + state 快照 | 同 DEBUG | ✓ |

### 13.6 错误处理原则

可观测系统的故障绝不允许影响业务执行：
- 所有 callback 方法包 try/except
- 写盘失败降级到 stderr
- MetricsCollector flush 失败静默
- trace_id 未设置时正常写主日志

### 13.7 非目标（YAGNI）

- 不做 Prometheus / OpenTelemetry 指标导出
- 不做实时 Web UI
- 不做日志加密、脱敏
- 不做集中式日志收集
- 不做告警 / 通知机制
- 不支持多线程并发执行