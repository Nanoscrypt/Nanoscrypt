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
        self,
        user_prompt: str,
        session: Session,
        registered_tools: list[dict[str, Any]],
        short_term_memory: list[dict[str, Any]] | None = None,
        personal_profile: dict[str, str] | None = None,
        semantic_memories: list[dict[str, Any]] | None = None,
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

        # Initialize Headroom context compressor
        from nanoscrypt.core.compressor import ContextCompressor
        compressor = ContextCompressor()

        # Parse @ annotations for file references
        import re
        referenced_contents = []
        matches = re.findall(r'@([a-zA-Z0-9_\.\-/\\~]+)', user_prompt)
        for match in matches:
            file_path = self.workspace_root / match
            target_path = None
            resolved_match_name = match

            if file_path.exists() and file_path.is_file():
                target_path = file_path
            else:
                # Fuzzy search workspace files by filename or relative path substring
                match_lower = match.lower()
                for item in files:
                    rel_path = item["relative_path"]
                    rel_lower = rel_path.lower()
                    base_name = Path(rel_path).name.lower()
                    stem_name = Path(rel_path).stem.lower()

                    if (
                        match_lower == base_name
                        or match_lower == stem_name
                        or match_lower in rel_lower
                        or match_lower in base_name
                    ):
                        candidate = self.workspace_root / rel_path
                        if candidate.exists() and candidate.is_file():
                            target_path = candidate
                            resolved_match_name = rel_path
                            break

            if target_path and target_path.exists() and target_path.is_file():
                try:
                    content = target_path.read_text(encoding="utf-8", errors="replace")
                    # Compress code block via Headroom if enabled
                    content = compressor.compress_code(content, file_name=resolved_match_name)
                    # Limit content size to prevent context explosion
                    if len(content) > 50000:
                        content = content[:50000] + "\n... [TRUNCATED DUE TO SIZE] ..."
                    referenced_contents.append(
                        f"--- File: {resolved_match_name} ---\n"
                        f"{content}\n"
                    )
                except Exception as e:
                    referenced_contents.append(f"--- File: {resolved_match_name} (Error reading: {e}) ---")
            else:
                referenced_contents.append(f"--- File: {match} (File not found in workspace) ---")

        referenced_section = ""
        if referenced_contents:
            referenced_section = "=== REFERENCED FILE CONTENTS ===\n" + "\n".join(referenced_contents) + "\n\n"

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
                out_data = str(item.output_data) if item.output_data else ""
                if len(out_data) > 300:
                    out_data = compressor.compress_tool_output(out_data)
                history_lines.append(
                    f"- Run of tool '{item.tool_name}' (v{item.version}): {status}\n"
                    f"  Inputs: {item.input_data}\n"
                    f"  Result: {out_data}\n"
                    f"  Error: {item.error}\n"
                )
            history_section = "\n".join(history_lines)

        # Format short term conversation memory
        memory_section = "No recent conversational history."
        if short_term_memory:
            memory_lines = []
            for item in short_term_memory:
                role_label = "User" if item["role"] == "user" else "Assistant"
                memory_lines.append(f"{role_label}: {item['content']}")
            raw_mem = "\n".join(memory_lines)
            if len(raw_mem) > 300:
                memory_section = compressor.compress_text(raw_mem)
            else:
                memory_section = raw_mem

        # Format user personal profile section
        profile_section = "No stored personal user details."
        if personal_profile:
            profile_lines = [f"- {k}: {v}" for k, v in personal_profile.items()]
            profile_section = "\n".join(profile_lines)

        # Format semantically recalled memories from MemMachine
        semantic_section = ""
        if semantic_memories:
            sem_lines = [
                f"- {item.get('text', str(item))}" for item in semantic_memories if item
            ]
            if sem_lines:
                semantic_section = (
                    "=== SEMANTICALLY RECALLED MEMORIES (MEMMACHINE) ===\n"
                    + "\n".join(sem_lines)
                    + "\n\n"
                )

        # Build combined prompt template
        context_prompt = (
            f"=== USER REQUEST ===\n"
            f"{user_prompt}\n\n"
            f"=== USER PERSONAL PROFILE & PREFERENCES ===\n"
            f"{profile_section}\n\n"
            f"{semantic_section}"
            f"=== RECENT CONVERSATION HISTORY ===\n"
            f"{memory_section}\n\n"
            f"=== CURRENT WORKSPACE FILES ===\n"
            f"{files_section}\n\n"
            f"{referenced_section}"
            f"=== REGISTERED TOOLS IN REGISTRY ===\n"
            f"{tools_section}\n\n"
            f"=== SESSION EXECUTION HISTORY ===\n"
            f"{history_section}\n"
        )
        return context_prompt
