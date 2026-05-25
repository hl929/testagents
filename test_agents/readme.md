# 测试智能体群（Test Agents）

基于 LangGraph Supervisor 模式的多智能体测试系统。

## 架构

- **测试经理（Supervisor）**：调度任务，决定调用代码分析 Agent 或用例评审 Agent
- **代码分析 Agent**：分析代码变更，生成变更报告
- **用例评审 Agent**：评审测试用例质量

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 安装 Claude CLI Skills

```bash
cp -r .claude/skills/code_analysis_skill ~/.claude/skills/
cp -r .claude/skills/case_review_skill ~/.claude/skills/
```

### 2. 运行测试分析

```bash
python -m test_agents "分析 order 模块从 a1b2c3d 到 e4f5a6b 的代码变更"
```

### 3. 查看 JSON 结果

```bash
python -m test_agents "分析 order 模块从 a1b2c3d 到 e4f5a6b 的代码变更" --output json
```

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `TEST_AGENTS_MODEL` | LLM 模型 | kimi-k2.6 |
| `TEST_AGENTS_CLAUDE_TIMEOUT` | Claude CLI 超时(秒) | 1200 |
| `TEST_AGENTS_MAX_PLAN_ITERATIONS` | 最大计划迭代次数 | 1 |
| `TEST_AGENTS_MAX_CONFIRM_RETRIES` | 最大计划确认重试次数 | 1 |

## 测试

```bash
python -m pytest test_agents/tests/ -v
```
