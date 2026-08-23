import os
from pathlib import Path
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from nanoscrypt.config.user_config import (
    GLOBAL_CONFIG_FILE,
    SUPPORTED_PROVIDERS,
    is_configured,
    load_global_config,
    save_global_config,
)

console = Console()


def prompt_provider_and_key(force: bool = False) -> bool:
    """Interactively prompts the user to select an LLM provider and enter their API Key,
    saving the configuration to the user's root directory (~/.nanoscrypt/config.toml).

    Returns True if configuration was written or updated, False if skipped.
    """
    if not force and is_configured():
        return False

    console.print()
    console.print(
        Panel(
            "[bold cyan]Welcome to Nanoscrypt![/bold cyan]\n\n"
            "To get started, please configure your LLM provider and credentials.\n"
            f"[dim]Settings will be stored in your user root: {GLOBAL_CONFIG_FILE}[/dim]",
            title="[bold yellow]Initial Setup[/bold yellow]",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()

    # 1. Display provider options
    provider_keys = list(SUPPORTED_PROVIDERS.keys())
    console.print("[bold]Available Providers:[/bold]")
    for idx, p_key in enumerate(provider_keys, 1):
        p_info = SUPPORTED_PROVIDERS[p_key]
        tag = "[green](No API key needed)[/green]" if not p_info["requires_key"] else "[yellow](API Key required)[/yellow]"
        console.print(f"  [cyan]{idx}.[/cyan] [bold]{p_info['name']}[/bold] {tag} - Default: [dim]{p_info['default_model']}[/dim]")
    console.print()

    # 2. Select Provider
    while True:
        choice = Prompt.ask(
            "[bold]Select provider number or name[/bold]",
            default="1",
        ).strip().lower()

        selected_key = None
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(provider_keys):
                selected_key = provider_keys[idx - 1]
        elif choice in SUPPORTED_PROVIDERS:
            selected_key = choice

        if selected_key:
            break
        console.print("[red]Invalid selection. Please choose a valid provider number or name.[/red]")

    provider_info = SUPPORTED_PROVIDERS[selected_key]
    console.print(f"\n[green]Selected Provider:[/green] [bold]{provider_info['name']}[/bold]")

    # 3. Prompt for API Key if required
    api_key = None
    if provider_info["requires_key"]:
        env_name = provider_info.get("api_key_env", "API_KEY")
        existing_env_key = os.environ.get(env_name, "")
        
        console.print(f"[bold yellow]→ Please provide your {provider_info['name']} API Key:[/bold yellow]")
        if existing_env_key:
            masked_env = existing_env_key[:4] + "..." + existing_env_key[-4:] if len(existing_env_key) > 8 else "••••••••"
            console.print(f"  [dim](Found existing {env_name} in environment: {masked_env})[/dim]")
        
        while True:
            if existing_env_key:
                prompt_text = f"API Key [dim](Press Enter to use environment default or paste key)[/dim]"
                api_key = Prompt.ask(prompt_text, default=existing_env_key).strip()
            else:
                api_key = Prompt.ask(f"Paste your {provider_info['name']} API Key").strip()

            if api_key:
                break
            console.print("[red]API Key cannot be empty for this provider. Please paste a valid key.[/red]")
        
        masked_display = api_key[:4] + "••••••••" + api_key[-4:] if len(api_key) > 10 else "••••••••"
        console.print(f"[green]✓ API Key registered:[/green] [cyan]{masked_display}[/cyan]")

    # 4. Prompt for Model (with interactive menu and custom option)
    popular_models = provider_info.get("popular_models", [])
    default_model = provider_info["default_model"]

    console.print(f"\n[bold]Select Model for {provider_info['name']}:[/bold]")
    if popular_models:
        for idx, m_name in enumerate(popular_models, 1):
            tag = " [green](Default)[/green]" if m_name == default_model else ""
            console.print(f"  [cyan]{idx}.[/cyan] {m_name}{tag}")
        console.print(f"  [cyan]{len(popular_models) + 1}.[/cyan] Custom / Other model name")
        console.print()

        choice = Prompt.ask(
            "[bold]Select model number or type model name[/bold]",
            default="1",
        ).strip()

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(popular_models):
                model = popular_models[idx - 1]
            elif idx == len(popular_models) + 1:
                model = Prompt.ask("[bold]Enter custom model name[/bold]", default=default_model).strip() or default_model
            else:
                model = choice
        else:
            model = choice or default_model
    else:
        model = Prompt.ask("[bold]Model name[/bold]", default=default_model).strip() or default_model

    console.print(f"[green]Selected Model:[/green] [bold]{model}[/bold]")

    # 5. Optional API base for Ollama or Custom
    api_base = None
    if selected_key == "ollama":
        api_base = Prompt.ask("[bold]Ollama API Base URL[/bold]", default="http://localhost:11434").strip()
    elif selected_key == "custom":
        api_base = Prompt.ask("[bold]Custom API Base URL (optional)[/bold]", default="").strip() or None

    # 6. Save to user root config (~/.nanoscrypt/config.toml)
    saved_path = save_global_config(
        provider=selected_key,
        api_key=api_key,
        model=model,
        api_base=api_base,
    )

    console.print()
    console.print(f"[bold green]✓ Successfully saved credentials & provider to {saved_path}![/bold green]")
    console.print(f"[dim]Provider: {selected_key} | Model: {model}[/dim]\n")
    return True


def ensure_user_configured(interactive: bool = True) -> bool:
    """Checks if credentials exist. If not and interactive is True, prompts user."""
    if is_configured():
        return True
    if not interactive:
        return False
    return prompt_provider_and_key(force=False)
