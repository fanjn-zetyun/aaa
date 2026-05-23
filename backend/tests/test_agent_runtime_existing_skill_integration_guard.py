import os

import pytest


@pytest.mark.skipif(
    os.environ.get("LOBSTER_RUN_LAB4AI_INTEGRATION") != "1",
    reason="requires explicit Lab4AI integration opt-in",
)
def test_lab4ai_integration_requires_explicit_opt_in():
    assert os.environ["LOBSTER_RUN_LAB4AI_INTEGRATION"] == "1"
