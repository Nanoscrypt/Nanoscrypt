import pytest
from typer.testing import CliRunner
from nanoscrypt.cli.main import app
from nanoscrypt.core.registry import ToolRegistry
from nanoscrypt.api.dependencies import get_registry
from nanoscrypt.models.tool import GeneratedTool, ToolManifest

runner = CliRunner()

def test_cli_init(temp_workspace, monkeypatch):
    # Change working directory to temp workspace to prevent polluting project folder
    monkeypatch.chdir(temp_workspace)
    
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "Created nanoscrypt.toml" in result.stdout
    assert (temp_workspace / "nanoscrypt.toml").exists()

@pytest.mark.asyncio
async def test_cli_tools_list(temp_workspace):
    registry = ToolRegistry("sqlite+aiosqlite:///:memory:")
    await registry.initialize_db()

    # Seed registry
    manifest = ToolManifest(name="math_square")
    tool = GeneratedTool(
        name="math_square", code="def run(): pass", requirements=[],
        manifest=manifest, tests="", readme="Calculate square"
    )
    await registry.register(tool, "sha", "prompt")

    # Override get_registry dependency for tools command checks
    from nanoscrypt.api import dependencies
    dependencies._registry = registry

    # Invoke subcommand
    result = runner.invoke(app, ["tools", "list"])
    assert result.exit_code == 0
    assert "math_square" in result.stdout

    # Invoke inspect
    result_inspect = runner.invoke(app, ["tools", "inspect", "math_square"])
    assert result_inspect.exit_code == 0
    assert "math_square" in result_inspect.stdout
    
    # Tear down
    dependencies._registry = None
