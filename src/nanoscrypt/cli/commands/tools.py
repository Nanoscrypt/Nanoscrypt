import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nanoscrypt.api.dependencies import get_registry

tools_app = typer.Typer(help="Manage and inspect tools inside the registry.")
console = Console()


@tools_app.command("list")
def list_cmd(query: str = typer.Option("", help="Search query filter")):
    """Lists all registered tools."""

    async def async_list():
        registry = await get_registry()
        tools = await registry.search(query)

        if not tools:
            console.print("[yellow]No tools found in the registry.[/yellow]")
            return

        table = Table(title="Registered Tools")
        table.add_column("Name", style="cyan")
        table.add_column("Purpose", style="green")
        table.add_column("Version", style="magenta")
        table.add_column("Success Rate", style="yellow")
        table.add_column("Usage Count", style="blue")
        table.add_column("Lifecycle", style="magenta")
        table.add_column("Status", style="red")

        for t in tools:
            table.add_row(
                t.name,
                t.purpose[:50] + "..." if len(t.purpose) > 50 else t.purpose,
                str(t.current_version),
                f"{t.success_rate * 100:.1f}%",
                str(t.usage_count),
                (await registry.get_lifecycle(t.name) or {}).get("state", "shared"),
                t.status,
            )
        console.print(table)

    from nanoscrypt.utils.async_runner import run_sync

    run_sync(async_list())


@tools_app.command("inspect")
def inspect_cmd(name: str):
    """Shows detailed information for a specific tool."""

    async def async_inspect():
        registry = await get_registry()
        t = await registry.get(name)
        if not t:
            console.print(f"[red]Tool '{name}' not found or inactive.[/red]")
            raise typer.Exit(code=1)

        lifecycle = await registry.get_lifecycle(name)
        details = (
            f"[bold]Name:[/bold] {t.name}\n"
            f"[bold]Purpose:[/bold] {t.purpose}\n"
            f"[bold]Dependencies:[/bold] {', '.join(t.dependencies) if t.dependencies else 'none'}\n"
            f"[bold]Current Version:[/bold] v{t.current_version}\n"
            f"[bold]Success Rate:[/bold] {t.success_rate * 100:.1f}%\n"
            f"[bold]Usage Count:[/bold] {t.usage_count}\n"
            f"[bold]Status:[/bold] {t.status}\n"
            f"[bold]Lifecycle:[/bold] {(lifecycle or {}).get('state', 'shared')} — "
            f"{(lifecycle or {}).get('reason', 'Legacy tool')}\n"
            f"[bold]Created At:[/bold] {t.created_at.isoformat()}"
        )
        console.print(
            Panel(details, title=f"Tool Inspect: {t.name}", border_style="cyan")
        )

    from nanoscrypt.utils.async_runner import run_sync

    run_sync(async_inspect())


@tools_app.command("delete")
def delete_cmd(name: str):
    """Deletes/deprecates a tool from the active registry."""

    async def async_delete():
        registry = await get_registry()
        success = await registry.delete(name)
        if success:
            console.print(f"[green]Tool '{name}' has been deprecated/marked inactive.[/green]")
        else:
            console.print(f"[red]Tool '{name}' not found.[/red]")

    from nanoscrypt.utils.async_runner import run_sync

    run_sync(async_delete())


@tools_app.command("outcome")
def outcome_cmd(
    execution_id: int = typer.Argument(..., help="Execution ID returned by nanoscrypt run"),
    task_key: str = typer.Option(..., help="Stable key for this task family"),
    contribution: str = typer.Option(..., help="helpful, neutral, or harmful"),
    evidence: str = typer.Option(..., help="Short explanation supporting the rating"),
):
    """Record task-level evidence for a tool execution."""

    async def async_record():
        if contribution not in {"helpful", "neutral", "harmful"}:
            console.print("[red]Contribution must be helpful, neutral, or harmful.[/red]")
            raise typer.Exit(code=2)
        registry = await get_registry()
        result = await registry.record_outcome(
            execution_id, task_key, contribution, evidence
        )
        if result is None:
            console.print("[red]Execution ID not found.[/red]")
            raise typer.Exit(code=1)
        console.print(
            f"[green]{result['tool_name']}[/green]: lifecycle is "
            f"[bold]{result['state']}[/bold] — {result['reason']}"
        )

    from nanoscrypt.utils.async_runner import run_sync

    run_sync(async_record())
