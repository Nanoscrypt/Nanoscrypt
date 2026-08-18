import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict

from nanoscrypt.config.settings import settings
from nanoscrypt.models.session import Session

# System prompt for Confluence Doc generator
CONFLUENCE_PROMPT = """You are an expert technical writer. Your task is to generate professional, Atlassian-optimized Markdown documentation for the provided code or module.
The document must be structured to copy-paste cleanly into the Atlassian Confluence editor.

Format requirements:
1. Document Header: Clean Title, Last Updated placeholder, and Author placeholder.
2. Overview / Purpose: Concise paragraph explaining the role of this module.
3. Component Reference Table: A markdown table detailing Classes/Functions, Parameter types, and Descriptions.
4. Code Examples: Use markdown code blocks (e.g., ```python) which Confluence automatically converts to Code Macros on paste.
5. Key Takeaways/Notes: Use blockquotes (e.g. > *Note*) or clean bullet points.

Generate the documentation based on the following code:
{code_content}
"""

# System prompt for TODO comments placement analysis
TODO_PROMPT = """You are a codebase analysis engine. Given a codebase file and a target task description, you must decide exactly where to insert a TODO comment in the file to help implement the task.
You will return a JSON object with:
- "comment": The specific, actionable TODO text.
- "line_number": The 1-indexed line number where the comment should be inserted.

Code:
{code_content}

Task:
{task}

Return ONLY a JSON block, matching the structure:
```json
{{
  "comment": "TODO: text...",
  "line_number": 5
}}
```
"""

async def handle_todo(orchestrator: Any, payload: str, session: Session) -> Dict[str, Any]:
    """Places structured TODO comments directly in codebase files."""
    # We expect a format like: <file_path> <task> or we analyze the codebase to find where.
    # To keep it extremely robust, let's parse: <filepath> <task>
    parts = payload.strip().split(" ", 1)
    if len(parts) < 2:
        return {
            "status": "failed",
            "error": "Usage format: //TODO <file_path> <task description>"
        }

    file_path_str, task = parts[0], parts[1]
    p = Path(file_path_str)
    if not p.exists() or not p.is_file():
        # Try finding the file in the workspace
        workspace_p = Path(orchestrator.context_builder.workspace_root) / file_path_str
        if workspace_p.exists() and workspace_p.is_file():
            p = workspace_p
        else:
            return {
                "status": "failed",
                "error": f"File '{file_path_str}' not found in workspace."
            }

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"status": "failed", "error": f"Failed to read file: {e}"}

    # Ask the LLM to identify the best line number and write comment
    prompt = TODO_PROMPT.format(code_content=content, task=task)
    try:
        raw_res = await orchestrator.planner.llm.generate(
            prompt=prompt,
            system_prompt="You are a helpful assistant that returns clean JSON.",
            temperature=0.0
        )
        # Parse JSON
        clean_json = raw_res.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0].strip()
        decision = json.loads(clean_json)
    except Exception:
        # Fallback to line 1 if LLM or JSON parsing fails
        decision = {
            "comment": f"TODO: {task}",
            "line_number": 1
        }

    comment = decision.get("comment", f"TODO: {task}")
    line_num = decision.get("line_number", 1)

    # Inject comment into file content
    lines = content.splitlines(keepends=True)
    comment_line = f"# {comment}\n"
    
    # Bound line number safety
    target_idx = max(0, min(line_num - 1, len(lines)))
    lines.insert(target_idx, comment_line)

    try:
        p.write_text("".join(lines), encoding="utf-8")
    except Exception as e:
        return {"status": "failed", "error": f"Failed to write file updates: {e}"}

    return {
        "status": "completed",
        "action_taken": "inject_todo",
        "response": f"Successfully injected TODO comment at line {line_num} in {p.name}:\n`{comment_line.strip()}`"
    }

async def handle_inject(orchestrator: Any, payload: str, session: Session) -> Dict[str, Any]:
    """Reads codebase files and indexes them directly into semantic/short-term memory."""
    p = Path(payload)
    if not p.exists() or not p.is_file():
        workspace_p = Path(orchestrator.context_builder.workspace_root) / payload
        if workspace_p.exists() and workspace_p.is_file():
            p = workspace_p
        else:
            return {
                "status": "failed",
                "error": f"File '{payload}' not found in workspace."
            }

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"status": "failed", "error": f"Failed to read file: {e}"}

    # Add to Short-Term Memory
    orchestrator.short_term_memory.add(
        "user",
        f"Injected codebase context from file '{payload}':\n```\n{content}\n```",
        {"source": payload}
    )

    # Store in Long-Term Semantic Memory if active
    if settings.memory.enabled and hasattr(orchestrator, "long_term_memory"):
        try:
            await orchestrator.long_term_memory.store(
                content[:10000],
                metadata={"source": payload, "type": "injected_code"}
            )
        except Exception:
            pass

    return {
        "status": "completed",
        "action_taken": "inject_code",
        "response": f"Successfully read and indexed '{p.name}' ({len(content)} characters) into agent short-term and semantic memory."
    }

async def handle_confluence(orchestrator: Any, payload: str, session: Session) -> Dict[str, Any]:
    """Generates Atlassian Confluence-optimized Markdown technical documentation."""
    p = Path(payload)
    if not p.exists():
        workspace_p = Path(orchestrator.context_builder.workspace_root) / payload
        if workspace_p.exists():
            p = workspace_p
        else:
            return {
                "status": "failed",
                "error": f"Target path '{payload}' not found in workspace."
            }

    # Read files
    code_content = ""
    if p.is_file():
        try:
            code_content = f"### File: {p.name}\n```\n{p.read_text(encoding='utf-8', errors='replace')[:20000]}\n```"
        except Exception as e:
            return {"status": "failed", "error": f"Failed to read file: {e}"}
    else:
        # It's a directory, read top python files (up to 5)
        files = list(p.glob("**/*.py"))[:5]
        if not files:
            files = list(p.glob("*.*"))[:5]
        for f in files:
            try:
                code_content += f"### File: {f.name}\n```\n{f.read_text(encoding='utf-8', errors='replace')[:4000]}\n```\n\n"
            except Exception:
                pass

    if not code_content:
        return {"status": "failed", "error": f"No readable content found at '{payload}'."}

    # Call LLM to generate document
    prompt = CONFLUENCE_PROMPT.format(code_content=code_content)
    try:
        doc = await orchestrator.planner.llm.generate(
            prompt=prompt,
            system_prompt="You are a professional technical documentation writer.",
            timeout=1800.0
        )
    except Exception as e:
        return {"status": "failed", "error": f"LLM documentation generation failed: {e}"}

    # Write document to confluence_doc.md
    output_path = Path(".").resolve() / "confluence_doc.md"
    try:
        output_path.write_text(doc, encoding="utf-8")
    except Exception as e:
        return {"status": "failed", "error": f"Failed to write confluence_doc.md file: {e}"}

    return {
        "status": "completed",
        "action_taken": "generate_confluence",
        "response": f"Successfully generated Confluence-optimized documentation!\n"
                    f"Saved to: [confluence_doc.md](file:///{output_path.as_posix()})\n\n"
                    f"--- Preview ---\n\n{doc[:1000]}..."
    }
