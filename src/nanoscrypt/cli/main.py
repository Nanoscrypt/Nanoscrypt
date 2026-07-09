import typer
from nanoscrypt.cli.commands import init, run, tools, serve

app = typer.Typer(
    name="nanoscrypt",
    help="Standalone agentic framework that dynamically synthesizes, validates, and reuses tools.",
    no_args_is_help=True
)

# Register command submodules
app.command(name="init")(init.init_cmd)
app.command(name="run")(run.run_cmd)
app.command(name="serve")(serve.serve_cmd)

# Register sub-app group for tools management
app.add_typer(tools.tools_app, name="tools")

if __name__ == "__main__":
    app()
