"""Shared test fixtures for observability tests.

Resets logger state between tests so that side effects from main.py's
module-top ``setup_logging()`` (which runs once per process and sets
``propagate=False`` on the ``test_agents`` logger) do not leak into tests
that rely on pytest ``caplog`` and the default propagation chain.
"""
import logging
import pytest

from test_agents.observability import logger as logger_mod


@pytest.fixture(autouse=True)
def _restore_test_agents_logger_propagate():
    """Ensure ``test_agents`` logger propagates so caplog can capture records.

    main.py calls ``setup_logging()`` at module import time, which sets
    ``propagate=False`` on the logger. That state persists across tests and
    breaks ``caplog`` for any test that doesn't first call
    ``_reset_for_tests()``. This fixture restores the default before each
    test and after.
    """
    logging.getLogger("test_agents").propagate = True
    yield
    logging.getLogger("test_agents").propagate = True
