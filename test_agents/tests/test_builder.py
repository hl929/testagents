from unittest.mock import MagicMock, patch

from test_agents.graph.builder import build_graph


def test_build_graph_returns_compiled_graph():
    with patch("test_agents.graph.builder.get_llm") as mock_get_llm, \
         patch("test_agents.graph.builder.build_code_analyzer_graph") as mock_ca, \
         patch("test_agents.graph.builder.build_case_reviewer_graph") as mock_cr:
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        mock_get_llm.return_value = mock_llm
        mock_ca.return_value = MagicMock()
        mock_cr.return_value = MagicMock()
        graph = build_graph()
        assert graph is not None


def test_graph_has_all_nodes():
    with patch("test_agents.graph.builder.get_llm") as mock_get_llm, \
         patch("test_agents.graph.builder.build_code_analyzer_graph") as mock_ca, \
         patch("test_agents.graph.builder.build_case_reviewer_graph") as mock_cr:
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        mock_ca.return_value = MagicMock()
        mock_cr.return_value = MagicMock()
        graph = build_graph()
        node_names = set(graph.get_graph().nodes.keys())
        for expected in ["intent_classifier", "planner", "confirm_plan", "dispatch", "code_analyzer", "case_reviewer", "reflect", "synthesize", "save_experience"]:
            assert expected in node_names, f"Missing node: {expected}"


def test_graph_starts_at_intent_classifier():
    with patch("test_agents.graph.builder.get_llm") as mock_get_llm, \
         patch("test_agents.graph.builder.build_code_analyzer_graph") as mock_ca, \
         patch("test_agents.graph.builder.build_case_reviewer_graph") as mock_cr:
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        mock_ca.return_value = MagicMock()
        mock_cr.return_value = MagicMock()
        graph = build_graph()
        g = graph.get_graph()
        # First node after __start__ should be intent_classifier
        edges_from_start = [e for e in g.edges if e[0] == "__start__"]
        assert any("intent_classifier" in str(e) for e in edges_from_start)
