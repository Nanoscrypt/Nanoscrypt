import asyncio
import uuid
import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.align import Align
from rich.text import Text
from nanoscrypt.api.dependencies import get_orchestrator
from nanoscrypt.models.session import Session

console = Console()

def run_cmd(
    prompt: str = typer.Argument(..., help="The task prompt for the orchestrator"),
    session_id: str = typer.Option(None, help="Optional session ID context")
):
    """Executes a task prompt directly using the core orchestrator."""
    sess_id = session_id or f"cli_{uuid.uuid4().hex[:8]}"
    
    async def async_run():
        from nanoscrypt.logging import setup_logging
        setup_logging()
        
        # Initialize dependencies
        orchestrator = await get_orchestrator()
        session = Session(
            id=sess_id,
            workspace_path=f"./workspaces/{sess_id}"
        )
        
        # Display header
        console.print()
        console.print(Align.center(Panel(
            Text.assemble(
                ("Nanoscrypt ", "cyan bold"),
                ("- Live Execution Runtime", "dim")
            ),
            subtitle=f"Session: {sess_id}",
            border_style="cyan",
            padding=(0, 2)
        )))
        console.print()

        # Custom printing during the run lifecycle
        console.print(f"[bold cyan]USER REQUEST:[/bold cyan] {prompt}")
        console.print()

        with console.status("[bold green]Thinking and planning...", spinner="dots") as status:
            def cli_pre_execute_hook(tool_name: str, scan: dict) -> bool:
                status.stop()
                console.print()
                warning_details = (
                    f"The generated tool [bold cyan]{tool_name}[/bold cyan] requests access to sensitive resources:\n\n"
                )
                if scan["file_access"]:
                    warning_details += "  • [yellow]File System Access[/yellow] (reading/writing local files)\n"
                if scan["network_access"]:
                    warning_details += "  • [yellow]External Network Connection[/yellow] (scraping/fetching URLs)\n"
                
                console.print(Panel(
                    warning_details.strip(),
                    title="[bold red]SECURITY AUDIT WARNING[/bold red]",
                    border_style="red",
                    padding=(1, 2)
                ))
                console.print()
                approved = typer.confirm("Do you want to authorize and execute this tool?", default=False)
                console.print()
                status.start()
                return approved

            result = await orchestrator.execute_task(prompt, session, pre_execute_hook=cli_pre_execute_hook)

        console.print()
        if result.get("status") == "completed":
            output_content = str(result.get("output"))
            
            # If the output looks like markdown or has linebreaks, render it beautifully
            if "\n" in output_content or "#" in output_content or "`" in output_content:
                console.print("[bold green]RESPONSE:[/bold green]")
                console.print(Panel(
                    Markdown(output_content),
                    border_style="green",
                    padding=(1, 2)
                ))
            else:
                console.print(Panel(
                    output_content,
                    title="[bold green]Success[/bold green]",
                    border_style="green",
                    padding=(1, 2)
                ))

            if result.get("tool_name"):
                console.print(
                    f" [dim]tool: [bold]{result.get('tool_name')}[/bold] (v{result.get('version')}) "
                    f"• duration: {result.get('runtime_ms')}ms[/dim]"
                )
        elif result.get("status") == "clarification_needed":
            console.print(Panel(
                str(result.get("response")), 
                title="[bold yellow]Clarification Needed[/bold yellow]",
                border_style="yellow",
                padding=(1, 2)
            ))
        else:
            console.print(Panel(
                str(result.get("error") or "Unknown error occurred"), 
                title="[bold red]Execution Failed[/bold red]",
                border_style="red",
                padding=(1, 2)
            ))
        console.print()

    from nanoscrypt.utils.async_runner import run_sync
    run_sync(async_run())
