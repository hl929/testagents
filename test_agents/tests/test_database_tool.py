import pytest
from unittest.mock import patch, MagicMock

from test_agents.tools.database import (
    _validate_sql,
    _add_limit,
    _results_to_markdown,
    QueryDatabaseTool,
)


class TestValidateSql:
    def test_valid_select_passes(self):
        assert _validate_sql("SELECT * FROM users") == (True, "")

    def test_insert_rejected(self):
        valid, msg = _validate_sql("INSERT INTO users VALUES (1)")
        assert not valid
        assert "forbidden keyword" in msg.lower()

    def test_update_rejected(self):
        valid, msg = _validate_sql("UPDATE users SET name = 'x'")
        assert not valid
        assert "forbidden keyword" in msg.lower()

    def test_delete_rejected(self):
        valid, msg = _validate_sql("DELETE FROM users")
        assert not valid
        assert "forbidden keyword" in msg.lower()

    def test_forbidden_keyword_detected(self):
        valid, msg = _validate_sql("DROP TABLE users")
        assert not valid
        assert "forbidden keyword" in msg.lower()

    def test_word_boundary_does_not_false_positive(self):
        assert _validate_sql("SELECT * FROM insertions") == (True, "")
        assert _validate_sql("SELECT * FROM updates") == (True, "")
        assert _validate_sql("SELECT * FROM raindrops") == (True, "")

    def test_semicolon_rejected(self):
        valid, msg = _validate_sql("SELECT * FROM users;")
        assert not valid
        assert "semicolon" in msg.lower() or ";" in msg

    def test_comment_rejected(self):
        valid, msg = _validate_sql("SELECT * FROM users -- comment")
        assert not valid
        assert "comment" in msg.lower() or "--" in msg

    def test_block_comment_rejected(self):
        valid, msg = _validate_sql("SELECT * FROM users /* comment */")
        assert not valid
        assert "comment" in msg.lower()

    def test_case_insensitive_select(self):
        assert _validate_sql("select * from users") == (True, "")


class TestAddLimit:
    def test_adds_limit_when_missing(self):
        assert _add_limit("SELECT * FROM users", 500) == "SELECT * FROM users LIMIT 500"

    def test_keeps_existing_limit_under_max(self):
        assert _add_limit("SELECT * FROM users LIMIT 100", 500) == "SELECT * FROM users LIMIT 100"

    def test_truncates_limit_over_max(self):
        assert _add_limit("SELECT * FROM users LIMIT 1000", 500) == "SELECT * FROM users LIMIT 500"

    def test_truncates_case_insensitive(self):
        assert _add_limit("SELECT * FROM users limit 1000", 500) == "SELECT * FROM users LIMIT 500"


class TestResultsToMarkdown:
    def test_empty_results(self):
        assert _results_to_markdown([], []) == "No data found for the given criteria."

    def test_single_row(self):
        rows = [("Alice", 25)]
        desc = [("name",), ("age",)]
        result = _results_to_markdown(rows, desc)
        assert "| name | age |" in result
        assert "|---|---|" in result
        assert "| Alice | 25 |" in result

    def test_multiple_rows(self):
        rows = [("Alice", 25), ("Bob", 30)]
        desc = [("name",), ("age",)]
        result = _results_to_markdown(rows, desc)
        lines = [line for line in result.split("\n") if line.strip()]
        assert len(lines) == 4  # header, separator, 2 data rows


class TestQueryDatabaseTool:
    def _setup_mock_db(self, mock_config, mock_connect, rows=None, desc=None, execute_side_effect=None):
        mock_config.DB_URL = "mysql+pymysql://user:pass@localhost:3306/testdb"
        mock_config.DB_MAX_ROWS = 500
        mock_config.DB_QUERY_TIMEOUT = 30

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows if rows is not None else []
        mock_cursor.description = desc if desc is not None else []
        if execute_side_effect is not None:
            mock_cursor.execute.side_effect = execute_side_effect
        mock_cursor.__enter__.return_value = mock_cursor
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn
        return mock_cursor, mock_conn

    @patch("test_agents.tools.database.config")
    def test_sql_rejection_without_db_call(self, mock_config):
        tool = QueryDatabaseTool()
        with patch("test_agents.tools.database.pymysql.connect") as mock_connect:
            result = tool._run("DROP TABLE users")
            assert "invalid" in result.lower() or "DROP" in result
            mock_connect.assert_not_called()

    @patch("test_agents.tools.database.config")
    def test_empty_result_returns_message(self, mock_config):
        tool = QueryDatabaseTool()
        with patch("test_agents.tools.database.pymysql.connect") as mock_connect:
            self._setup_mock_db(mock_config, mock_connect, rows=[], desc=[("id",), ("name",)])
            result = tool._run("SELECT id, name FROM users WHERE 1=0")
            assert "No data found" in result
            mock_connect.assert_called_once()

    @patch("test_agents.tools.database.config")
    def test_successful_query_returns_markdown(self, mock_config):
        tool = QueryDatabaseTool()
        with patch("test_agents.tools.database.pymysql.connect") as mock_connect:
            self._setup_mock_db(
                mock_config, mock_connect,
                rows=[(1, "Alice"), (2, "Bob")],
                desc=[("id",), ("name",)],
            )
            result = tool._run("SELECT id, name FROM users")
            assert "| id | name |" in result
            assert "| 1 | Alice |" in result
            assert "| 2 | Bob |" in result

    @patch("test_agents.tools.database.config")
    def test_query_timeout_returns_error(self, mock_config):
        tool = QueryDatabaseTool()
        with patch("test_agents.tools.database.pymysql.connect") as mock_connect:
            mock_config.DB_URL = "mysql+pymysql://user:pass@localhost:3306/testdb"
            import pymysql
            mock_connect.side_effect = pymysql.err.OperationalError(2013, "Lost connection")
            result = tool._run("SELECT * FROM users")
            assert "error" in result.lower() or "连接" in result or "failed" in result.lower()

    @patch("test_agents.tools.database.config")
    def test_sql_execution_error_returns_message(self, mock_config):
        tool = QueryDatabaseTool()
        with patch("test_agents.tools.database.pymysql.connect") as mock_connect:
            self._setup_mock_db(
                mock_config, mock_connect,
                rows=[],
                desc=[],
                execute_side_effect=Exception("Syntax error"),
            )
            result = tool._run("SELECT * FROM")
            assert "error" in result.lower() or "syntax" in result.lower()

    @patch("test_agents.tools.database.config")
    def test_limit_auto_appended(self, mock_config):
        tool = QueryDatabaseTool()
        with patch("test_agents.tools.database.pymysql.connect") as mock_connect:
            mock_cursor, _ = self._setup_mock_db(
                mock_config, mock_connect,
                rows=[(1,)],
                desc=[("count",)],
            )
            tool._run("SELECT count(*) FROM users")
            call_args = mock_cursor.execute.call_args[0][0]
            assert "LIMIT" in call_args
            assert "500" in call_args

    @patch("test_agents.tools.database.config")
    def test_truncated_result_warning(self, mock_config):
        tool = QueryDatabaseTool()
        with patch("test_agents.tools.database.pymysql.connect") as mock_connect:
            self._setup_mock_db(
                mock_config, mock_connect,
                rows=[(i,) for i in range(500)],
                desc=[("id",)],
            )
            result = tool._run("SELECT id FROM users")
            assert "truncat" in result.lower() or "warning" in result.lower() or "500" in result
