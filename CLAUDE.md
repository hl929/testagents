# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

这是一个基于 LangGraph 的多智能体测试系统（Test Agents v3），采用 Plan-and-Solve + Reflection 架构。Supervisor 解析用户自然语言请求，生成执行计划，调度 Worker Agent 完成任务，并通过 Reflection 评估结果质量。

## Common Commands

### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行测试
```bash
# 运行全部测试
python -m pytest test_agents/tests/ -v

# 运行单个测试文件
python -m pytest test_agents/tests/test_integration.py -v

# 运行单个测试函数
python -m pytest test_agents/tests/test_integration.py::test_full_pipeline_mocked -v
```

### 运行应用
```bash
# 需要先加载 .env（如未安装 python-dotenv: pip install python-dotenv）
python -c "from dotenv import load_dotenv; load_dotenv()" && python -m test_agents

# 交互模式
python -m test_agents

# 直接传入请求
python -m test_agents "分析订单模块代码变更"

# JSON 输出
python -m test_agents "评审测试用例" --output json
```

### 安装 Skills（可选）
```bash
# 项目级 skills 已在 .claude/skills/ 中，Claude Code 自动加载
# 如需用户级安装：
cp -r .claude/skills/code_analysis_skill ~/.claude/skills/
cp -r .claude/skills/case_review_skill ~/.claude/skills/
```

## Architecture

### 高层数据流

```
用户请求 → planner → confirm_plan → dispatch → worker(s) → reflect → synthesize → save_experience
                                              ↑___________________↓
```

- **planner**: 解析用户请求，生成 `ExecutionPlan`（结构化输出）
- **confirm_plan**: 使用 `langgraph.types.interrupt` 暂停图执行，等待用户确认计划
- **dispatch**: 根据 `current_step_index` 路由到下一个 worker
- **code_analyzer / case_reviewer**: Worker 节点，将 `SupervisorState` 转换为 `WorkerState`，调用子图执行
- **reflect**: Supervisor 评估整体执行结果，决定 REPLAN 或 COMPLETE
- **synthesize**: 汇总所有 step_results 生成最终答案
- **save_experience**: 将计划和执行经验追加写入 `data/reflection_experience.md`

### Worker 子图（ReAct + Reflection）

每个 Worker 都是一个独立的编译后子图（`StateGraph(WorkerState)`），结构为：

```
START → agent → (tools_condition) → tools → agent → reflect → (worker_route) → END
                        ↓______________________________________↑
```

- **agent**: LLM 绑定工具（`llm.bind_tools(tools)`）生成响应或工具调用
- **tools**: `ToolNode` 执行工具调用
- **reflect**: 评估结果质量，质量不通过时返回错误消息让 agent 重试
- 两个 Worker：
  - `code_analyzer`: 工具为 `[claude_cli]`，输出写入 `code_change_report`
  - `case_reviewer`: 工具为 `[claude_cli, parse_test_cases, query_business_knowledge]`，输出写入 `review_results`

### 状态定义

- **`SupervisorState`** (`test_agents/graph/state.py`): 主图状态，TypedDict，包含 `user_request`, `plan`, `current_step_index`, `step_results`, `code_change_report`, `review_results`, `final_answer` 等
- **`WorkerState`** (`test_agents/graph/state.py`): Worker 子图状态，TypedDict，包含 `task`, `messages`, `error`, `reflection_count`, `result`
- **`ExecutionPlan`** / **`PlanStep`** / **`StepResult`** / **`AnalysisTarget`**: Pydantic BaseModel，用于结构化 LLM 输出和输入校验

### 路由函数

所有条件边路由逻辑集中在 `test_agents/agents/supervisor.py` 底部：
- `route_from_confirm`: confirmed→dispatch, rejected→planner, over limit→end
- `route_from_dispatch`: 按 `current_step_index` 和 step agent 类型路由到 code_analyzer / case_reviewer / reflect
- `route_from_reflect`: needs_replan 且未达上限→planner，否则→synthesize
- `worker_route` (`worker_base.py`): error=="no" 或 reflection_count 超限→END，否则→agent

### 工具层

- **TestAgentTool 基类** (`test_agents/tools/base.py`): 所有工具继承 `TestAgentTool(BaseTool)`，子类定义时自动注册到 `ToolRegistry`
- **ToolRegistry** (`test_agents/tools/base.py`): 自动注册表，提供 `get_tools_by_names()` 按 Worker 绑定工具、`render_all()` 动态生成 Planner 工具描述
- **ClaudeCliTool** (`test_agents/tools/claude_cli.py`): 通过 `subprocess.run(["claude", "-p", prompt])` 调用 Claude CLI，有超时和重试机制
- **TestCaseParserTool** (`test_agents/tools/test_case_parser.py`): 解析 JSON/Text 格式测试用例
- **BusinessKnowledgeTool** (`test_agents/tools/business_knowledge.py`): 从本地 JSON 知识库查询模块业务知识

### Prompt 系统

Prompt 模板存放在 `test_agents/prompts/*.md`，通过 `test_agents/prompts/loader.py` 的 `load_prompt(name, **kwargs)` 加载并格式化。模板名称与文件名称一致（不含 `.md` 后缀）。

## Configuration

环境变量（定义在 `test_agents/config.py`）：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `TEST_AGENTS_MODEL` | LLM 模型 | gpt-4o |
| `OPENAI_API_KEY` | OpenAI API Key | — |
| `OPENAI_BASE_URL` | LLM API 基地址（国内模型） | — |
| `TEST_AGENTS_CLAUDE_TIMEOUT` | Claude CLI 超时(秒) | 120 |
| `TEST_AGENTS_MAX_PLAN_ITERATIONS` | 最大计划迭代次数 | 1 |
| `TEST_AGENTS_MAX_CONFIRM_RETRIES` | 最大计划确认重试次数 | 3 |
| `TEST_AGENTS_EXPERIENCE_FILE` | 反思经验文件路径 | `data/reflection_experience.md` |

## Key Files

- `test_agents/main.py`: CLI 入口，`run_test_agents()` 驱动主图并处理中断恢复
- `test_agents/graph/builder.py`: 图组装工厂，编译 Supervisor 图和两个 Worker 子图
- `test_agents/agents/supervisor.py`: Supervisor 节点和路由函数，所有节点都内联创建 LLM 实例（通过 `get_llm()`）
- `test_agents/agents/worker_base.py`: Worker 子图工厂 `build_worker_graph()`
- `test_agents/agents/code_analyzer.py` / `case_reviewer.py`: Worker 包装节点，负责 State 转换和结果提取
- `test_agents/graph/state.py`: 所有状态定义和 Pydantic 模型
- `test_agents/config.py`: 全局配置单例
- `test_agents/tools/base.py`: TestAgentTool 基类 + ToolRegistry 自动注册表

## Testing Notes

- 测试大量使用 `unittest.mock.patch` 来 Mock LLM、Worker 子图和 `interrupt`
- `test_integration.py` 包含完整的 pipeline Mock 测试，是理解数据流的最佳参考
- Worker 子图在 `build_graph()` 时初始化并缓存到全局变量（`code_analyzer_graph` / `case_reviewer_graph`），测试时通常直接 patch wrapper 函数

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
