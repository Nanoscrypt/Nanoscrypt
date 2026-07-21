import pytest
import tempfile
import json
from pathlib import Path
from nanoscrypt.core.versioning import VersionManager

def test_version_manager_create_and_list():
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = VersionManager(tools_dir=tmp_dir)
        
        tool_name = "math_util"
        code = "def add(a, b): return a + b"
        requirements = ["numpy"]
        manifest = {"name": tool_name}
        tests = "assert add(1, 2) == 3"
        readme = "# Math Util"
        prompt = "Create add utility"

        # Create first version
        v1 = manager.create_version(
            tool_name=tool_name,
            code=code,
            requirements=requirements,
            manifest=manifest,
            tests=tests,
            readme=readme,
            prompt=prompt
        )
        assert v1 == 1

        # Check version directory content
        tool_dir = Path(tmp_dir) / tool_name
        v1_dir = tool_dir / "v1"
        assert v1_dir.exists()
        assert (v1_dir / "tool.py").read_text(encoding="utf-8") == code
        assert (v1_dir / "requirements.txt").read_text(encoding="utf-8") == "numpy"
        
        # Check current version pointer
        current_file = tool_dir / "current.json"
        assert current_file.exists()
        current_data = json.loads(current_file.read_text(encoding="utf-8"))
        assert current_data["version"] == 1

        # Create second version
        code_v2 = "def add(a, b): return a + b + 1"
        v2 = manager.create_version(
            tool_name=tool_name,
            code=code_v2,
            requirements=requirements,
            manifest=manifest,
            tests=tests,
            readme=readme,
            prompt="Modify add utility",
            parent_version=1,
            change_reason="Add 1"
        )
        assert v2 == 2

        versions = manager.get_versions(tool_name)
        assert versions == [1, 2]
