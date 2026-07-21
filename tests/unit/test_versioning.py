import pytest
import json
from pathlib import Path
from nanoscrypt.core.versioning import VersionManager

@pytest.fixture
def version_manager(temp_workspace):
    return VersionManager(tools_dir=temp_workspace / "generated_tools")

def test_version_manager_snapshots(version_manager):
    tool_name = "format_parser"
    
    # 1. Create Version 1
    v1 = version_manager.create_version(
        tool_name=tool_name,
        code="def run(data): return data",
        requirements=[],
        manifest={"name": tool_name},
        tests="pass",
        readme="# Format Parser",
        prompt="create default parser"
    )
    assert v1 == 1
    assert version_manager.get_current_version_number(tool_name) == 1
    
    v1_dir = version_manager.get_version_directory(tool_name, 1)
    assert v1_dir.exists()
    assert (v1_dir / "tool.py").read_text(encoding="utf-8") == "def run(data): return data"
    assert (v1_dir / "version.json").exists()

    # 2. Create Version 2
    v2 = version_manager.create_version(
        tool_name=tool_name,
        code="def run(data):\n    return data.strip()",
        requirements=["tomli"],
        manifest={"name": tool_name, "dependencies": ["tomli"]},
        tests="pass",
        readme="# Format Parser V2",
        prompt="add strip function to parser",
        parent_version=1,
        change_reason="added clean strip"
    )
    assert v2 == 2
    assert version_manager.get_current_version_number(tool_name) == 2
    
    # 3. Rollback to version 1
    version_manager.rollback(tool_name, 1)
    assert version_manager.get_current_version_number(tool_name) == 1

    # 4. Compute Diffs
    diff_output = version_manager.diff(tool_name, 1, 2)
    assert "def run(data)" in diff_output
    assert "+    return data.strip()" in diff_output
