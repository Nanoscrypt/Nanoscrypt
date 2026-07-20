from pathlib import Path
from typing import Any

from nanoscrypt.models.session import Session


class ContextBuilder:
    """Assembles context prompts by merging session history, workspace files, registry tools, and active user requests."""

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root)

    def list_workspace_files(self) -> list[dict[str, Any]]:
        """Scans the workspace directory and lists user-facing files (ignoring envs/hidden directories)."""
        files = []
        if not self.workspace_root.exists():
            return files

        # Common directories to skip
        skip_dirs = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            "workspaces",
            "generated_tools",
            "venv_cache",
        }

        for p in self.workspace_root.rglob("*"):
            # Check if any parent directories match skip list
            if any(
                part in skip_dirs or part.startswith(".")
                for part in p.relative_to(self.workspace_root).parts[:-1]
            ):
                continue
            if p.is_file() and not p.name.startswith("."):
                try:
                    # Provide metadata about size and sample content
                    size = p.stat().st_size
                    files.append(
                        {
                            "relative_path": str(p.relative_to(self.workspace_root)),
                            "size_bytes": size,
                            "description": f"File with size {size} bytes",
                        }
                    )
                except Exception:
                    pass
        return files

    def assemble(
        self, user_prompt: str, session: Session, registered_tools: list[dict[str, Any]]
    ) -> str:
        """Constructs the comprehensive prompt representing current state for LLM processing."""
        files = self.list_workspace_files()

        # Format workspace files section
        files_section = "No files found in workspace."
        if files:
            files_lines = [
                f"- {f['relative_path']} ({f['size_bytes']} bytes)" for f in files
            ]
            files_section = "\n".join(files_lines)

        # Format registered tools section
        tools_section = "No registered tools available in the registry."
        if registered_tools:
            tools_lines = []
            for t in registered_tools:
                tools_lines.append(
                    f"- Tool: {t['name']}\n"
                    f"  Purpose: {t['purpose']}\n"
                    f"  Inputs: {t.get('input_schema', {})}\n"
                    f"  Outputs: {t.get('output_schema', {})}\n"
                    f"  Success Rate: {t.get('success_rate', 0.0) * 100:.1f}%\n"
                )
            tools_section = "\n".join(tools_lines)

        # Format session history (previous runs in this session)
        history_section = "No prior tools executed in this session."
        if session.history:
            history_lines = []
            for item in session.history:
                status = "Success" if item.success else "Failed"
                history_lines.append(
                    f"- Run of tool '{item.tool_name}' (v{item.version}): {status}\n"
                    f"  Inputs: {item.input_data}\n"
                    f"  Result: {item.output_data}\n"
                    f"  Error: {item.error}\n"
                )
            history_section = "\n".join(history_lines)

        # Build combined prompt template
        context_prompt = (
            f"=== USER REQUEST ===\n"
            f"{user_prompt}\n\n"
            f"=== CURRENT WORKSPACE FILES ===\n"
            f"{files_section}\n\n"
            f"=== REGISTERED TOOLS IN REGISTRY ===\n"
            f"{tools_section}\n\n"
            f"=== SESSION EXECUTION HISTORY ===\n"
            f"{history_section}\n"
        )
        return context_prompt
