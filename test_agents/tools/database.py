"""数据库查询工具 — 只读 MySQL 查询，带 SQL 白名单和 LIMIT 保护"""

import re

import pymysql
from pydantic import BaseModel, Field

from test_agents.tools.base import TestAgentTool
from test_agents.config import config


_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|CALL|"
    r"INTO\s+OUTFILE|LOAD_FILE)\b",
    re.IGNORECASE,
)


def _validate_sql(query: str) -> tuple[bool, str]:
    """SQL 安全校验：仅允许 SELECT，禁止危险关键字和注释。"""
    stripped = query.strip()

    if _FORBIDDEN_KEYWORDS.search(stripped):
        return False, "SQL rejected: forbidden keyword detected"

    if not re.match(r"(?i)^SELECT\s", stripped):
        return False, "Only SELECT queries are allowed."

    if ";" in stripped:
        return False, "Semicolons are not allowed."

    if "--" in stripped:
        return False, "Line comments (-- ) are not allowed."

    if "/*" in stripped or "*/" in stripped:
        return False, "Block comments (/* */) are not allowed."

    return True, ""


def _add_limit(query: str, max_rows: int = 500) -> str:
    """为缺少 LIMIT 的查询自动追加 LIMIT，或截断过大的 LIMIT。"""
    # 查找已有的 LIMIT（不区分大小写）
    limit_match = re.search(r"(?i)\bLIMIT\s+(\d+)\s*$", query.strip())
    if limit_match:
        current_limit = int(limit_match.group(1))
        if current_limit > max_rows:
            return re.sub(r"(?i)\bLIMIT\s+\d+\s*$", f"LIMIT {max_rows}", query.strip())
        return query.strip()
    return f"{query.strip()} LIMIT {max_rows}"


def _results_to_markdown(rows: list[tuple], description: list[tuple]) -> str:
    """将 pymysql 查询结果转换为 Markdown 表格。"""
    if not rows:
        return "No data found for the given criteria."

    headers = [desc[0] or "" for desc in description]
    header_line = "| " + " | ".join(headers) + " |"
    separator = "|" + "|".join(["---" for _ in headers]) + "|"

    data_lines = []
    for row in rows:
        cells = [str(cell) if cell is not None else "" for cell in row]
        data_lines.append("| " + " | ".join(cells) + " |")

    return "\n".join([header_line, separator] + data_lines)


class QueryDatabaseTool(TestAgentTool):
    name: str = "query_database"
    description: str = (
        "Execute a read-only MySQL query and return results as a Markdown table. "
        "Only SELECT statements are allowed. A LIMIT of 500 rows is automatically applied."
    )

    class InputSchema(BaseModel):
        query: str = Field(description="The SQL SELECT query to execute")

    args_schema: type = InputSchema

    def _run(self, query: str) -> str:
        # a. SQL 校验
        valid, error_msg = _validate_sql(query)
        if not valid:
            return f"Invalid SQL: {error_msg}"

        # b. 自动追加/截断 LIMIT
        safe_query = _add_limit(query, config.DB_MAX_ROWS)

        # c. 检查 DB_URL
        if not config.DB_URL:
            return "Database connection failed: TEST_AGENTS_DB_URL is not configured"

        # d. 解析 DB_URL
        match = re.match(
            r"^mysql\+pymysql://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(.+)$",
            config.DB_URL,
        )
        if not match:
            return "Database connection failed: Invalid DB_URL format"

        user, password, host, port_str, database = match.groups()
        port = int(port_str) if port_str else 3306

        conn = None
        try:
            # e. 连接数据库
            conn = pymysql.connect(
                host=host,
                user=user,
                password=password,
                database=database,
                port=port,
                connect_timeout=10,
                read_timeout=config.DB_QUERY_TIMEOUT,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.Cursor,
            )

            # f. 执行查询
            with conn.cursor() as cursor:
                cursor.execute(safe_query)
                rows = cursor.fetchall()
                description = cursor.description or []

            # g. 转换为 Markdown
            result = _results_to_markdown(rows, description)

            # h. 截断警告
            if len(rows) >= config.DB_MAX_ROWS:
                result += (
                    f"\n\nWarning: Results may be truncated. "
                    f"Only the first {config.DB_MAX_ROWS} rows are returned."
                )

            return result

        except pymysql.err.OperationalError as e:
            return f"Database error: {e}"
        except Exception as e:
            return f"Error executing query: {e}"
        finally:
            # k. 始终关闭连接
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
