import sys
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

import os
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style

console = Console()


class FileCompleter(Completer):
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.skip_dirs = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            "workspaces",
            "generated_tools",
            "venv_cache",
        }

    def _get_files(self) -> list[str]:
        files = []
        for root, dirs, filenames in os.walk(self.workspace_root):
            dirs[:] = [d for d in dirs if d not in self.skip_dirs and not d.startswith(".")]
            for f in filenames:
                if not f.startswith("."):
                    rel = os.path.relpath(os.path.join(root, f), self.workspace_root)
                    files.append(rel.replace("\\", "/"))
        return files

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text:
            return
        
        last_at_idx = text.rfind('@')
        if last_at_idx == -1:
            return

        after_at = text[last_at_idx + 1:]
        if ' ' in after_at:
            return

        word_to_match = after_at.lower()
        all_files = self._get_files()
        
        for f in all_files:
            f_lower = f.lower()
            base_lower = os.path.basename(f).lower()
            if f_lower.startswith(word_to_match) or word_to_match in base_lower or word_to_match in f_lower:
                yield Completion(f, start_position=-len(word_to_match))



class Meter:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def get_stats(self) -> dict:
        input_tokens = 0
        output_tokens = 0
        cost = 0.0

        llms = []
        if hasattr(self.orchestrator, "planner") and hasattr(self.orchestrator.planner, "llm"):
            llms.append(self.orchestrator.planner.llm)
        if hasattr(self.orchestrator, "generator") and hasattr(self.orchestrator.generator, "llm"):
            llms.append(self.orchestrator.generator.llm)
        if hasattr(self.orchestrator, "repair_loop") and self.orchestrator.repair_loop and hasattr(self.orchestrator.repair_loop, "llm"):
            llms.append(self.orchestrator.repair_loop.llm)

        for llm in llms:
            input_tokens += getattr(llm, "total_input_tokens", 0) or 0
            output_tokens += getattr(llm, "total_output_tokens", 0) or 0
            cost += getattr(llm, "total_cost", 0.0) or 0.0

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
        }

    def status(self) -> str:
        stats = self.get_stats()
        saved_info = ""
        try:
            from nanoscrypt.core.compressor import ContextCompressor
            comp = ContextCompressor()
            if comp.total_saved_tokens > 0:
                saved_info = f"  ·  [green]Headroom saved ~{comp.total_saved_tokens} tokens[/green]"
        except Exception:
            pass

        return (
            f"${stats['cost']:.5f}  ·  "
            f"in {stats['input_tokens']}  out {stats['output_tokens']}{saved_info}"
        )


def run_cmd(
    prompt: str = typer.Argument(None, help="The task prompt for the orchestrator. Omit to run in interactive REPL mode."),
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
    """Executes a task prompt or enters an interactive REPL developer session using the Nanoscrypt orchestrator."""
    sess_id = session_id or f"cli_{uuid.uuid4().hex[:8]}"

    async def async_run():
        from nanoscrypt.logging import setup_logging

        setup_logging()

        # Initialize dependencies
        orchestrator = await get_orchestrator()
        session = Session(id=sess_id, workspace_path=f"./workspaces/{sess_id}")
        meter = Meter(orchestrator)

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

        # Display header with Sandbox status
        from nanoscrypt.config.settings import settings
        sandbox_lbl = "Google CAPSEM MicroVM (Secure)" if settings.runtime.capsem_enabled else "Local Subprocess (Host OS)"
        console.print()
        console.print(
            Align.center(
                Panel(
                    Text.assemble(
                        ("Nanoscrypt ", "cyan bold"),
                        ("- Live Execution Runtime v0.2.0", "dim"),
                    ),
                    subtitle=f"Session: {sess_id} | Agent: {active_agent.name if active_agent else 'Default orchestrator'} | Sandbox: {sandbox_lbl}",
                    border_style="cyan",
                    padding=(0, 2),
                )
            )
        )
        console.print()

        async def execute_prompt(user_prompt: str):
            from nanoscrypt.core.harness import AgentHarness

            stats_before = meter.get_stats()
            
            # Setup harness
            harness = AgentHarness(orchestrator, session, active_agent)

            # Setup interactive console approval handler
            def cli_approval_callback(req: ApprovalRequest) -> bool:
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
                return approved

            # Register the approval callback
            orchestrator.approval_gate.approval_callback = cli_approval_callback

            # Event listener for real-time progress events
            has_printed_response_header = False

            def event_listener(event):
                nonlocal has_printed_response_header
                if event.type == "thinking_delta":
                    console.print(f"[bold green]● Planning: {event.delta}[/bold green]")
                elif event.type == "tool_execution_start":
                    console.print(f"\n[dim]⚒ Executing tool: [bold]{event.tool_name}[/bold]...[/dim]")
                elif event.type == "tool_execution_end":
                    status_str = "[green]Success[/green]" if event.success else "[red]Failed[/red]"
                    console.print(f"[dim]⚒ Tool execution completed: {status_str}[/dim]")
                    if event.error:
                        console.print(f"[red]Error: {event.error}[/red]")
                elif event.type == "message_start":
                    console.print("\n[bold green]RESPONSE:[/bold green]")
                    has_printed_response_header = True
                elif event.type == "message_delta":
                    console.print(event.delta, end="")

            harness.subscribe(event_listener)

            # Execute via the harness prompt stream
            async for _ in harness.prompt(user_prompt):
                pass
                
            # Retrieve final result structure
            result = harness.last_result or {}

            console.print()
            if result.get("status") == "completed":
                output_content = str(result.get("output") or result.get("response") or "")

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

            stats_after = meter.get_stats()
            spent = stats_after["cost"] - stats_before["cost"]
            in_diff = stats_after["input_tokens"] - stats_before["input_tokens"]
            out_diff = stats_after["output_tokens"] - stats_before["output_tokens"]
            console.print(
                f"  [dim]turn cost: ${spent:.5f} (in {in_diff} | out {out_diff})  ·  "
                f"total cost: {meter.status()}[/dim]"
            )

        def handle_slash(command_line: str) -> bool:
            cmd, _, rest = command_line.strip().partition(" ")
            cmd = cmd.lower()
            if cmd == "/help":
                console.print("[bold]Available Commands:[/bold]")
                console.print("  /help                Show this help menu")
                console.print("  /cost                Show cumulative token and USD cost")
                console.print("  /model               Show current LLM model configuration")
                console.print("  /model <model_name>  Change the active model dynamically")
                console.print("  /profile             View stored personal user memory profile")
                console.print("  /profile set <k> <v> Set or update a personal user trait manually")
                console.print("  /memory search <q>   Search memories semantically using MemMachine")
                console.print("  /clear               Clear the conversation session history")
                console.print("  /history             Print history of the current session")
                console.print("  /exit                Exit the REPL session")
                return True
            elif cmd == "/memory":
                rest = rest.strip()
                if rest.startswith("search "):
                    query = rest[7:].strip()
                    if query:
                        from nanoscrypt.utils.async_runner import run_sync
                        res = run_sync(orchestrator.memmachine.search_memories(user_id="default_user", query=query))
                        if res:
                            console.print(f"[bold]MemMachine Semantic Search Results for '{query}':[/bold]")
                            for idx, item in enumerate(res, 1):
                                text = item.get("text", str(item))
                                console.print(f"  {idx}. [cyan]{text}[/cyan]")
                        else:
                            console.print(f"  [dim]No semantic vector memory matches found for '{query}'.[/dim]")
                    else:
                        console.print("  [yellow]Usage:[/yellow] /memory search <query>")
                else:
                    console.print("  [bold]MemMachine Memory Commands:[/bold]")
                    console.print("    /memory search <query>  Search memories semantically via MemMachine vector engine")
                return True
            elif cmd == "/profile":
                rest = rest.strip()
                if rest.startswith("set "):
                    _, _, set_args = rest.partition(" ")
                    trait_key, _, trait_val = set_args.partition(" ")
                    if trait_key and trait_val:
                        from nanoscrypt.utils.async_runner import run_sync
                        run_sync(orchestrator.user_personal_memory.set_trait(trait_key, trait_val))
                        console.print(f"  [green]Updated personal memory trait:[/green] {trait_key} -> {trait_val}")
                    else:
                        console.print("  [yellow]Usage:[/yellow] /profile set <trait_key> <trait_value>")
                else:
                    from nanoscrypt.utils.async_runner import run_sync
                    prof = run_sync(orchestrator.user_personal_memory.get_profile())
                    if prof:
                        console.print("[bold]User Personal Memory Profile:[/bold]")
                        for k, v in prof.items():
                            console.print(f"  • [cyan]{k}:[/cyan] {v}")
                    else:
                        console.print("  [dim]No personal user memory recorded yet.[/dim]")
                return True
            elif cmd == "/cost":
                console.print(f"  [bold]Cumulative Cost:[/bold] {meter.status()}")
                return True
            elif cmd == "/model":
                rest = rest.strip()
                if rest:
                    from nanoscrypt.config.settings import settings
                    settings.llm.model = rest
                    if hasattr(orchestrator.planner.llm, "default_model"):
                        orchestrator.planner.llm.default_model = rest
                    if hasattr(orchestrator.generator.llm, "default_model"):
                        orchestrator.generator.llm.default_model = rest
                    if orchestrator.repair_loop and hasattr(orchestrator.repair_loop.llm, "default_model"):
                        orchestrator.repair_loop.llm.default_model = rest
                    console.print(f"  [green]Model updated to:[/green] {rest}")
                else:
                    from nanoscrypt.config.settings import settings
                    console.print(f"  [bold]Active Model:[/bold] {settings.llm.model}")
                return True
            elif cmd == "/clear":
                session.history.clear()
                console.print("  [dim]Session history cleared.[/dim]")
                return True
            elif cmd == "/history":
                if not session.history:
                    console.print("  [dim]No history in this session yet.[/dim]")
                else:
                    console.print("[bold]Session Execution History:[/bold]")
                    for idx, item in enumerate(session.history):
                        status_str = "[green]SUCCESS[/green]" if item.success else "[red]FAILED[/red]"
                        console.print(
                            f"  {idx+1}. Tool: [bold]{item.tool_name}[/bold] (v{item.version}) • Status: {status_str}"
                        )
                        if item.error:
                            console.print(f"     Error: {item.error}")
                return True
            elif cmd in ("/exit", "/quit"):
                console.print("[dim]Exiting REPL session cleanly...[/dim]")
                sys.exit(0)
            return False

        # One-shot mode vs Interactive REPL mode
        if prompt:
            console.print(f"[bold cyan]USER REQUEST:[/bold cyan] {prompt}")
            console.print()
            await execute_prompt(prompt)
        else:
            console.print("[dim]/help for commands · ctrl-c or ctrl-d to exit[/dim]\n")
            
            completer = FileCompleter(Path("."))
            style = Style.from_dict({
                'prompt': 'bold #0000ff',
            })
            use_prompt_toolkit = True
            try:
                session_prompt = PromptSession(
                    completer=completer,
                    style=style
                )
            except Exception:
                use_prompt_toolkit = False
            
            while True:
                try:
                    if use_prompt_toolkit:
                        line = await session_prompt.prompt_async(
                            [('class:prompt', '> ')]
                        )
                    else:
                        line = console.input("[bold blue]>[/bold blue] ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    console.print(f"[dim]final cost: {meter.status()}[/dim]")
                    break
                if not line.strip():
                    continue
                if line.startswith("/"):
                    if handle_slash(line):
                        continue
                else:
                    await execute_prompt(line)

    from nanoscrypt.utils.async_runner import run_sync

    run_sync(async_run())
