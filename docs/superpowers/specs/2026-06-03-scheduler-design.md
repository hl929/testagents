# Scheduler 定时调度模块设计

## 1. 背景与目标

为 test_agents 增加定时调度能力，允许用户配置 cron 表达式和 prompt，到了指定时间自动执行对应的 Agent 任务，并将结果追加写入报告文件。任务配置需要持久化存储，重启后自动恢复。

## 2. 设计原则

- **与现有架构解耦**：scheduler 作为独立模块运行，不侵入 main.py / graph / agents 的现有代码
- **复用现有入口**：定时任务的执行复用 `run_test_agents()`，完全一致的体验
- **进程隔离**：调度器可独立长期运行，不影响交互式 CLI 的短期执行模式
- **持久化**：任务仓库用本地 JSON 文件，零外部依赖

## 3. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    test_agents.scheduler                     │
│  (长期驻留进程: python -m test_agents.scheduler start)      │
├─────────────────────────────────────────────────────────────┤
│  CLI 层 (argparse)                                          │
│    ├─ add    : 添加定时任务                                 │
│    ├─ remove : 删除定时任务                                 │
│    ├─ list   : 列出所有任务                                 │
│    ├─ start  : 启动调度器进程                               │
│    └─ stop   : 停止调度器进程                               │
├─────────────────────────────────────────────────────────────┤
│  调度引擎 (APScheduler)                                     │
│    ├─ CronTrigger : 解析 cron 表达式                        │
│    └─ JobStore    : 内存 + 自定义 JSON 持久化               │
├─────────────────────────────────────────────────────────────┤
│  执行层                                                      │
│    └─ 调用 run_test_agents(prompt) → 结果写入报告文件      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    logs/scheduled_reports.md   (追加写入)
                    data/scheduled_tasks.json   (任务仓库)
```

## 4. 数据模型

### 4.1 ScheduledTask

```python
class ScheduledTask(BaseModel):
    id: str              # UUID，唯一标识
    name: str            # 用户可读的任务名称
    cron: str            # cron 表达式，如 "0 9 * * 1-5"
    prompt: str          # 执行时传给 run_test_agents() 的 prompt
    agent_hint: str      # 可选，直接指定 worker (code_analyzer / case_reviewer / data_analyst)
                         # 为空则走 Supervisor 自动路由
    output_file: str     # 结果追加写入的文件路径（默认 logs/scheduled_reports.md）
    timezone: str        # 时区，默认 "Asia/Shanghai"
    enabled: bool        # 是否启用
    created_at: str      # ISO 时间
    last_run_at: str | None
    last_run_status: str | None   # "success" | "error"
    run_count: int       # 执行次数统计
```

### 4.2 任务仓库 (data/scheduled_tasks.json)

```json
{
  "version": 1,
  "tasks": [
    {
      "id": "uuid",
      "name": "每日代码分析",
      "cron": "0 9 * * 1-5",
      "prompt": "分析昨天提交的代码变更",
      "agent_hint": "code_analyzer",
      "output_file": "logs/scheduled_reports.md",
      "timezone": "Asia/Shanghai",
      "enabled": true,
      "created_at": "2026-06-03T10:00:00+08:00",
      "last_run_at": null,
      "last_run_status": null,
      "run_count": 0
    }
  ]
}
```

## 5. 模块设计

### 5.1 test_agents/scheduler/models.py

定义 `ScheduledTask` Pydantic 模型，包含验证逻辑（cron 表达式合法性检查）。

### 5.2 test_agents/scheduler/store.py

JSON 任务仓库的读写管理：

- `load() -> list[ScheduledTask]`：从 `data/scheduled_tasks.json` 加载全部任务
- `save(tasks: list[ScheduledTask])`：原子写回 JSON 文件（先写临时文件再 rename）
- `add(task: ScheduledTask) -> None`：添加任务并保存
- `remove(task_id: str) -> bool`：按 ID 删除任务
- `get(task_id: str) -> ScheduledTask | None`：按 ID 获取任务

并发安全：JSON 文件读写使用文件锁（`fcntl` on Linux / `msvcrt` on Windows），防止多进程同时修改。

### 5.3 test_agents/scheduler/engine.py

APScheduler 封装：

- `SchedulerEngine` 类，内部持有 `BackgroundScheduler`
- `load_jobs()`：启动时从 store 加载所有 enabled 任务，为每个任务创建 `CronTrigger` Job
- `add_job(task: ScheduledTask)`：动态添加任务到 APScheduler
- `remove_job(task_id: str)`：从 APScheduler 移除任务
- `start()` / `shutdown()`：启停调度器
- 回调函数 `on_trigger(task_id: str)`：触发时调用 executor 执行

依赖：`pip install apscheduler`

### 5.4 test_agents/scheduler/executor.py

执行回调：

```python
def execute_task(task: ScheduledTask) -> None:
    """被 APScheduler 触发时调用"""
    start_time = datetime.now().isoformat()
    try:
        result = run_test_agents(task.prompt)
        status = "success"
        content = result.get("final_answer", "")
    except Exception as e:
        status = "error"
        content = f"执行异常: {e}"

    # 格式化并追加写入报告文件
    report = _format_report(task, start_time, status, content)
    _append_to_file(task.output_file, report)

    # 更新任务状态并持久化
    task.last_run_at = start_time
    task.last_run_status = status
    task.run_count += 1
    store.save_all()
```

报告格式示例：

```markdown
## [2026-06-03 09:00:00] 每日代码分析

- **任务 ID**: uuid
- **Cron**: `0 9 * * 1-5`
- **状态**: success
- **Prompt**: 分析昨天提交的代码变更

### 执行结果

<result content here>

---
```

### 5.5 test_agents/scheduler/cli.py

argparse CLI：

```bash
python -m test_agents.scheduler add \
  --name "每日代码分析" \
  --cron "0 9 * * 1-5" \
  --prompt "分析昨天提交的代码变更" \
  --agent code_analyzer \
  --output logs/daily_code_report.md \
  --timezone Asia/Shanghai

python -m test_agents.scheduler list
python -m test_agents.scheduler remove --id <uuid>
python -m test_agents.scheduler start
python -m test_agents.scheduler stop
```

`stop` 实现：写入 PID 文件到 `data/scheduler.pid`，stop 时读取 PID 发送 SIGTERM。

## 6. 执行流程

```
APScheduler 触发
    │
    ▼
┌─────────────────┐
│  executor.run() │  ──▶  记录 start_time
└─────────────────┘
    │
    ▼
run_test_agents(task.prompt)  (复用现有入口)
    │
    ▼
捕获结果 + 异常
    │
    ▼
┌─────────────────┐
│  格式化输出      │  包含: 时间、任务名、cron、结果摘要、错误信息
└─────────────────┘
    │
    ▼
追加写入 task.output_file
    │
    ▼
更新 task.last_run_at / last_run_status / run_count
原子写回 data/scheduled_tasks.json
```

## 7. 错误处理

| 场景 | 处理方式 |
|---|---|
| 任务执行失败 | 记录错误到报告文件，更新 `last_run_status="error"`，不影响其他任务调度 |
| 调度器进程崩溃 | 重启后从 `data/scheduled_tasks.json` 重新加载所有任务，未过期的继续执行 |
| 并发修改任务仓库 | JSON 文件读写使用文件锁，保证原子性 |
| cron 表达式非法 | `add` 时校验，非法则拒绝并提示 |
| 输出文件目录不存在 | 自动创建父目录 |

## 8. 配置与环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `TEST_AGENTS_SCHEDULER_TASKS_FILE` | 任务仓库路径 | `data/scheduled_tasks.json` |
| `TEST_AGENTS_SCHEDULER_PID_FILE` | PID 文件路径 | `data/scheduler.pid` |
| `TEST_AGENTS_SCHEDULER_DEFAULT_OUTPUT` | 默认报告文件 | `logs/scheduled_reports.md` |

## 9. 依赖

新增依赖（写入 `requirements.txt`）：

```
apscheduler>=3.10.0
```

APScheduler 3.x 是成熟稳定的调度库，支持 cron 表达式、时区、多 trigger 类型，社区广泛采用。

## 10. 测试策略

- **单元测试**：`test_scheduler_store.py` — store 的增删改查、并发安全
- **单元测试**：`test_scheduler_engine.py` — engine 的 load/start/stop，mock APScheduler
- **集成测试**：`test_scheduler_e2e.py` — 启动 scheduler，用短间隔 trigger 验证执行和文件输出
- 所有测试不依赖真实 LLM，mock `run_test_agents()` 返回值
