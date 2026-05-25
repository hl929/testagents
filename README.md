# Test Agents

基于 LangGraph 的多智能体测试系统，采用 Supervisor + Worker 架构执行代码变更分析和测试用例评审。

## 功能

- 自然语言入口：根据用户请求自动判断走单 Worker 还是完整 Supervisor 流程
- 代码分析 Agent：分析模块代码变更，输出结构化变更报告
- 用例评审 Agent：基于代码变更、业务知识和测试用例输出评审结果
- Plan-and-Solve：Supervisor 生成执行计划，并支持人工确认
- Reflection：Worker 和 Supervisor 均支持结果质量评估
- 可观测性：输出 JSONL 日志、单次 trace 日志和 metrics 汇总

## 安装

```bash
pip install -r requirements.txt
```

系统依赖：`grep` / `glob` 工具依赖 ripgrep。

```bash
# WSL/Ubuntu/Debian
sudo apt install ripgrep

# macOS
brew install ripgrep
```

## 配置

复制环境变量示例并填写实际值：

```bash
cp .env.example .env
```

常用变量：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `TEST_AGENTS_MODEL` | LLM 模型 | `kimi-k2.6` |
| `OPENAI_API_KEY` | LLM API Key | - |
| `OPENAI_BASE_URL` | LLM API 基地址 | - |
| `TEST_AGENTS_CLAUDE_TIMEOUT` | Claude CLI 超时秒数 | `1200` |
| `TEST_AGENTS_MAX_PLAN_ITERATIONS` | 最大计划迭代次数 | `1` |
| `TEST_AGENTS_MAX_CONFIRM_RETRIES` | 最大计划确认重试次数 | `1` |
| `TEST_AGENTS_LOG_LEVEL` | 可观测日志级别：`OFF|INFO|DEBUG|TRACE` | `INFO` |

## 使用

交互模式：

```bash
python -m test_agents
```

直接传入自然语言请求：

```bash
python -m test_agents "分析 order 模块从 a1b2c3d 到 e4f5a6b 的代码变更"
```

JSON 输出：

```bash
python -m test_agents "评审测试用例" --output json
```

## 测试

运行全部测试：

```bash
python -m pytest test_agents/tests/ -v
```

运行单个测试文件：

```bash
python -m pytest test_agents/tests/test_integration.py -v
```

## 架构概览

```text
用户请求 → intent_classifier → planner → confirm_plan → dispatch → worker(s) → reflect → synthesize → save_experience
```

核心组件：

- `test_agents/main.py`：CLI 入口和运行模式调度
- `test_agents/graph/builder.py`：Supervisor 图和 Worker 子图组装
- `test_agents/agents/supervisor.py`：计划、确认、调度、反思、汇总节点
- `test_agents/agents/worker_base.py`：通用 Worker ReAct + Reflection 子图
- `test_agents/agents/code_analyzer.py`：代码分析 Worker
- `test_agents/agents/case_reviewer.py`：测试用例评审 Worker
- `test_agents/tools/`：Claude CLI、测试用例解析、业务知识库、文件系统只读工具
- `test_agents/observability/`：日志、trace 和 metrics

Worker 输出统一写入 `outputs[output_key]`，例如：

- `code_change_report`
- `review_results`

## 可观测性

默认日志目录：

```text
logs/
├── app-YYYY-MM-DD.jsonl
├── traces/<trace_id>.jsonl
└── metrics.jsonl
```

关闭观测：

```bash
TEST_AGENTS_LOG_LEVEL=OFF python -m test_agents "分析代码变更"
```
