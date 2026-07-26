import uuid

import typer
from rich.align import Align
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from nanoscrypt.api.dependencies import get_orchestrator
from nanoscrypt.core.approval import ApprovalRequest, ApprovalType
from nanoscrypt.models.agent import Agent, AgentRole
from nanoscrypt.models.permissions import AgentPermissions, PermissionLevel
from nanoscrypt.models.session import Session
from nanoscrypt.config.settings import settings

console = Console()


def run_cmd(
    prompt: str = typer.Argument(..., help="The task prompt for the orchestrator"),
    session_id: str = typer.Option(None, help="Optional session ID context"),
    agent_name: str = typer.Option(
        None, help="Define a custom Agent name to execute this task"
    ),
    agent_role: str = typer.Option(
        None,
        help="Define Agent Role (planner, coder, researcher, executor, reviewer, custom)",
    ),
    agent_goal: str = typer.Option(None, help="Goal description for the active Agent"),
    allow_web: bool = typer.Option(
        False, help="Explicitly enable web access for this run"
    ),
):
    """Executes a task prompt using the orchestrator with Agent configurations and interactive approvals."""
    sess_id = session_id or f"cli_{uuid.uuid4().hex[:8]}"

    async def async_run():
        from nanoscrypt.logging import setup_logging

        setup_logging()

        # Initialize dependencies
        orchestrator = await get_orchestrator()
        session = Session(id=sess_id, workspace_path=f"./workspaces/{sess_id}")

        # Build custom agent if args specified
        active_agent = None
        if agent_name or agent_role or agent_goal:
            role_enum = AgentRole.PLANNER
            if agent_role:
                try:
                    role_enum = AgentRole(agent_role.lower())
                except ValueError:
                    role_enum = AgentRole.CUSTOM

            perms = AgentPermissions(
                file_system=PermissionLevel.WRITE
                if role_enum == AgentRole.CODER
                else PermissionLevel.READ,
                network=PermissionLevel.EXECUTE if allow_web else PermissionLevel.DENY,
                tool_generation=PermissionLevel.EXECUTE,
                tool_execution=PermissionLevel.EXECUTE,
            )

            active_agent = Agent(
                name=agent_name or "CustomAgent",
                role=role_enum,
                goal=agent_goal or "Complete the requested user task",
                allow_web_access=allow_web,
                permissions=perms,
            )

        import shutil
        capsem_active = getattr(settings.runtime, "capsem_enabled", False) and bool(shutil.which("capsem"))
        if getattr(settings.runtime, "capsem_enabled", False):
            sandbox_lbl = "Capsem" if capsem_active else "Process Isolation"
        else:
            sandbox_lbl = "Disabled"

        # Display header
        console.print()
        console.print(
            Align.center(
                Panel(
                    Text.assemble(
                        ("Nanoscrypt ", "cyan bold"),
                        ("- Live Execution Runtime v0.2.0\n", "dim"),
                        (f"Session: {sess_id} | Agent: {active_agent.name if active_agent else 'Default orchestrator'} | Sandbox: {sandbox_lbl}", "yellow"),
                    ),
                    border_style="cyan",
                    padding=(0, 2),
                )
            )
        )
        console.print()

        # Custom printing during the run lifecycle
        console.print(f"[bold cyan]USER REQUEST:[/bold cyan] {prompt}")
        console.print()

        with console.status(
            "[bold green]Thinking and planning...", spinner="dots"
        ) as status:
            # Setup interactive console approval handler
            def cli_approval_callback(req: ApprovalRequest) -> bool:
                status.stop()
                console.print()

                # Risk level color determination
                risk_colors = {
                    "low": "green",
                    "medium": "yellow",
                    "high": "red",
                    "critical": "bold red reverse",
                }
                color = risk_colors.get(req.risk_level.lower(), "red")

                title = f"[bold {color}]SECURITY APPROVAL REQUIRED ({req.risk_level.upper()} RISK)[/bold {color}]"

                details = (
                    f"Operation: [bold cyan]{req.approval_type.value}[/bold cyan]\n"
                )
                details += f"Description: {req.description}\n\n"

                if req.approval_type == ApprovalType.WEB_ACCESS:
                    details += "[bold red]WEB SAFETY WARNING:[/bold red] This tool executes code that requests external web connectivity.\n"
                    if req.resource_details:
                        details += f"Resource Details: {req.resource_details}\n"
                elif req.approval_type == ApprovalType.FILE_ACCESS:
                    details += "[bold yellow]File System Warning:[/bold yellow] This tool attempts to read or write local files.\n"

                console.print(
                    Panel(
                        details.strip(), title=title, border_style=color, padding=(1, 2)
                    )
                )
                console.print()
                approved = typer.confirm("Do you authorize this action?", default=False)
                console.print()
                status.start()
                return approved

            # Register the approval callback
            orchestrator.approval_gate.approval_callback = cli_approval_callback

            # Execute
            result = await orchestrator.execute_task(
                user_prompt=prompt, session=session, agent=active_agent
            )

        console.print()
        if result.get("status") == "completed":
            output_content = str(result.get("output") or result.get("response") or "Success")

            # If the output looks like markdown or has linebreaks, render it beautifully
            if "\n" in output_content or "#" in output_content or "`" in output_content:
                console.print("[bold green]RESPONSE:[/bold green]")
                console.print(
                    Panel(
                        Markdown(output_content), border_style="green", padding=(1, 2)
                    )
                )
            else:
                console.print(
                    Panel(
                        output_content,
                        title="[bold green]Success[/bold green]",
                        border_style="green",
                        padding=(1, 2),
                    )
                )

            if result.get("tool_name"):
                console.print(
                    f" [dim]tool: [bold]{result.get('tool_name')}[/bold] (v{result.get('version')}) "
                    f"• duration: {result.get('runtime_ms')}ms[/dim]"
                )
        elif result.get("status") == "clarification_needed":
            console.print(
                Panel(
                    str(result.get("response")),
                    title="[bold yellow]Clarification Needed[/bold yellow]",
                    border_style="yellow",
                    padding=(1, 2),
                )
            )
        elif result.get("status") == "denied":
            console.print(
                Panel(
                    str(
                        result.get("error")
                        or "Execution blocked by security permissions."
                    ),
                    title="[bold red]Security Block[/bold red]",
                    border_style="red",
                    padding=(1, 2),
                )
            )
        else:
            console.print(
                Panel(
                    str(result.get("error") or "Unknown error occurred"),
                    title="[bold red]Execution Failed[/bold red]",
                    border_style="red",
                    padding=(1, 2),
                )
            )
        console.print()

    from nanoscrypt.utils.async_runner import run_sync

    run_sync(async_run())
