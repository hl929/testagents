import pytest
from test_agents.graph.state import TestAgentState


def test_valid_state():
    state = TestAgentState(
        module_name="order",
        source_commit="a1b2c3d",
        target_commit="e4f5a6b",
        commit_msg="fix: update order logic",
        test_cases=[{"case_id": "TC001", "title": "test order creation"}],
    )
    assert state.module_name == "order"


def test_invalid_commit_sha():
    with pytest.raises(ValueError, match="Invalid commit SHA"):
        TestAgentState(
            module_name="order",
            source_commit="invalid!",
            target_commit="e4f5a6b",
            commit_msg="fix",
        )


def test_path_traversal_in_module():
    with pytest.raises(ValueError, match="Invalid module name"):
        TestAgentState(
            module_name="../../etc",
            source_commit="a1b2c3d",
            target_commit="e4f5a6b",
            commit_msg="fix",
        )


def test_test_cases_default_empty():
    state = TestAgentState(
        module_name="order",
        source_commit="a1b2c3d",
        target_commit="e4f5a6b",
        commit_msg="fix",
    )
    assert state.test_cases == []
