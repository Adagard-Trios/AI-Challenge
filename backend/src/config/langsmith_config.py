"""
LangSmith Configuration Module

Industry-level tracing and observability for Roger Intelligence Platform.
Enables automatic trace collection for all agent decisions and tool executions.
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class LangSmithConfig:
    """
    LangSmith configuration for agent tracing and evaluation.

    Environment Variables Required:
    - LANGSMITH_API_KEY: Your LangSmith API key
    - LANGSMITH_PROJECT: (Optional) Project name, defaults to 'roger-intelligence'
    - LANGSMITH_TRACING_V2: (Optional) Enable v2 tracing, defaults to 'true'
    """

    def __init__(self):
        self.api_key = os.getenv("LANGSMITH_API_KEY")
        self.project = os.getenv("LANGSMITH_PROJECT", "roger-intelligence")
        self.endpoint = os.getenv(
            "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
        )
        self._configured = False

    @property
    def is_available(self) -> bool:
        """Check if LangSmith is configured and ready."""
        return bool(self.api_key)

    def configure(self) -> bool:
        """
        Configure LangSmith environment variables for automatic tracing.

        Returns:
            bool: True if configured successfully, False otherwise.
        """
        if not self.api_key:
            print("[LangSmith] WARNING: LANGSMITH_API_KEY not found. Tracing disabled.")
            return False

        if self._configured:
            return True

        # Set environment variables for LangChain/LangGraph auto-tracing
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = self.api_key
        os.environ["LANGCHAIN_PROJECT"] = self.project
        os.environ["LANGCHAIN_ENDPOINT"] = self.endpoint

        self._configured = True
        print(f"[LangSmith] OK - Tracing enabled for project: {self.project}")
        return True

    def disable(self):
        """Disable LangSmith tracing (useful for testing without API calls)."""
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        self._configured = False
        print("[LangSmith] Tracing disabled.")


def get_langsmith_client():
    """
    Get a LangSmith client for manual trace operations and evaluations.

    Returns:
        langsmith.Client or None if not available
    """
    try:
        from langsmith import Client

        config = LangSmithConfig()
        if config.is_available:
            return Client(api_key=config.api_key, api_url=config.endpoint)
        return None
    except ImportError:
        print("[LangSmith] langsmith package not installed. Run: pip install langsmith")
        return None


def trace_agent_execution(run_name: str = "agent_run"):
    """
    Decorator to trace agent function executions.

    Usage:
        @trace_agent_execution("weather_agent")
        def process_weather_query(query):
            ...
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                from langsmith import traceable

                traced_func = traceable(name=run_name)(func)
                return traced_func(*args, **kwargs)
            except ImportError:
                # Fallback: run without tracing
                return func(*args, **kwargs)

        return wrapper

    return decorator


# Auto-configure on import (if API key is present)
_config = LangSmithConfig()
if _config.is_available:
    _config.configure()
