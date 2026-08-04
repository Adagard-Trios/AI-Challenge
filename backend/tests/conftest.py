"""
Pytest Configuration for Roger Intelligence Platform

Provides fixtures and configuration for testing agentic AI components:
- Agent graph fixtures
- Mock LLM for unit testing
- LangSmith integration
- Golden dataset loading
"""

import os
import sys
import pytest
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import MagicMock, patch

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# ENVIRONMENT CONFIGURATION
# =============================================================================


@pytest.fixture(scope="session", autouse=True)
def configure_test_environment():
    """Configure environment for testing (runs once per session)."""
    # Ensure we're in test mode
    os.environ["TESTING"] = "true"

    # Optionally disable LangSmith tracing in unit tests for speed
    # Set LANGSMITH_TRACING_TESTS=true to enable tracing in tests
    if os.getenv("LANGSMITH_TRACING_TESTS", "false").lower() != "true":
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

    yield

    # Cleanup
    os.environ.pop("TESTING", None)


# =============================================================================
# MOCK LLM FIXTURES
# =============================================================================


@pytest.fixture
def mock_llm():
    """
    Provides a mock LLM for testing without API calls.
    Returns predictable responses for deterministic testing.
    """
    mock = MagicMock()
    mock.invoke.return_value = MagicMock(
        content='{"decision": "proceed", "reasoning": "Test response"}'
    )
    return mock


@pytest.fixture
def mock_groq_llm():
    """Mock GroqLLM class for testing agent nodes."""
    with patch("src.llms.groqllm.GroqLLM") as mock_class:
        mock_instance = MagicMock()
        mock_instance.get_llm.return_value = MagicMock()
        mock_class.return_value = mock_instance
        yield mock_class


# =============================================================================
# AGENT FIXTURES
# =============================================================================


@pytest.fixture
def sample_agent_state() -> Dict[str, Any]:
    """Returns a sample CombinedAgentState for testing."""
    return {
        "run_count": 1,
        "last_run_ts": "2024-01-01T00:00:00",
        "domain_insights": [],
        "final_ranked_feed": [],
        "risk_dashboard_snapshot": {},
        "route": None,
    }


@pytest.fixture
def sample_domain_insight() -> Dict[str, Any]:
    """Returns a sample domain insight for testing aggregation."""
    return {
        "title": "Test Flood Warning",
        "summary": "Heavy rainfall expected in Colombo district",
        "source": "DMC",
        "domain": "meteorological",
        "timestamp": "2024-01-01T10:00:00",
        "confidence": 0.85,
        "risk_type": "Flood",
        "severity": "High",
    }


# =============================================================================
# GOLDEN DATASET FIXTURES
# =============================================================================


@pytest.fixture
def golden_dataset_path() -> Path:
    """Returns path to golden datasets directory."""
    return PROJECT_ROOT / "tests" / "evaluation" / "golden_datasets"


@pytest.fixture
def expected_responses(golden_dataset_path) -> List[Dict]:
    """Load expected responses for LLM-as-Judge evaluation."""
    import json

    response_file = golden_dataset_path / "expected_responses.json"
    if response_file.exists():
        with open(response_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


# =============================================================================
# LANGSMITH FIXTURES
# =============================================================================


@pytest.fixture
def langsmith_client():
    """
    Provides LangSmith client for evaluation tests.
    Returns None if not configured.
    """
    try:
        from src.config.langsmith_config import get_langsmith_client

        return get_langsmith_client()
    except ImportError:
        return None


@pytest.fixture
def traced_test(langsmith_client):
    """
    Context manager for traced test execution.
    Automatically logs test runs to LangSmith.
    """
    from contextlib import contextmanager

    @contextmanager
    def _traced_test(test_name: str):
        if langsmith_client:
            # Start a trace run
            pass  # LangSmith auto-traces when configured
        yield

    return _traced_test


# =============================================================================
# TOOL FIXTURES
# =============================================================================


@pytest.fixture
def weather_tool_response() -> str:
    """Sample response from weather tool for testing."""
    import json

    return json.dumps(
        {
            "status": "success",
            "data": {
                "location": "Colombo",
                "temperature": 28,
                "humidity": 75,
                "condition": "Partly Cloudy",
                "rainfall_probability": 30,
            },
        }
    )


@pytest.fixture
def news_tool_response() -> str:
    """Sample response from news tool for testing."""
    import json

    return json.dumps(
        {
            "status": "success",
            "results": [
                {
                    "title": "Economic growth forecast for 2024",
                    "source": "Daily Mirror",
                    "url": "https://example.com/news/1",
                    "published": "2024-01-01",
                }
            ],
        }
    )


# =============================================================================
# TEST MARKERS
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line(
        "markers", "evaluation: marks tests as LLM evaluation tests"
    )
    config.addinivalue_line(
        "markers", "adversarial: marks tests as adversarial/security tests"
    )
