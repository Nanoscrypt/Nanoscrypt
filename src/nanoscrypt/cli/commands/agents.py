import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import delete, select

from nanoscrypt.api.dependencies import get_registry
from nanoscrypt.models.database import DBAgentDefinition

console = Console()
agents_app = typer.Typer(help="Manage registered agent role profiles.")


async def async_list():
    registry = await get_registry()
    async with registry.session_factory() as session:
        stmt = select(DBAgentDefinition)
        res = await session.execute(stmt)
        agents = res.scalars().all()

        if not agents:
            console.print("[yellow]No custom agents registered in database.[/yellow]")
            return

        table = Table(title="Nanoscrypt Agents Registry")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Role", style="green")
        table.add_column("Goal", style="magenta")
        table.add_column("Permissions (FS/Net)", style="dim")

        for a in agents:
            perms = a.permissions
            fs_net = (
                f"{perms.get('file_system', 'deny')}/{perms.get('network', 'deny')}"
            )
            table.add_row(
                a.name,
                a.role,
                a.goal[:50] + "..." if len(a.goal) > 50 else a.goal,
                fs_net,
            )

        console.print(table)


async def async_create(name: str, role: str, goal: str, backstory: str):
    registry = await get_registry()
    async with registry.session_factory() as session:
        async with session.begin():
            # Check unique name
            stmt = select(DBAgentDefinition).where(DBAgentDefinition.name == name)
            res = await session.execute(stmt)
            if res.scalar_one_or_none():
                console.print(
                    f"[bold red]Error:[/bold red] Agent with name '{name}' already exists."
                )
                return

            agent = DBAgentDefinition(
                name=name,
                role=role.lower(),
                goal=goal,
                backstory=backstory,
                tools=[],
                permissions={
                    "file_system": "read",
                    "network": "deny",
                    "tool_generation": "execute",
                    "tool_execution": "execute",
                },
            )
            session.add(agent)
        await session.commit()
        console.print(
            f"[bold green]Success:[/bold green] Agent '{name}' registered successfully."
        )


async def async_delete(name: str):
    registry = await get_registry()
    async with registry.session_factory() as session:
        async with session.begin():
            stmt = delete(DBAgentDefinition).where(DBAgentDefinition.name == name)
            await session.execute(stmt)
        await session.commit()
        console.print(
            f"[bold green]Success:[/bold green] Agent '{name}' deleted successfully."
        )


@agents_app.command("list")
def list_cmd():
    """Lists all registered agent role configurations."""
    from nanoscrypt.utils.async_runner import run_sync

    run_sync(async_list())


@agents_app.command("create")
def create_cmd(
    name: str = typer.Argument(..., help="Unique name for the agent"),
    role: str = typer.Option(
        "planner", help="Agent Role: planner, coder, researcher, reviewer, executor"
    ),
    goal: str = typer.Option(..., prompt=True, help="Agent's primary goal description"),
    backstory: str = typer.Option("", prompt=True, help="Agent's background story"),
):
    """Registers a new agent profile."""
    from nanoscrypt.utils.async_runner import run_sync

    run_sync(async_create(name, role, goal, backstory))


@agents_app.command("delete")
def delete_cmd(name: str = typer.Argument(..., help="Name of the agent to delete")):
    """Deletes an agent profile."""
    from nanoscrypt.utils.async_runner import run_sync

    run_sync(async_delete(name))
