import sys
import typer

# Reconfigure standard streams to UTF-8 to prevent encoding crashes on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from nanoscrypt.cli.commands import agents, init, run, serve, tools
from nanoscrypt.cli.setup import prompt_provider_and_key


def setup_cmd():
    """Configures the LLM provider, API Key, and model stored in user root ~/.nanoscrypt/config.toml."""
    prompt_provider_and_key(force=True)


app = typer.Typer(
    name="nanoscrypt",
    help="Standalone agentic framework that dynamically synthesizes, validates, and reuses tools.",
    no_args_is_help=True,
)

# Register command submodules
app.command(name="setup")(setup_cmd)
app.command(name="init")(init.init_cmd)
app.command(name="run")(run.run_cmd)
app.command(name="serve")(serve.serve_cmd)

# Register sub-app groups
app.add_typer(tools.tools_app, name="tools")
app.add_typer(agents.agents_app, name="agents")

if __name__ == "__main__":
    app()
