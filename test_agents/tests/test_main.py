from unittest.mock import patch, MagicMock
from test_agents.main import run_test_agents


def test_run_test_agents_with_mock():
    with patch("test_agents.main.build_graph") as mock_build:
        mock_app = MagicMock()
        mock_app.invoke.return_value = {
            "review_results": [{"case_id": "TC001", "verdict": "pass"}]
        }
        mock_build.return_value = mock_app

        result = run_test_agents(
            module_name="order",
            source_commit="a1b2c3d",
            target_commit="e4f5a6b",
            test_cases='[{"case_id": "TC001", "title": "test"}]',
        )

        assert result["review_results"][0]["verdict"] == "pass"
