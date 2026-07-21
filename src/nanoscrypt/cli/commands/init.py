from pathlib import Path

import typer
from rich.console import Console

console = Console()


def init_cmd(
    model: str = typer.Option("ollama/qwen2.5-coder", help="Default LLM model to use"),
    workspace: str = typer.Option(
        "./workspaces", help="Isolated workspace directories root"
    ),
):
    """Initializes a new Nanoscrypt project with a default nanoscrypt.toml config."""
    config_file = Path("nanoscrypt.toml")
    if config_file.exists():
        console.print(
            "[yellow]nanoscrypt.toml already exists in this directory. Initialization skipped.[/yellow]"
        )
        raise typer.Exit(code=0)

    config_template = f"""[llm]
model = "{model}"
temperature = 0.2
max_tokens = 4096

[runtime]
timeout_seconds = 30
max_memory_mb = 512
cleanup_after = true
workspace_root = "{workspace}"

[registry]
database_url = "sqlite+aiosqlite:///./registry/tools.db"
tools_dir = "./generated_tools"

[logging]
level = "INFO"
json_output = false
"""
    config_file.write_text(config_template, encoding="utf-8")
    console.print("[green]Created nanoscrypt.toml successfully![/green]")
