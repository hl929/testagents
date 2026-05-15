from test_agents.graph.builder import build_graph


def test_graph_builds():
    graph = build_graph()
    assert graph is not None
