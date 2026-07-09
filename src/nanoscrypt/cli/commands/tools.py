import asyncio
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
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
        table.add_column("Status", style="red")

        for t in tools:
            table.add_row(
                t.name,
                t.purpose[:50] + "..." if len(t.purpose) > 50 else t.purpose,
                str(t.current_version),
                f"{t.success_rate*100:.1f}%",
                str(t.usage_count),
                t.status
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

        details = (
            f"[bold]Name:[/bold] {t.name}\n"
            f"[bold]Purpose:[/bold] {t.purpose}\n"
            f"[bold]Dependencies:[/bold] {', '.join(t.dependencies) if t.dependencies else 'none'}\n"
            f"[bold]Current Version:[/bold] v{t.current_version}\n"
            f"[bold]Success Rate:[/bold] {t.success_rate*100:.1f}%\n"
            f"[bold]Usage Count:[/bold] {t.usage_count}\n"
            f"[bold]Status:[/bold] {t.status}\n"
            f"[bold]Created At:[/bold] {t.created_at.isoformat()}"
        )
        console.print(Panel(details, title=f"Tool Inspect: {t.name}", border_style="cyan"))

    from nanoscrypt.utils.async_runner import run_sync
    run_sync(async_inspect())
