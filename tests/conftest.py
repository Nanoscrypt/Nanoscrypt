import sys
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from nanoscrypt.config.settings import Settings, LLMSettings, RuntimeSettings, RegistrySettings, LoggingSettings


# ---------------------------------------------------------------------------
# Windows ProactorEventLoop fix:
# On Windows + Python 3.10, asyncio defaults to ProactorEventLoop. When
# aiosqlite / SQLAlchemy async sessions or litellm.acompletion create pipe
# transports, Python's __del__ garbage collector attempts to close them after
# the event loop is already closed, causing:
#   RuntimeError: Event loop is closed
#
# Switching to SelectorEventLoop avoids this entirely. It is safe because
# Nanoscrypt does not use any Windows-specific proactor features (named pipes,
# subprocess transport, etc.).
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def temp_workspace():
    """Provides a temporary workspace path that is cleaned up after testing."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def mock_settings(temp_workspace):
    """Generates mock Settings overrides for testing environment isolation."""
    return Settings(
        llm=LLMSettings(
            model="mock-model",
            temperature=0.0,
            max_tokens=100
        ),
        runtime=RuntimeSettings(
            timeout_seconds=5,
            max_memory_mb=128,
            cleanup_after=True,
            workspace_root=str(temp_workspace / "workspaces")
        ),
        registry=RegistrySettings(
            database_url="sqlite+aiosqlite:///:memory:",
            tools_dir=str(temp_workspace / "generated_tools")
        ),
        logging=LoggingSettings(
            level="DEBUG",
            json_output=False
        )
    )
