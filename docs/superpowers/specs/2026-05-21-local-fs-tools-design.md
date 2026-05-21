# 通用文件系统工具设计 (Local FS Tools)

日期：2026-05-21
状态：Draft（待 review）
作者：Claude Code（与 hl929 协作）

## 背景

当前 Worker `code_analyzer` 仅绑定 `claude_cli`，所有文件系统访问需通过 prompt 让 Claude CLI 子进程间接完成。
对 `/mnt/d/obs_node/` 等位于本项目目录外的代码仓库，Worker 没有直接的"读文件 / 列目录 / 搜索"能力，导致跨仓库变更分析无法落地。

## 目标

- 为 Worker 增加 4 个**只读**的通用本地文件系统工具
- 不限定可访问路径（用户自担风险，与操作系统权限对齐）
- 工具语义清晰、单一职责，便于 LLM 工具调用
- 与现有 `TestAgentTool` 自动注册机制无缝集成

## 非目标

- 不实现写入工具（write / edit / rm / mv）
- 不实现通用 shell 工具（避免命令注入与权限放大）
- 不实现路径白名单沙箱（操作系统权限更可靠）
- 不维护会话级 cwd（保持工具无状态以适配 LangGraph 并发）

## 方案选型

| 候选 | 实现 | 安全 | 跨平台 | 接口清晰 | 结论 |
|---|---|---|---|---|---|
| A. 纯 Python | `pathlib + re + os.walk` | ✅ | ✅ | ✅ | 备选 |
| **B. ripgrep 子进程**（采纳） | grep/glob → `rg`，read/list → 原生 fs | ✅（无 `shell=True`） | ⚠️ 需装 rg | ✅ | **采纳** |
| C. langchain FileManagementToolkit | 社区封装 | ✅ | ✅ | ⚠️ 无 grep | 否 |
| D. 复用 local_file 中的 TerminalTool | `shell=True` + 白名单 | ❌ 命令可绕过白名单；`bash/python` 也在白名单 | ⚠️ 包装 | ❌ 单一 command 入口 | 否 |

**方案 B 理由**：
- 与 opencode、Claude Code 内置工具的实现路径一致（均用 ripgrep）
- 性能优于纯 Python（自动并行 + 默认尊重 `.gitignore`）
- `subprocess.run([...])`（list 形式）不开 shell，无命令注入
- ripgrep 是单二进制，三大平台均有标准安装方式

## 架构

```
test_agents/tools/
├── base.py              （已有，TestAgentTool 自动注册）
├── claude_cli.py        （已有）
├── business_knowledge.py（已有）
├── test_case_parser.py  （已有）
└── fs/                  （新增子包）
    ├── __init__.py      （触发四个子模块 import，激活自动注册）
    ├── read_file.py     → ReadFileTool（原生 fs）
    ├── list_dir.py      → ListDirTool（原生 fs）
    ├── grep.py          → GrepTool（subprocess → rg）
    ├── glob.py          → GlobTool（subprocess → rg --files）
    └── _rg.py           → 共享 ripgrep 调用封装
```

- 4 个工具均继承 `TestAgentTool`，靠 `__init_subclass__` 自动注册到 `ToolRegistry`
- 单文件单类，与 `claude_cli.py` 风格一致
- `_rg.py` 集中处理：定位 `rg` 二进制、超时、退出码、stderr 收集
- 全部**只读**，全部接受**绝对路径**（无 cwd 状态）

### Worker 绑定

- `code_analyzer` = `["claude_cli", "read_file", "list_dir", "grep", "glob"]`
- `case_reviewer` 不变（保持 `["claude_cli", "parse_test_cases", "query_business_knowledge"]`）

绑定点：`test_agents/agents/code_analyzer.py` 第 8 行

```python
_code_analyzer_tools = ToolRegistry.get_tools_by_names(
    ["claude_cli", "read_file", "list_dir", "grep", "glob"]
)
```

### 工具激活

修改已有的 `test_agents/tools/__init__.py`，在末尾追加：

```python
from test_agents.tools.fs.read_file import ReadFileTool
from test_agents.tools.fs.list_dir import ListDirTool
from test_agents.tools.fs.grep import GrepTool
from test_agents.tools.fs.glob import GlobTool
```

显式 import 触发 `__init_subclass__`，与现有 `claude_cli` 等工具的注册方式保持一致；确保 `ToolRegistry._tool_classes` 在 `build_graph()` 调用 `get_tools_by_names()` 前已收集 4 个新类。`tools/fs/__init__.py` 可留空。

## 工具规格

### `read_file`

读取单个文件的内容。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `file_path` | str | 必填 | 绝对路径 |
| `offset` | int | 0 | 起始行号（0-based） |
| `limit` | int | 2000 | 最多读取行数 |

行为：
- 路径不存在 → `错误: 文件不存在: {path}`
- 是目录 → `错误: 路径是目录，请用 list_dir: {path}`
- 二进制（探测前 4KB 含 `\x00`）→ `错误: 二进制文件无法读取: {path}`
- 文件 > 5 MB 且未显式传 `limit` → 强制截断到前 2000 行，附 `⚠️ 文件过大，仅显示前 2000 行`
- 输出格式：`{line_no:>6}\t{line_content}`（与 Claude Code 的 Read 一致），便于 LLM 引用 `file:line`

### `list_dir`

列出目录树。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `path` | str | 必填 | 绝对路径 |
| `depth` | int | 1 | 递归深度（1-3） |
| `show_hidden` | bool | false | 是否显示 `.` 开头条目 |

行为：
- 不存在 / 不是目录 → 报错
- 输出为 `tree` 风格树形结构，文件标 ` ({size})`、目录加 `/`
- 单次最多 500 个条目，超出截断附提示
- 始终跳过 `.git`、`node_modules`、`__pycache__`、`.venv`（即使 `show_hidden=true` 也跳过，避免大目录污染输出）

### `grep`

使用 ripgrep 在文件内容中按正则搜索。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `pattern` | str | 必填 | 正则（rg 默认引擎） |
| `path` | str | 必填 | 绝对路径（文件或目录） |
| `include` | str | "" | 文件 glob 过滤，如 `*.py` 或 `*.{ts,tsx}` |
| `case_insensitive` | bool | false | `-i` |
| `max_results` | int | 100 | 截断保护 |

底层命令：
```
rg --line-number --no-heading --color=never [-i] [-g <include>] -- <pattern> <path>
```

行为：
- 输出格式：`{file}:{line}:{content}`（rg 原生格式）
- 0 结果 → `未找到匹配`
- 超过 `max_results` → 截断 + `⚠️ 结果超过 {n}，仅显示前 {n} 条`
- rg 退出码 1（无匹配）视为正常；退出码 ≥2 → 错误消息（含 stderr）
- 默认尊重 `.gitignore`（rg 默认行为）

### `glob`

使用 ripgrep `--files` 做文件名匹配。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `pattern` | str | 必填 | glob 模式，如 `**/*.py` |
| `path` | str | 必填 | 搜索根目录（绝对路径） |
| `max_results` | int | 200 | 截断保护 |

底层命令：
```
rg --files --glob <pattern> <path>
```

行为：
- 输出按 mtime 倒序排列的绝对路径，一行一个
- 超出 `max_results` 截断 + 提示

### 共享 `_rg.py`

```python
def run_rg(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """调用 ripgrep，返回 (returncode, stdout, stderr)。

    rg 未安装 → 抛 RuntimeError（带平台安装提示）
    超时 → 抛 TimeoutError
    """
```

`grep.py` 和 `glob.py` 调用此函数，捕获 `RuntimeError` / `TimeoutError` 转为 LLM 友好错误字符串。

## 错误处理

所有工具采用统一的"LLM 友好错误"模式 —— 错误不抛异常，作为字符串返回给 LLM，由 LLM 决定重试 / 换路径 / 报告用户。与 `ClaudeCliTool` 风格一致。

| 错误类别 | 返回示例 |
|---|---|
| 参数缺失/非绝对路径 | `错误: file_path 必须是绝对路径，收到: ./foo.py` |
| 路径不存在 | `错误: 文件不存在: /mnt/d/obs_node/foo.py` |
| 路径类型错 | `错误: 路径是目录，请用 list_dir: {path}` |
| 二进制文件 | `错误: 二进制文件无法读取: {path}` |
| ripgrep 未安装 | `错误: 未找到 ripgrep。请安装：apt install ripgrep / brew install ripgrep / scoop install ripgrep` |
| ripgrep 超时 | `错误: ripgrep 超时（30s），考虑缩小 path 或使用更精确的 include 过滤` |
| 输出过大 | 截断 + `⚠️ 输出已截断，剩余 N 行未显示` |
| 内部异常 | `错误: 工具执行失败 - {repr(e)}` |

重试由 `worker_base.py` 的 `reflection_count` 上限统一管控，工具本身不重试。

## 测试

新增 `test_agents/tests/test_fs_tools.py`，与 `test_workers.py` 共存。

### Fixture

```python
@pytest.fixture
def fs_sandbox(tmp_path):
    """构造一个 mini 仓库：
    tmp_path/
      src/main.py     ('def foo(): pass\ndef bar(): pass\n')
      src/util.py     ('def helper(): pass\n')
      README.md
      bin.dat         (含 \x00)
      big.txt         (> 5MB)
    """
```

### 用例矩阵（约 20 条）

| 工具 | 用例 |
|---|---|
| read_file | 正常读 / 行号格式 / offset+limit / 不存在 / 是目录 / 二进制 / 大文件强制截断 |
| list_dir | depth=1 / depth=3 / 隐藏文件 / 自动跳过 .git / 500 条截断 / 不存在 |
| grep | 命中 / 未命中 / `include` 过滤 / case_insensitive / `max_results` 截断 / 非法 pattern |
| glob | `**/*.py` / mtime 排序 / 不存在 / `max_results` 截断 |
| 集成 | `ToolRegistry.get_tools_by_names()` 返回 4 个新工具且 schema 可被 LangChain 渲染 |

### ripgrep 可用性

- pytest 启动时 `shutil.which("rg") is None` → grep/glob 用例 `pytest.skip("需要 ripgrep")`
- 标记 `@pytest.mark.requires_rg`

### Worker 集成验证

在 `test_workers.py` 增加 1 个用例，断言 `code_analyzer` 的 tools 列表长度 == 5 且名称完整。

`test_integration.py` 保持不变（mock 了 worker 子图，不受新工具影响）。

## 文档变更

| 文件 | 改动 |
|---|---|
| `README.md` | 新增 "系统依赖：ripgrep" 小节，给出 apt / brew / scoop / winget 安装命令 |
| `CLAUDE.md` | "工具层" 段落新增 4 个工具及其与 `code_analyzer` 的绑定关系 |
| `test_agents/prompts/code_analyzer.md` | 在 prompt 中明确告诉 LLM 可用 `read_file/list_dir/grep/glob` 访问任意绝对路径的仓库；增加针对 `/mnt/d/obs_node/` 等外部仓库的调用示范 |
| `requirements.txt` | 不变（纯 Python 实现，ripgrep 为系统依赖） |

## 安全说明

- 工具均为只读，无写入风险
- **不限制路径范围**：agent 可访问宿主用户能访问的任意文件（包括 `/etc/passwd` 等）；用户需要更严的隔离应在操作系统层（unprivileged user / 容器）实现
- 所有 subprocess 调用使用 `list` 形式参数，禁用 `shell=True`，无命令注入
- ripgrep 调用经超时控制（30s 默认），不会长时间挂起 Worker

## 实施顺序（供 writing-plans 参考）

1. `tools/fs/_rg.py` + 单元测试
2. `tools/fs/read_file.py` + `tools/fs/list_dir.py` + 单元测试（不依赖 rg，可先跑）
3. `tools/fs/grep.py` + `tools/fs/glob.py` + 单元测试
4. 修改 `test_agents/tools/__init__.py`，追加 4 个 import 触发自动注册（`tools/fs/__init__.py` 留空即可）
5. `agents/code_analyzer.py` 增加工具绑定
6. `test_workers.py` 添加绑定断言
7. 更新 `README.md` / `CLAUDE.md` / `prompts/code_analyzer.md`
8. 手工 e2e：用真实 obs_node 仓库跑一次 `python -m test_agents "分析 /mnt/d/obs_node 最近变更"`

