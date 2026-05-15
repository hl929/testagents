---
title: 测试智能体群（Test Agents）设计文档
description: 基于 LangGraph Supervisor 模式的多智能体测试系统，包含测试经理、代码分析智能体、用例评审智能体，支持 Claude CLI Skill 调用
date: 2026-05-15
---

# 测试智能体群（Test Agents）设计文档

## 1. 项目概述

基于 LangGraph Supervisor 模式构建的多智能体测试系统。核心目标：接收代码变更信息（模块名、commit 范围）和测试用例，自动分析代码变更、评审测试用例质量，输出评审报告。

系统以 **Claude CLI Skill** 的形式交付，安装后可通过 `claude /test_agents` 直接调用。

## 2. 架构设计

### 2.1 模式选型

采用 **LangGraph Supervisor（监管者模式）**：

- 一个中心 **测试经理（Supervisor）** 智能体负责任务调度
- 两个 Worker 智能体：**代码分析** 和 **用例评审**
- Supervisor 根据当前 `state` 决定下一步调用哪个 Worker
- Worker 执行完成后返回 Supervisor，形成循环直到任务完成

### 2.2 目录结构

```
test_agents/
├── agents/                      # 智能体定义
│   ├── __init__.py
│   ├── supervisor.py            # 测试经理 Supervisor
│   ├── code_analyzer.py         # 代码分析智能体
│   └── case_reviewer.py         # 用例评审智能体
├── tools/                       # 公共工具层
│   ├── __init__.py
│   ├── claude_cli.py            # 调用 claude -p 的工具
│   ├── git_diff.py              # Git 变更提取工具
│   ├── test_case_parser.py      # 测试用例解析工具
│   └── business_knowledge.py    # 业务知识查询工具
├── graph/                       # 图编排
│   ├── __init__.py
│   ├── state.py                 # GraphState 定义
│   └── builder.py               # 图构建与编译
├── skills/                      # Claude CLI Skills
│   ├── readme.md                # Skill 安装与使用说明
│   ├── code_analysis_skill/     # 代码分析 Skill
│   │   └── SKILL.md             # Skill 元数据：代码变更分析指令
│   └── case_review_skill/       # 用例评审 Skill
│       └── SKILL.md             # Skill 元数据：测试用例评审指令
├── prompts/                     # 提示词模板
│   ├── supervisor.md
│   ├── code_analyzer.md
│   └── case_reviewer.md
├── config.py                    # 配置（模型、API Key、路径等）
└── readme.md                    # 项目说明
```

## 3. 状态设计（GraphState）

```python
class TestAgentState(TypedDict):
    # === 用户输入 ===
    module_name: str
    source_commit: str
    target_commit: str
    commit_msg: str
    test_cases: list[dict]
    business_knowledge: str

    # === 中间产物 ===
    code_change_report: str        # 代码分析结果
    review_results: list[dict]     # 用例评审结果

    # === 控制流 ===
    next_step: str                 # Supervisor 决策
    messages: Annotated[list, add_messages]
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `module_name` | `str` | 待分析的模块名称 |
| `source_commit` | `str` | 源 commit ID |
| `target_commit` | `str` | 目标 commit ID |
| `commit_msg` | `str` | commit message（辅助理解变更意图） |
| `test_cases` | `list[dict]` | 待评审的测试用例，支持单条或批量 |
| `business_knowledge` | `str` | 可选的业务背景知识 |
| `code_change_report` | `str` | 代码分析智能体输出的变更报告 |
| `review_results` | `list[dict]` | 用例评审智能体输出的评审结果 |
| `next_step` | `str` | Supervisor 路由决策：`analyze` / `review` / `end` |
| `messages` | `list` | LangGraph MessagesState 的 messages 字段，累积对话历史 |

## 4. 节点设计

### 4.1 Supervisor 节点（测试经理）

**职责**：
- 读取当前 `state`，判断已完成的步骤和待执行的任务
- 输出 `next_step` 字段，驱动条件边路由

**决策逻辑**：

```
if code_change_report 为空:
    next_step = "analyze"
elif test_cases 非空 且 review_results 为空:
    next_step = "review"
else:
    next_step = "end"
```

**加载工具**：无（纯 LLM 决策节点）

**提示词**：`prompts/supervisor.md`

### 4.2 代码分析智能体（CodeAnalyzer）

**职责**：
- 接收 `module_name`、`source_commit`、`target_commit`
- 调用 `GitDiffTool` 提取代码变更
- 将变更内容通过 `ClaudeCliTool`（`claude -p`）传递给 Claude CLI 进行分析
- 生成结构化变更报告，写入 `code_change_report`

**加载工具**：
- `GitDiffTool`：执行 `git diff <src>..<tgt> -- <module>/`
- `ClaudeCliTool`：封装 `claude -p <analysis_prompt>` 调用

**提示词**：`prompts/code_analyzer.md`

**输出格式**：

```python
{
    "code_change_report": """
    ## 变更概述
    ...
    ## 新增/修改/删除的文件
    ...
    ## 关键逻辑变更
    ...
    ## 影响范围评估
    ...
    """
}
```

### 4.3 用例评审智能体（CaseReviewer）

**职责**：
- 读取 `code_change_report` + `test_cases` + `business_knowledge`
- 调用 `TestCaseParserTool` 将输入统一为结构化用例列表
- 调用 `ClaudeCliTool`（`claude -p`）对用例进行评审
- 支持单条评审和批量评审两种模式
- 输出评审结果到 `review_results`

**加载工具**：
- `ClaudeCliTool`：封装 `claude -p <review_prompt>` 调用
- `TestCaseParserTool`：解析单条/批量用例输入，统一为 `list[dict]`
- `BusinessKnowledgeTool`：从本地知识库检索相关业务知识（可选）

**提示词**：`prompts/case_reviewer.md`

**输出格式**：

```python
{
    "review_results": [
        {
            "case_id": "TC001",
            "title": "...",
            "verdict": "pass / fail / needs_improvement",
            "score": 85,
            "issues": ["缺少边界值验证", "步骤描述不清晰"],
            "suggestions": ["补充负数输入场景", "明确前置条件"],
            "coverage_assessment": "覆盖了主要路径，缺少异常分支"
        }
    ]
}
```

## 5. 图编排（Graph Builder）

### 5.1 节点与边

```python
graph = StateGraph(TestAgentState)

# 添加节点
graph.add_node("supervisor", supervisor_node)
graph.add_node("code_analyzer", code_analyzer_node)
graph.add_node("case_reviewer", case_reviewer_node)

# 固定边
graph.add_edge(START, "supervisor")
graph.add_edge("code_analyzer", "supervisor")
graph.add_edge("case_reviewer", "supervisor")

# 条件边：Supervisor 决策路由
graph.add_conditional_edges(
    "supervisor",
    route_decision,
    {
        "analyze": "code_analyzer",
        "review": "case_reviewer",
        "end": END
    }
)
```

### 5.2 执行流程

```
用户输入（模块名、commit、用例）
    ↓
START → Supervisor
    ↓ 判断：无 code_change_report
    ↓
CodeAnalyzer
    ├─ GitDiffTool 提取变更
    ├─ ClaudeCliTool 分析变更
    └─ 输出 code_change_report
    ↓
Supervisor
    ↓ 判断：有 report，有用例，无 review_results
    ↓
CaseReviewer
    ├─ TestCaseParserTool 解析用例
    ├─ BusinessKnowledgeTool 查询业务知识（可选）
    ├─ ClaudeCliTool 评审用例
    └─ 输出 review_results
    ↓
Supervisor
    ↓ 判断：所有任务完成
    ↓
END → 输出 review_results
```

## 6. 工具层设计

### 6.1 GitDiffTool

**功能**：提取指定模块在 commit 范围内的代码变更

**参数**：
- `module_name`: `str` — 模块路径
- `source_commit`: `str` — 源 commit
- `target_commit`: `str` — 目标 commit

**实现**：调用 `subprocess.run(["git", "diff", f"{src}..{tgt}", "--", f"{module}/"])`

### 6.2 ClaudeCliTool

**功能**：封装 `claude -p` 命令调用，将 prompt 传递给 Claude CLI 并返回结果

**参数**：
- `prompt`: `str` — 要传递给 Claude CLI 的完整提示词
- `model`: `str` — 可选，指定模型（默认从 config 读取）

**实现**：调用 `subprocess.run(["claude", "-p", prompt], capture_output=True)`

### 6.3 TestCaseParserTool

**功能**：统一解析单条和批量用例输入

**参数**：
- `input_data`: `str` — 原始输入（JSON/Excel/纯文本）
- `format`: `str` — 输入格式：`json` / `excel` / `text`

**输出**：统一为 `list[dict]`，每个 dict 包含 `case_id`, `title`, `steps`, `expected_result` 等字段

### 6.4 BusinessKnowledgeTool

**功能**：根据模块名查询相关业务知识

**参数**：
- `module_name`: `str` — 模块名称
- `query`: `str` — 可选，补充查询条件

**实现**：从本地知识库（JSON/YAML 文件或向量数据库）检索匹配的业务描述

## 7. Skill 层设计

### 7.1 设计目的

`skills/` 目录存放 **Claude CLI Skill**，供本项目的智能体在运行时通过 `ClaudeCliTool` 间接调用。

**调用链路**：

```
本项目的 LangGraph 智能体 (CodeAnalyzer / CaseReviewer)
    ↓ 调用 ClaudeCliTool
Claude CLI (claude -p)
    ↓ 加载并使用 Skill
Skill 完成特定子任务（如代码变更分析、用例评审）
    ↓ 返回结果
Claude CLI 返回输出
    ↓
智能体接收结果，写入 state
```

**部署方式**：将 `skills/` 下的 skill 目录复制到 Claude 用户级 skill 目录（如 `~/.claude/skills/`），Claude CLI 启动时自动加载。

### 7.2 Skill 结构

```
skills/
├── readme.md                        # Skill 安装与使用说明
├── code_analysis_skill/             # 代码分析 Skill
│   └── SKILL.md                     # Skill 元数据：代码变更分析指令
└── case_review_skill/               # 用例评审 Skill
    └── SKILL.md                     # Skill 元数据：测试用例评审指令
```

每个 Skill 是一个独立目录，仅包含 `SKILL.md`。Claude CLI 通过 `SKILL.md` 中的元数据识别和加载 skill。

### 7.3 Skill 内容示例

**`code_analysis_skill/SKILL.md`**：
- 定义代码变更分析的指令模板
- 规定输出格式（变更概述、影响文件、关键逻辑变更、影响范围评估）
- 定义输入参数占位符（`{{module_name}}`、`{{diff_content}}`、`{{commit_msg}}`）

**`case_review_skill/SKILL.md`**：
- 定义测试用例评审的指令模板
- 规定输出格式（verdict、score、issues、suggestions、coverage_assessment）
- 定义输入参数占位符（`{{code_change_report}}`、`{{test_cases}}`、`{{business_knowledge}}`）

### 7.4 调用方式

本项目的智能体通过 `ClaudeCliTool` 调用 Claude CLI，prompt 中嵌入 skill 触发指令：

```python
# CodeAnalyzer 中
prompt = f"""
分析以下代码变更：
模块：{module_name}
Commit：{source_commit}..{target_commit}
变更内容：\n{diff_content}

请使用 code_analysis_skill 进行结构化分析。
"""
claude_cli_tool.run({"prompt": prompt})

# CaseReviewer 中
prompt = f"""
基于以下代码变更报告评审测试用例：
变更报告：\n{code_change_report}
用例列表：\n{test_cases}
业务知识：\n{business_knowledge}

请使用 case_review_skill 进行结构化评审。
"""
claude_cli_tool.run({"prompt": prompt})
```

## 8. 错误处理

| 场景 | 处理方式 |
|---|---|
| `git diff` 执行失败（commit 不存在/模块不存在） | 返回错误信息到 state，Supervisor 可决策重试或终止 |
| `claude -p` 超时/失败 | 捕获异常，将错误作为 ToolMessage 返回，Agent 提示用户检查 Claude CLI 配置 |
| 用例格式错误 | `TestCaseParserTool` 返回结构化错误，Supervisor 终止流程并提示用户修正输入 |
| 业务知识库未命中 | 返回空字符串继续执行，不阻塞评审流程 |

## 9. 扩展性考虑

- **增加 Worker**：在 `agents/` 下新增智能体文件，在 `supervisor.py` 的决策逻辑中增加路由分支即可
- **替换模型**：通过 `config.py` 统一配置 LLM 模型，所有 Agent 节点读取同一配置
- **新增工具**：在 `tools/` 下新增工具文件，在对应 Agent 的 `bind_tools` 中注册
- **切换为子图模式**：未来 Worker 数量增多时，可将 `case_reviewer` 拆分为独立子图（内部再分单条/批量 Worker），Supervisor 调用子图即可

## 10. 依赖

```
langgraph
langchain-core
langchain-openai  # 或其他模型 provider
pydantic
```

Claude CLI 需单独安装并配置到 PATH 中。

---

<!-- AUTONOMOUS DECISION LOG -->
## Autoplan Review Decision Audit Trail

Captured: 2026-05-15 | Reviewer: Claude subagent only (Codex unavailable)

| # | Phase | Decision | Classification | Principle | Rationale |
|---|-------|----------|----------------|-----------|-----------|
| 1 | CEO | 保留「评审测试用例」定位（不改为生成测试） | User Challenge rejected | P6 (用户方向优先) | 用户明确选择保留当前设计，接受风险 |
| 2 | CEO | 保留 LangGraph Supervisor 架构 | User Challenge rejected | P6 (用户方向优先) | 用户选择保留，后续实现中验证 |
| 3 | CEO | 保留 Claude CLI 子进程调用方式 | User Challenge rejected | P6 (用户方向优先) | 用户选择保留，作为 Skill 的核心链路 |
| 4 | Eng | 不添加 checkpointing（当前 scope 内） | Auto-decided | P3 (pragmatic) | MVP 阶段可用 InMemorySaver，后续升级 |
| 5 | Eng | 接受 diff 大小风险（后续加阈值） | Auto-decided | P3 (pragmatic) | 首版不加复杂分块，先验证核心流程 |
| 6 | Eng | 在实现阶段添加输入验证（SHA 正则、路径净化） | Auto-decided | P1 (completeness) | 安全风险必须在首版修复 |
| 7 | DX | 不拆分 README/ARCHITECTURE（当前 scope 内） | Auto-decided | P3 (pragmatic) | 首版用单一 readme，后续拆分 |
| 8 | DX | 在实现阶段添加入口点（main.py + CLI） | Auto-decided | P1 (completeness) | DX 关键缺口，必须修复 |

### Review Scores Summary
- CEO: 8/10 — 定位清晰但缺少竞争分析和护城河设计
- Eng: 7/10 — 架构合理但缺少安全校验和 checkpointing
- DX: 6/10 — 缺少快速开始和入口点

### Critical Items Deferred to Implementation
1. 输入验证（commit SHA 正则、路径净化）— 必须在首版实现
2. 命令注入防护 — 必须在首版实现
3. `main.py` 入口点和 CLI 封装 — 必须在首版实现
4. 测试计划 — 实施阶段补充
