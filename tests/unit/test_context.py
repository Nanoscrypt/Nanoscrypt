from pathlib import Path
from datetime import datetime
from nanoscrypt.core.context import ContextBuilder
from nanoscrypt.models.session import Session, SessionToolOutput

def test_context_builder_workspace_scan(temp_workspace):
    # Create dummy files in temporary workspace
    file1 = temp_workspace / "data.csv"
    file1.write_text("a,b,c\n1,2,3")
    
    # Nested file
    nested_dir = temp_workspace / "subdir"
    nested_dir.mkdir()
    file2 = nested_dir / "notes.txt"
    file2.write_text("important notes")

    # Excluded files/dirs
    venv_dir = temp_workspace / ".venv"
    venv_dir.mkdir()
    (venv_dir / "config.txt").write_text("should be ignored")
    (temp_workspace / ".git").mkdir()
    (temp_workspace / ".gitignore").write_text("ignore me")

    builder = ContextBuilder(workspace_root=temp_workspace)
    files = builder.list_workspace_files()

    relative_paths = [f["relative_path"] for f in files]
    
    assert "data.csv" in relative_paths
    assert (Path("subdir") / "notes.txt").as_posix() in relative_paths
    assert ".gitignore" not in relative_paths
    assert ".git" not in relative_paths
    assert (Path(".venv") / "config.txt").as_posix() not in relative_paths

def test_context_builder_assemble(temp_workspace):
    builder = ContextBuilder(workspace_root=temp_workspace)
    
    session = Session(
        id="session-123",
        workspace_path=str(temp_workspace),
        history=[
            SessionToolOutput(
                tool_name="existing_parser",
                version=1,
                success=True,
                input_data={"file": "test.csv"},
                output_data="[{\"status\": \"parsed\"}]"
            )
        ]
    )

    registered_tools = [
        {
            "name": "registry_helper",
            "purpose": "Helpers for general tasks",
            "input_schema": {"query": "str"},
            "output_schema": {"result": "str"},
            "success_rate": 0.95
        }
    ]

    assembled = builder.assemble(
        user_prompt="Summarize my data",
        session=session,
        registered_tools=registered_tools
    )

    assert "Summarize my data" in assembled
    assert "registry_helper" in assembled
    assert "existing_parser" in assembled
    assert "Success" in assembled
