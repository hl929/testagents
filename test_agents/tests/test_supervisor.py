from test_agents.agents.supervisor import route_decision


def test_route_to_analyze_when_no_report():
    state = {"code_change_report": "", "test_cases": [{"id": "1"}], "review_results": []}
    assert route_decision(state) == "analyze"


def test_route_to_review_when_has_report_and_cases():
    state = {"code_change_report": "report", "test_cases": [{"id": "1"}], "review_results": []}
    assert route_decision(state) == "review"


def test_route_to_end_when_done():
    state = {"code_change_report": "report", "test_cases": [{"id": "1"}], "review_results": [{"id": "1"}]}
    assert route_decision(state) == "end"


def test_route_to_end_when_no_test_cases():
    state = {"code_change_report": "report", "test_cases": [], "review_results": []}
    assert route_decision(state) == "end"
