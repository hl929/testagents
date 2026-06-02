# Data Analyst Worker（数据库访问能力）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `data_analyst` Worker，支持 MySQL 只读查询（`query_database` + `describe_schema`），Agent 可基于数据库内容生成测试数据洞察报告。

**Architecture:** 新增两个工具继承 `TestAgentTool` 自动注册。`QueryDatabaseTool` 用 `pymysql` 直连 MySQL，执行 SQL 安全校验（SELECT 白名单 + LIMIT 截断 + 超时）。`SchemaDescriptionTool` 从本地 Markdown 文件加载表结构描述。新增 `data_analyst` Worker 子图，复用 `build_worker_graph`，与 `code_analyzer` / `case_reviewer` 完全平行。Supervisor 路由增加 `data_analyst` 分支。

**Tech Stack:** Python 3.10+、`pymysql>=1.1.0`、`langchain-core` BaseTool、`langgraph` StateGraph、pytest

**Spec:** `docs/superpowers/specs/2026-06-02-database-access-design.md`

## File Structure

| 文件 | 类型 | 职责 |
|---|---|---|
| `requirements.txt` | Modify | 新增 `pymysql>=1.1.0` 依赖 |
| `test_agents/config.py` | Modify | 新增数据库连接环境变量（`TEST_AGENTS_DB_URL`、`TEST_AGENTS_DB_QUERY_TIMEOUT`、`TEST_AGENTS_DB_MAX_ROWS`、`TEST_AGENTS_SCHEMA_DIR`） |
| `test_agents/tools/database.py` | Create | `QueryDatabaseTool` — MySQL 只读查询，SQL 白名单校验，LIMIT 截断，超时控制 |
| `test_agents/tools/schema_loader.py` | Create | `SchemaDescriptionTool` — 从 `data/schema/*.md` 加载表结构描述 |
| `test_agents/tools/__init__.py` | Modify | 追加两个 import 触发自动注册 |
| `test_agents/prompts/data_analyst.md` | Create | Data Analyst Worker 系统 Prompt（计划引导 + SQL 规范 + 输出要求） |
| `test_agents/agents/data_analyst.py` | Create | `data_analyst` Worker 包装器（与 `code_analyzer.py` 平行） |
| `test_agents/agents/supervisor.py` | Modify | `route_from_dispatch` 增加 `data_analyst` 分支 |
| `test_agents/graph/builder.py` | Modify | 注册 `data_analyst` Worker，路由增加 `data_analyst` 分支 |
| `test_agents/data/schema/` | Create | Schema 描述文件目录 |
| `test_agents/data/schema/defects.md` | Create | 示例：defects 表结构描述 |
| `test_agents/tests/test_database_tool.py` | Create | `QueryDatabaseTool` 单元测试（SQL 白名单、LIMIT 截断、超时、结果转 Markdown） |
| `test_agents/tests/test_schema_loader.py` | Create | `SchemaDescriptionTool` 单元测试（加载文件、缺失表、多表概览） |
| `test_agents/tests/test_data_analyst.py` | Create | `data_analyst_wrapper` Worker 测试 |
| `test_agents/tests/test_builder.py` | Modify | 扩展：验证 graph 包含 `data_analyst` 节点 |
| `test_agents/tests/test_supervisor.py` | Modify | 扩展：验证 `route_from_dispatch` 路由 `data_analyst` |
| `test_agents/tests/test_prompts.py` | Modify | 扩展：验证 `data_analyst` prompt 可加载 |

---

## Task 1: 添加 pymysql 依赖与数据库配置

**Files:**
- Modify: `requirements.txt`
- Modify: `test_agents/config.py`

- [ ] **Step 1: 在 requirements.txt 新增 pymysql**

修改 `requirements.txt`，在末尾追加：

```
pymysql>=1.1.0
```

完整文件应为：
```
langgraph>=0.2.0
langchain-core>=0.3.0
langchain-openai>=0.2.0
pydantic>=2.0.0
pytest>=8.0.0
pymysql>=1.1.0
```

- [ ] **Step 2: 安装依赖**

Run: `pip install pymysql>=1.1.0`
Expected: `Successfully installed pymysql-1.x.x`

- [ ] **Step 3: 在 config.py 新增数据库配置**

修改 `test_agents/config.py`，在 `EXPERIENCE_FILE` 下方追加：

```python
    # 数据库配置（data_analyst Worker）
    DB_URL: str = os.getenv("TEST_AGENTS_DB_URL", "")
    DB_QUERY_TIMEOUT: int = int(os.getenv("TEST_AGENTS_DB_QUERY_TIMEOUT", "30"))
    DB_MAX_ROWS: int = int(os.getenv("TEST_AGENTS_DB_MAX_ROWS", "500"))
    SCHEMA_DIR: str = os.getenv(
        "TEST_AGENTS_SCHEMA_DIR",
        os.path.join(os.path.dirname(__file__), "data", "schema"),
    )
```

完整 `Config` 类应为（新增部分用 `# --- NEW ---` 标记）：

```python
class Config:
    """配置类"""

    # LLM 配置
    LLM_MODEL: str = os.getenv("TEST_AGENTS_MODEL", "kimi-k2.6")
    LLM_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    LLM_BASE_URL: Optional[str] = os.getenv("OPENAI_BASE_URL")

    # Claude CLI 配置
    CLAUDE_TIMEOUT: int = int(os.getenv("TEST_AGENTS_CLAUDE_TIMEOUT", "1200"))
    CLAUDE_MAX_RETRIES: int = int(os.getenv("TEST_AGENTS_CLAUDE_RETRIES", "1"))

    # 业务知识库路径
    KNOWLEDGE_DIR: str = os.getenv("TEST_AGENTS_KNOWLEDGE_DIR", "")

    # v3 Plan-and-Solve + Reflection 配置
    MAX_PLAN_ITERATIONS: int = int(os.getenv("TEST_AGENTS_MAX_PLAN_ITERATIONS", "1"))
    MAX_CONFIRM_RETRIES: int = int(os.getenv("TEST_AGENTS_MAX_CONFIRM_RETRIES", "1"))
    MAX_WORKER_REFLECTIONS: int = int(os.getenv("TEST_AGENTS_MAX_WORKER_REFLECTIONS", "0"))
    EXPERIENCE_FILE: str = os.getenv(
        "TEST_AGENTS_EXPERIENCE_FILE",
        os.path.join(os.path.dirname(__file__), "data", "reflection_experience.md"),
    )

    # 可观测体系配置（spec §6）
    LOG_LEVEL: str = os.getenv("TEST_AGENTS_LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("TEST_AGENTS_LOG_DIR", "logs")
    LOG_TRACE_FILES: bool = os.getenv("TEST_AGENTS_LOG_TRACE_FILES", "true").lower() == "true"
    LOG_TRACES_KEEP: int = int(os.getenv("TEST_AGENTS_LOG_TRACES_KEEP", "1000"))
    LOG_RETAIN_DAYS: int = int(os.getenv("TEST_AGENTS_LOG_RETAIN_DAYS", "30"))
    LOG_TRACE_HANDLES: int = int(os.getenv("TEST_AGENTS_LOG_TRACE_HANDLES", "64"))

    # --- NEW ---
    # 数据库配置（data_analyst Worker）
    DB_URL: str = os.getenv("TEST_AGENTS_DB_URL", "")
    DB_QUERY_TIMEOUT: int = int(os.getenv("TEST_AGENTS_DB_QUERY_TIMEOUT", "30"))
    DB_MAX_ROWS: int = int(os.getenv("TEST_AGENTS_DB_MAX_ROWS", "500"))
    SCHEMA_DIR: str = os.getenv(
        "TEST_AGENTS_SCHEMA_DIR",
        os.path.join(os.path.dirname(__file__), "data", "schema"),
    )
```

- [ ] **Step 4: 运行 config 测试确认无回归**

Run: `python -m pytest test_agents/tests/test_config.py -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add requirements.txt test_agents/config.py
git commit -m "feat(db): add pymysql dependency and database config"
```

---

## Task 2: 创建 QueryDatabaseTool（TDD）

**Files:**
- Create: `test_agents/tools/database.py`
- Create: `test_agents/tests/test_database_tool.py`

- [ ] **Step 1: 写失败测试（SQL 白名单 + LIMIT + 结果转 Markdown）**

创建 `test_agents/tests/test_database_tool.py`：

```python
"""Tests for QueryDatabaseTool"""
from unittest.mock import MagicMock, patch

import pytest

from test_agents.tools.database import QueryDatabaseTool, _validate_sql, _add_limit, _results_to_markdown


class TestValidateSql:
    def test_valid_select_passes(self):
        valid, err = _validate_sql("SELECT * FROM users")
        assert valid is True
        assert err == ""

    def test_insert_rejected(self):
        valid, err = _validate_sql("INSERT INTO users VALUES (1)")
        assert valid is False
        assert "must start with SELECT" in err

    def test_update_rejected(self):
        valid, err = _validate_sql("UPDATE users SET name='x'")
        assert valid is False
        assert "must start with SELECT" in err

    def test_delete_rejected(self):
        valid, err = _validate_sql("DELETE FROM users")
        assert valid is False
        assert "must start with SELECT" in err

    def test_forbidden_keyword_detected(self):
        valid, err = _validate_sql("SELECT * FROM users; DROP TABLE users")
        assert valid is False
        assert "forbidden keyword" in err

    def test_semicolon_rejected(self):
        valid, err = _validate_sql("SELECT 1; SELECT 2")
        assert valid is False
        assert "multiple statements" in err

    def test_comment_rejected(self):
        valid, err = _validate_sql("SELECT * FROM users -- comment")
        assert valid is False
        assert "comments not allowed" in err

    def test_block_comment_rejected(self):
        valid, err = _validate_sql("SELECT * /* comment */ FROM users")
        assert valid is False
        assert "comments not allowed" in err

    def test_case_insensitive_select(self):
        valid, err = _validate_sql("select * from users")
        assert valid is True
        assert err == ""


class TestAddLimit:
    def test_adds_limit_when_missing(self):
        result = _add_limit("SELECT * FROM users", max_rows=500)
        assert result == "SELECT * FROM users LIMIT 500"

    def test_keeps_existing_limit_under_max(self):
        result = _add_limit("SELECT * FROM users LIMIT 100", max_rows=500)
        assert result == "SELECT * FROM users LIMIT 100"

    def test_truncates_limit_over_max(self):
        result = _add_limit("SELECT * FROM users LIMIT 1000", max_rows=500)
        assert result == "SELECT * FROM users LIMIT 500"

    def test_truncates_case_insensitive(self):
        result = _add_limit("SELECT * FROM users limit 1000", max_rows=500)
        assert result == "SELECT * FROM users LIMIT 500"


class TestResultsToMarkdown:
    def test_empty_results(self):
        result = _results_to_markdown([], [])
        assert result == "No data found for the given criteria."

    def test_single_row(self):
        result = _results_to_markdown([("id", "name")], [(1, "alice")])
        assert "| id | name |" in result
        assert "| 1 | alice |" in result

    def test_multiple_rows(self):
        result = _results_to_markdown(
            [("a", "b")], [(1, 2), (3, 4)]
        )
        lines = result.strip().split("\n")
        assert len(lines) == 4  # header, separator, row1, row2


class TestQueryDatabaseTool:
    def test_sql_rejection_without_db_call(self):
        """非 SELECT SQL 不触发任何数据库连接"""
        tool = QueryDatabaseTool()
        with patch("test_agents.tools.database.pymysql.connect") as mock_connect:
            result = tool.invoke({"query": "DELETE FROM users"})
            mock_connect.assert_not_called()
        assert "SQL rejected" in result

    def test_empty_result_returns_message(self):
        tool = QueryDatabaseTool()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = []
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("test_agents.tools.database.pymysql.connect", return_value=mock_conn):
            result = tool.invoke({"query": "SELECT * FROM empty_table"})

        assert "No data found" in result

    def test_successful_query_returns_markdown(self):
        tool = QueryDatabaseTool()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "alice"), (2, "bob")]
        mock_cursor.description = [("id",), ("name",)]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("test_agents.tools.database.pymysql.connect", return_value=mock_conn):
            result = tool.invoke({"query": "SELECT id, name FROM users"})

        assert "| id | name |" in result
        assert "| 1 | alice |" in result
        assert "| 2 | bob |" in result

    def test_query_timeout_returns_error(self):
        tool = QueryDatabaseTool()

        with patch("test_agents.tools.database.pymysql.connect") as mock_connect:
            mock_connect.side_effect = Exception("Connection timeout")
            result = tool.invoke({"query": "SELECT * FROM users"})

        assert "Database connection failed" in result

    def test_sql_execution_error_returns_message(self):
        tool = QueryDatabaseTool()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("Table 'users' doesn't exist")
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("test_agents.tools.database.pymysql.connect", return_value=mock_conn):
            result = tool.invoke({"query": "SELECT * FROM users"})

        assert "SQL error" in result

    def test_limit_auto_appended(self):
        tool = QueryDatabaseTool()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = []
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("test_agents.tools.database.pymysql.connect", return_value=mock_conn):
            tool.invoke({"query": "SELECT * FROM users"})

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "LIMIT 500" in executed_sql

    def test_truncated_result_warning(self):
        tool = QueryDatabaseTool()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # Simulate 500 rows returned (at the limit)
        mock_cursor.fetchall.return_value = [(i,) for i in range(500)]
        mock_cursor.description = [("id",)]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("test_agents.tools.database.pymysql.connect", return_value=mock_conn):
            result = tool.invoke({"query": "SELECT id FROM users"})

        assert "结果已截断" in result or "⚠️" in result
```

- [ ] **Step 2: 运行测试确认全部失败**

Run: `python -m pytest test_agents/tests/test_database_tool.py -v`
Expected: 全部 FAIL（`ImportError` 或 `module not found`）

- [ ] **Step 3: 实现 QueryDatabaseTool**

创建 `test_agents/tools/database.py`：

```python
"""MySQL 只读查询工具"""

import re

import pymysql

from test_agents.config import config
from test_agents.tools.base import TestAgentTool


_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|CALL|"
    r"INTO\s+OUTFILE|LOAD_FILE)\b",
    re.IGNORECASE,
)


def _validate_sql(query: str) -> tuple[bool, str]:
    """SQL 安全校验：只允许 SELECT，禁止危险关键字和注释。"""
    cleaned = query.strip()

    if not cleaned.upper().startswith("SELECT"):
        return False, "SQL rejected: query must start with SELECT"

    if _FORBIDDEN_KEYWORDS.search(cleaned):
        return False, "SQL rejected: forbidden keyword detected"

    if ";" in cleaned:
        return False, "SQL rejected: multiple statements not allowed"

    if "--" in cleaned or "/*" in cleaned:
        return False, "SQL rejected: comments not allowed"

    return True, ""


def _add_limit(query: str, max_rows: int = 500) -> str:
    """如无 LIMIT 则自动追加；有 LIMIT 则截断到 max_rows。"""
    limit_match = re.search(r"\bLIMIT\s+(\d+)\s*$", query, re.IGNORECASE)
    if limit_match:
        existing = int(limit_match.group(1))
        if existing > max_rows:
            return query[: limit_match.start()] + f" LIMIT {max_rows}"
        return query
    return f"{query} LIMIT {max_rows}"


def _results_to_markdown(rows: list[tuple], description: list[tuple]) -> str:
    """将 pymysql 查询结果转为 Markdown 表格。"""
    if not rows:
        return "No data found for the given criteria."

    headers = [desc[0] for desc in description]
    header_line = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"

    body_lines = []
    for row in rows:
        cells = [str(cell) if cell is not None else "" for cell in row]
        body_lines.append("| " + " | ".join(cells) + " |")

    return "\n".join([header_line, separator] + body_lines)


class QueryDatabaseTool(TestAgentTool):
    """执行 MySQL 只读 SQL 查询，返回 Markdown 表格格式结果。"""

    name: str = "query_database"
    description: str = (
        "执行 MySQL 只读 SQL 查询，返回 Markdown 表格。"
        "只接受 SELECT 语句，会自动追加 LIMIT 500。"
    )

    def _run(self, query: str) -> str:
        """执行 SQL 查询并返回结果。"""
        # 安全校验
        is_valid, error = _validate_sql(query)
        if not is_valid:
            return error

        # 自动限制行数
        safe_query = _add_limit(query, max_rows=config.DB_MAX_ROWS)

        # 检查是否配置了数据库连接
        if not config.DB_URL:
            return "Database connection failed: TEST_AGENTS_DB_URL is not configured"

        try:
            conn = pymysql.connect(
                host=self._parse_host(config.DB_URL),
                user=self._parse_user(config.DB_URL),
                password=self._parse_password(config.DB_URL),
                database=self._parse_database(config.DB_URL),
                port=self._parse_port(config.DB_URL),
                connect_timeout=10,
                read_timeout=config.DB_QUERY_TIMEOUT,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.Cursor,
            )
        except Exception as e:
            return f"Database connection failed: {e}"

        try:
            with conn.cursor() as cursor:
                cursor.execute(safe_query)
                rows = cursor.fetchall()
                description = cursor.description or []

                result = _results_to_markdown(rows, description)

                # 如果结果可能达到上限，追加截断提示
                if len(rows) >= config.DB_MAX_ROWS:
                    result += (
                        f"\n\n⚠️ 结果已截断至 {config.DB_MAX_ROWS} 行，"
                        "请添加更严格的过滤条件。"
                    )

                return result
        except Exception as e:
            return f"SQL error: {e}"
        finally:
            conn.close()

    # --- 简单的 URL 解析辅助方法 ---
    def _parse_host(self, url: str) -> str:
        # mysql+pymysql://user:pass@host:port/db
        m = re.match(r"mysql\+pymysql://[^:]+:[^@]+@([^:/]+)", url)
        return m.group(1) if m else "localhost"

    def _parse_user(self, url: str) -> str:
        m = re.match(r"mysql\+pymysql://([^:]+):", url)
        return m.group(1) if m else ""

    def _parse_password(self, url: str) -> str:
        m = re.match(r"mysql\+pymysql://[^:]+:([^@]+)@", url)
        return m.group(1) if m else ""

    def _parse_database(self, url: str) -> str:
        m = re.match(r"mysql\+pymysql://[^/]+/([^?]+)", url)
        return m.group(1) if m else ""

    def _parse_port(self, url: str) -> int:
        m = re.search(r"@([^:]+):(\d+)", url)
        return int(m.group(2)) if m else 3306
```

- [ ] **Step 4: 运行测试确认全部通过**

Run: `python -m pytest test_agents/tests/test_database_tool.py -v`
Expected: 全部 PASS（14 条用例）

- [ ] **Step 5: Commit**

```bash
git add test_agents/tools/database.py test_agents/tests/test_database_tool.py
git commit -m "feat(db): add QueryDatabaseTool with SQL whitelist and LIMIT guard"
```

---

## Task 3: 创建 SchemaDescriptionTool（TDD）

**Files:**
- Create: `test_agents/tools/schema_loader.py`
- Create: `test_agents/tests/test_schema_loader.py`
- Create: `test_agents/data/schema/defects.md`

- [ ] **Step 1: 写失败测试**

创建 `test_agents/tests/test_schema_loader.py`：

```python
"""Tests for SchemaDescriptionTool"""
import os

import pytest

from test_agents.tools.schema_loader import SchemaDescriptionTool


class TestSchemaDescriptionTool:
    def test_describe_specific_table(self, tmp_path, monkeypatch):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "defects.md").write_text("# defects 表\n存储缺陷数据。\n")

        monkeypatch.setattr(
            "test_agents.tools.schema_loader.config.SCHEMA_DIR", str(schema_dir)
        )

        tool = SchemaDescriptionTool()
        result = tool.invoke({"table_name": "defects"})
        assert "defects 表" in result

    def test_describe_missing_table_returns_list(self, tmp_path, monkeypatch):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "users.md").write_text("# users 表\n")
        (schema_dir / "orders.md").write_text("# orders 表\n")

        monkeypatch.setattr(
            "test_agents.tools.schema_loader.config.SCHEMA_DIR", str(schema_dir)
        )

        tool = SchemaDescriptionTool()
        result = tool.invoke({"table_name": "nonexistent"})
        assert "未找到" in result
        assert "users" in result
        assert "orders" in result

    def test_describe_all_tables(self, tmp_path, monkeypatch):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "defects.md").write_text("# defects\n")
        (schema_dir / "coverage.md").write_text("# coverage\n")

        monkeypatch.setattr(
            "test_agents.tools.schema_loader.config.SCHEMA_DIR", str(schema_dir)
        )

        tool = SchemaDescriptionTool()
        result = tool.invoke({"table_name": ""})
        assert "defects" in result
        assert "coverage" in result

    def test_empty_schema_dir(self, tmp_path, monkeypatch):
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        monkeypatch.setattr(
            "test_agents.tools.schema_loader.config.SCHEMA_DIR", str(schema_dir)
        )

        tool = SchemaDescriptionTool()
        result = tool.invoke({"table_name": ""})
        assert "暂无表结构描述" in result
```

- [ ] **Step 2: 运行测试确认全部失败**

Run: `python -m pytest test_agents/tests/test_schema_loader.py -v`
Expected: 全部 FAIL（ImportError）

- [ ] **Step 3: 实现 SchemaDescriptionTool**

创建 `test_agents/tools/schema_loader.py`：

```python
"""Schema 描述加载工具"""

import os

from test_agents.config import config
from test_agents.tools.base import TestAgentTool


class SchemaDescriptionTool(TestAgentTool):
    """加载数据库表结构描述文件，帮助 Agent 理解可用字段。"""

    name: str = "describe_schema"
    description: str = (
        "返回数据库表结构描述。传入 table_name 获取指定表描述，"
        "不传则返回所有可用表的概览列表。"
    )

    def _run(self, table_name: str = "") -> str:
        schema_dir = config.SCHEMA_DIR

        if not os.path.isdir(schema_dir):
            return f"Schema 描述目录不存在: {schema_dir}"

        # 收集所有 .md 文件
        md_files = [
            f for f in os.listdir(schema_dir)
            if f.endswith(".md")
        ]
        md_files.sort()

        if not md_files:
            return "暂无表结构描述文件。"

        # 不传 table_name，返回概览
        if not table_name:
            lines = ["# 可用数据表概览\n"]
            for f in md_files:
                table = f[:-3]  # 去掉 .md
                lines.append(f"- {table}")
            lines.append("\n如需查看某张表的详细结构，请传入 table_name。")
            return "\n".join(lines)

        # 查找指定表
        target_file = f"{table_name}.md"
        if target_file not in md_files:
            lines = [f"未找到表 '{table_name}' 的描述文件。\n"]
            lines.append("可用表列表：")
            for f in md_files:
                lines.append(f"- {f[:-3]}")
            return "\n".join(lines)

        # 返回文件内容
        file_path = os.path.join(schema_dir, target_file)
        with open(file_path, "r", encoding="utf-8") as fh:
            return fh.read()
```

- [ ] **Step 4: 创建示例 schema 文件**

创建目录和示例文件：

```bash
mkdir -p test_agents/data/schema
```

创建 `test_agents/data/schema/defects.md`：

```markdown
# 表：defects（缺陷表）

## 用途
存储测试过程中发现的缺陷记录。

## 字段

| 字段名 | 类型 | 含义 |
|---|---|---|
| id | INT | 缺陷唯一编号 |
| module | VARCHAR(64) | 所属模块，如 'payment', 'order', 'user' |
| title | VARCHAR(256) | 缺陷标题 |
| severity | ENUM('critical', 'major', 'minor', 'trivial') | 严重程度 |
| status | ENUM('new', 'in_progress', 'resolved', 'closed', 'reopened') | 状态 |
| created_at | DATETIME | 创建时间 |
| resolved_at | DATETIME | 修复时间（未修复为空）|

## 常用查询

- 按模块统计缺陷数：`SELECT module, COUNT(*) FROM defects GROUP BY module`
- 严重缺陷趋势：`SELECT DATE(created_at), COUNT(*) FROM defects WHERE severity='critical' GROUP BY DATE(created_at)`

## 注意事项
- `resolved_at` 可能为 NULL，计算修复时长时需处理
- `status` 变更需关联操作日志表 `defect_history`
```

- [ ] **Step 5: 运行测试确认全部通过**

Run: `python -m pytest test_agents/tests/test_schema_loader.py -v`
Expected: 全部 PASS（4 条用例）

- [ ] **Step 6: Commit**

```bash
git add test_agents/tools/schema_loader.py test_agents/tests/test_schema_loader.py test_agents/data/schema/defects.md
git commit -m "feat(db): add SchemaDescriptionTool and sample schema docs"
```

---

## Task 4: 注册新工具

**Files:**
- Modify: `test_agents/tools/__init__.py`

- [ ] **Step 1: 追加 import 触发自动注册**

修改 `test_agents/tools/__init__.py`，在末尾追加两行：

```python
from test_agents.tools.database import QueryDatabaseTool
from test_agents.tools.schema_loader import SchemaDescriptionTool
```

完整文件应为：

```python
from test_agents.tools.base import ToolRegistry, TestAgentTool
from test_agents.tools.claude_cli import ClaudeCliTool
from test_agents.tools.test_case_parser import TestCaseParserTool
from test_agents.tools.business_knowledge import BusinessKnowledgeTool
from test_agents.tools.fs.read_file import ReadFileTool
from test_agents.tools.fs.list_dir import ListDirTool
from test_agents.tools.fs.grep import GrepTool
from test_agents.tools.fs.glob import GlobTool
from test_agents.tools.database import QueryDatabaseTool
from test_agents.tools.schema_loader import SchemaDescriptionTool
```

- [ ] **Step 2: 验证工具注册**

Run: `python -c "from test_agents.tools.base import ToolRegistry; print([t.name for t in ToolRegistry.get_all()])"`
Expected: 输出包含 `query_database` 和 `describe_schema`

- [ ] **Step 3: Commit**

```bash
git add test_agents/tools/__init__.py
git commit -m "chore(tools): register QueryDatabaseTool and SchemaDescriptionTool"
```

---

## Task 5: 创建 data_analyst 系统 Prompt

**Files:**
- Create: `test_agents/prompts/data_analyst.md`
- Modify: `test_agents/tests/test_prompts.py`

- [ ] **Step 1: 创建 Prompt 文件**

创建 `test_agents/prompts/data_analyst.md`：

```markdown
# 角色
你是测试数据分析师，专注于从 MySQL 数据库中提取测试相关的数据洞察。

# 工作流程（必须遵守）
1. **制定分析计划**：在调用任何工具前，先明确回答以下问题：
   - 需要查询哪些表？
   - 需要计算哪些关键指标？
   - 时间范围和过滤条件是什么？
   将计划写入你的 reasoning。
2. **探索表结构**：如果不确定字段含义，先调用 `describe_schema`。
3. **执行查询**：一次可执行一条 SQL，根据结果决定是否需要补充查询。
4. **生成报告**：汇总所有查询结果，输出自然语言洞察报告。

# 可用工具
- `query_database`: 执行 MySQL 只读查询，传入 {"query": "SELECT ..."}
- `describe_schema`: 获取表结构描述，传入 {"table_name": "表名"}（不传返回所有表概览）

# SQL 规范
- 只生成 SELECT 语句，禁止任何写操作
- 复杂查询优先使用 JOIN 和聚合函数
- 时间范围过滤必须包含，避免全表扫描
- 如无 LIMIT，系统会自动追加 LIMIT 500

# 输出要求
- 自然语言报告，包含数据结论、趋势判断和风险提示
- 如果查询无结果，明确说明"未找到符合条件的数据"，不得猜测
- 报告结构建议：摘要 → 关键发现 → 趋势分析 → 风险建议

# 安全提醒
- 你生成的 SQL 会经过安全校验，非 SELECT 语句会被拒绝
- 如果 SQL 被拒绝，请检查是否包含写操作或危险关键字
```

- [ ] **Step 2: 扩展 prompt 测试**

修改 `test_agents/tests/test_prompts.py`，在末尾追加：

```python
def test_data_analyst_prompt_loads():
    prompt = load_prompt("data_analyst")
    assert "测试数据分析师" in prompt
    assert "query_database" in prompt
    assert "describe_schema" in prompt
```

- [ ] **Step 3: 运行测试**

Run: `python -m pytest test_agents/tests/test_prompts.py::test_data_analyst_prompt_loads -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add test_agents/prompts/data_analyst.md test_agents/tests/test_prompts.py
git commit -m "feat(db): add data_analyst system prompt and load test"
```

---

## Task 6: 创建 data_analyst Worker（TDD）

**Files:**
- Create: `test_agents/agents/data_analyst.py`
- Create: `test_agents/tests/test_data_analyst.py`

- [ ] **Step 1: 写失败测试**

创建 `test_agents/tests/test_data_analyst.py`：

```python
"""Tests for data_analyst worker"""
from unittest.mock import MagicMock, patch

import pytest

from test_agents.agents.data_analyst import (
    build_data_analyst_graph,
    data_analyst_wrapper,
)


class TestBuildDataAnalystGraph:
    def test_builds_graph(self):
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        graph = build_data_analyst_graph(mock_llm, mock_llm_with_tools)
        assert graph is not None


class TestDataAnalystWrapper:
    def test_no_worker_input_returns_empty(self):
        state = {}
        result = data_analyst_wrapper(state)
        assert result == {}

    def test_graph_not_initialized_raises(self):
        from test_agents.agents.data_analyst import data_analyst_graph
        # Reset global to None for this test
        import test_agents.agents.data_analyst as da_module
        original = da_module.data_analyst_graph
        da_module.data_analyst_graph = None
        try:
            state = {"worker_input": {"task": "test", "messages": [], "output_key": "report"}}
            with pytest.raises(RuntimeError, match="data_analyst_graph not initialized"):
                data_analyst_wrapper(state)
        finally:
            da_module.data_analyst_graph = original

    def test_successful_invocation(self):
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "result": "## 数据分析报告\n\n缺陷数上升。",
            "messages": [],
        }

        import test_agents.agents.data_analyst as da_module
        original = da_module.data_analyst_graph
        da_module.data_analyst_graph = mock_graph
        try:
            state = {
                "worker_input": {
                    "task": "分析缺陷趋势",
                    "messages": [],
                    "output_key": "data_insight_report",
                    "error": "no",
                    "reflection_count": 0,
                    "max_reflections": 0,
                    "result": "",
                },
                "outputs": {},
                "current_step_index": 0,
                "plan": {
                    "steps": [
                        {"step_id": 1, "agent": "data_analyst", "input_mapping": {}}
                    ]
                },
            }
            result = data_analyst_wrapper(state)
            assert "outputs" in result
            assert "data_insight_report" in result["outputs"]
            assert "缺陷数上升" in result["outputs"]["data_insight_report"]
            assert result["current_step_index"] == 1
        finally:
            da_module.data_analyst_graph = original
```

- [ ] **Step 2: 运行测试确认全部失败**

Run: `python -m pytest test_agents/tests/test_data_analyst.py -v`
Expected: 全部 FAIL（ImportError）

- [ ] **Step 3: 实现 data_analyst Worker**

创建 `test_agents/agents/data_analyst.py`：

```python
"""Data analyst worker - ReAct subgraph with QueryDatabaseTool + SchemaDescriptionTool"""

from test_agents.agents.worker_base import build_worker_graph, aggregate_worker_result
from test_agents.graph.state import SupervisorState
from test_agents.prompts.loader import load_prompt
from test_agents.tools.base import ToolRegistry


_data_analyst_tools = ToolRegistry.get_tools_by_names(
    ["query_database", "describe_schema"]
)
data_analyst_graph = None


def build_data_analyst_graph(llm, llm_with_tools):
    """Build and cache the data analyst subgraph"""
    global data_analyst_graph
    data_analyst_graph = build_worker_graph(
        _data_analyst_tools,
        llm,
        llm_with_tools,
        system_prompt=load_prompt("data_analyst"),
    )
    return data_analyst_graph


def data_analyst_wrapper(state: SupervisorState) -> dict:
    """Data analyst node - thin adapter around worker subgraph."""
    worker_input = state.get("worker_input")
    if not worker_input:
        return {}
    if data_analyst_graph is None:
        raise RuntimeError(
            "data_analyst_graph not initialized. Call build_data_analyst_graph first."
        )
    result = data_analyst_graph.invoke(worker_input)
    return aggregate_worker_result(
        state, result, worker_input["output_key"], "data_analyst"
    )
```

- [ ] **Step 4: 运行测试确认全部通过**

Run: `python -m pytest test_agents/tests/test_data_analyst.py -v`
Expected: 全部 PASS（3 条用例）

- [ ] **Step 5: Commit**

```bash
git add test_agents/agents/data_analyst.py test_agents/tests/test_data_analyst.py
git commit -m "feat(db): add data_analyst worker with database tools"
```

---

## Task 7: 修改 Supervisor 路由与 Graph Builder

**Files:**
- Modify: `test_agents/agents/supervisor.py`
- Modify: `test_agents/graph/builder.py`
- Modify: `test_agents/tests/test_supervisor.py`
- Modify: `test_agents/tests/test_builder.py`

- [ ] **Step 1: 修改 supervisor.py 路由**

修改 `test_agents/agents/supervisor.py` 中 `route_from_dispatch` 函数：

```python
def route_from_dispatch(state: SupervisorState) -> Literal["code_analyzer", "case_reviewer", "data_analyst", "reflect"]:
    """Route after dispatch: more steps→worker, all done→reflect"""
    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)

    if current_index >= len(steps):
        return "reflect"

    agent = steps[current_index].get("agent", "")
    if agent == "code_analyzer":
        return "code_analyzer"
    elif agent == "case_reviewer":
        return "case_reviewer"
    elif agent == "data_analyst":
        return "data_analyst"
    return "reflect"
```

**注意：** 返回类型注解从 `Literal["code_analyzer", "case_reviewer", "reflect"]` 改为 `Literal["code_analyzer", "case_reviewer", "data_analyst", "reflect"]`。

- [ ] **Step 2: 修改 builder.py 注册 data_analyst**

修改 `test_agents/graph/builder.py`：

在 imports 中新增：
```python
from test_agents.agents.data_analyst import (
    build_data_analyst_graph,
    data_analyst_wrapper,
)
```

在 `build_graph()` 中新增：
```python
def build_graph():
    """Build and compile the supervisor graph with worker subgraphs"""
    llm = get_llm()

    code_analyzer_tools = _get_code_analyzer_tools()
    case_reviewer_tools = _get_case_reviewer_tools()
    data_analyst_tools = _get_data_analyst_tools()

    llm_with_ca_tools = llm.bind_tools(code_analyzer_tools)
    llm_with_cr_tools = llm.bind_tools(case_reviewer_tools)
    llm_with_da_tools = llm.bind_tools(data_analyst_tools)

    code_analyzer_graph = build_code_analyzer_graph(llm, llm_with_ca_tools)
    case_reviewer_graph = build_case_reviewer_graph(llm, llm_with_cr_tools)
    data_analyst_graph = build_data_analyst_graph(llm, llm_with_da_tools)
    WORKER_REGISTRY["code_analyzer"] = code_analyzer_graph
    WORKER_REGISTRY["case_reviewer"] = case_reviewer_graph
    WORKER_REGISTRY["data_analyst"] = data_analyst_graph

    graph = StateGraph(SupervisorState)

    # Add nodes
    graph.add_node("planner", planner_node)
    graph.add_node("confirm_plan", confirm_plan_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("code_analyzer", code_analyzer_wrapper)
    graph.add_node("case_reviewer", case_reviewer_wrapper)
    graph.add_node("data_analyst", data_analyst_wrapper)
    graph.add_node("reflect", reflect_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("save_experience", save_experience_node)
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("reply", reply_node)

    # Fixed edges
    graph.add_edge(START, "intent_classifier")
    graph.add_edge("reply", END)
    graph.add_edge("code_analyzer", "dispatch")
    graph.add_edge("case_reviewer", "dispatch")
    graph.add_edge("data_analyst", "dispatch")
    graph.add_edge("synthesize", "save_experience")
    graph.add_edge("save_experience", END)

    # Conditional edges
    graph.add_conditional_edges(
        "intent_classifier",
        route_from_classifier,
        {"planner": "planner", "reply": "reply"},
    )

    graph.add_conditional_edges("planner", lambda state: "confirm_plan", {"confirm_plan": "confirm_plan"})

    graph.add_conditional_edges(
        "confirm_plan",
        route_from_confirm,
        {"dispatch": "dispatch", "planner": "planner", "end": END},
    )

    graph.add_conditional_edges(
        "dispatch",
        route_from_dispatch,
        {"code_analyzer": "code_analyzer", "case_reviewer": "case_reviewer", "data_analyst": "data_analyst", "reflect": "reflect"},
    )

    graph.add_conditional_edges(
        "reflect",
        route_from_reflect,
        {"planner": "planner", "synthesize": "synthesize"},
    )

    memory = InMemorySaver()
    return graph.compile(checkpointer=memory)
```

在文件末尾新增 `_get_data_analyst_tools`：

```python
def _get_data_analyst_tools():
    from test_agents.tools.base import ToolRegistry
    return ToolRegistry.get_tools_by_names(["query_database", "describe_schema"])
```

- [ ] **Step 3: 扩展 supervisor 测试**

修改 `test_agents/tests/test_supervisor.py`，在 `TestRouteFromDispatch` 类中追加：

```python
    def test_data_analyst_step(self):
        state: SupervisorState = {
            "plan": {"steps": [{"step_id": 1, "agent": "data_analyst"}]},
            "current_step_index": 0,
        }
        assert route_from_dispatch(state) == "data_analyst"
```

- [ ] **Step 4: 扩展 builder 测试**

修改 `test_agents/tests/test_builder.py`：

在 `test_graph_has_all_nodes` 中，将 `"data_analyst"` 加入 expected 列表：

```python
        for expected in ["intent_classifier", "planner", "confirm_plan", "dispatch",
                         "code_analyzer", "case_reviewer", "data_analyst", "reflect",
                         "synthesize", "save_experience", "reply"]:
            assert expected in node_names, f"Missing node: {expected}"
```

在两个测试函数中增加 `build_data_analyst_graph` 的 patch：

```python
def test_build_graph_returns_compiled_graph():
    with patch("test_agents.graph.builder.get_llm") as mock_get_llm, \
         patch("test_agents.graph.builder.build_code_analyzer_graph") as mock_ca, \
         patch("test_agents.graph.builder.build_case_reviewer_graph") as mock_cr, \
         patch("test_agents.graph.builder.build_data_analyst_graph") as mock_da:
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        mock_get_llm.return_value = mock_llm
        mock_ca.return_value = MagicMock()
        mock_cr.return_value = MagicMock()
        mock_da.return_value = MagicMock()
        graph = build_graph()
        assert graph is not None
```

同样修改 `test_graph_has_all_nodes` 和 `test_graph_starts_at_intent_classifier`。

- [ ] **Step 5: 运行测试确认无回归**

Run: `python -m pytest test_agents/tests/test_supervisor.py test_agents/tests/test_builder.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add test_agents/agents/supervisor.py test_agents/graph/builder.py test_agents/tests/test_supervisor.py test_agents/tests/test_builder.py
git commit -m "feat(db): wire data_analyst worker into supervisor graph and routing"
```

---

## Task 8: 全局回归测试

**Files:** （无新文件，运行全部测试）

- [ ] **Step 1: 运行全部测试**

Run: `python -m pytest test_agents/tests/ -v`
Expected: 全部 PASS

- [ ] **Step 2: Commit**

```bash
git commit --allow-empty -m "test: verify full test suite passes with data_analyst integration"
```

---

## Self-Review Checklist

### 1. Spec Coverage

| Spec 章节 | 实现任务 | 状态 |
|---|---|---|
| `QueryDatabaseTool` 安全校验（SELECT 白名单、禁止关键字、禁止分号/注释） | Task 2 | 已覆盖 `_validate_sql` + 6 条测试 |
| `QueryDatabaseTool` LIMIT 自动截断 | Task 2 | 已覆盖 `_add_limit` + 4 条测试 |
| `QueryDatabaseTool` 超时控制 | Task 2 | 已覆盖 `_run` 异常处理 + 测试 |
| `QueryDatabaseTool` 结果转 Markdown 表格 | Task 2 | 已覆盖 `_results_to_markdown` + 3 条测试 |
| `QueryDatabaseTool` 行数截断提示 | Task 2 | 已覆盖测试 `test_truncated_result_warning` |
| `SchemaDescriptionTool` 加载指定表 | Task 3 | 已覆盖测试 `test_describe_specific_table` |
| `SchemaDescriptionTool` 缺失表返回列表 | Task 3 | 已覆盖测试 `test_describe_missing_table_returns_list` |
| `SchemaDescriptionTool` 返回全部概览 | Task 3 | 已覆盖测试 `test_describe_all_tables` |
| `data_analyst.md` Prompt | Task 5 | 已创建文件 + 加载测试 |
| `data_analyst` Worker 子图 | Task 6 | 已创建 `data_analyst.py` + 3 条测试 |
| Supervisor 路由增加 `data_analyst` | Task 7 | 已修改 `route_from_dispatch` + 测试 |
| Graph Builder 注册 `data_analyst` | Task 7 | 已修改 `builder.py` + 测试 |
| 环境变量配置 | Task 1 | 已修改 `config.py` + `requirements.txt` |
| Schema 描述示例文件 | Task 3 | 已创建 `defects.md` |

### 2. Placeholder Scan

- [x] 无 "TBD"、"TODO"、"implement later"
- [x] 无 "Add appropriate error handling" 等模糊描述
- [x] 每个代码步骤都包含完整代码
- [x] 每个测试都包含完整断言
- [x] 每个命令都包含预期输出

### 3. Type Consistency

- [x] `route_from_dispatch` 返回类型注解已更新为 `Literal["code_analyzer", "case_reviewer", "data_analyst", "reflect"]`
- [x] `build_worker_graph` 调用签名在各 Worker 中一致
- [x] `aggregate_worker_result` 调用签名一致（`data_analyst` 无 post_processor，与 `code_analyzer` 相同）
- [x] `config.DB_URL`、`config.DB_QUERY_TIMEOUT`、`config.DB_MAX_ROWS`、`config.SCHEMA_DIR` 在 `database.py` 和 `schema_loader.py` 中引用一致

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-02-database-access.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints for review

**Which approach?**