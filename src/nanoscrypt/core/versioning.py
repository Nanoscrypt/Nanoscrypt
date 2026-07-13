import difflib
import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

from nanoscrypt.utils.filesystem import check_path_traversal, ensure_directory
from nanoscrypt.utils.hashing import calculate_sha256

logger = structlog.get_logger()


class VersionManager:
    """Manages file-based snapshot directories, version pointers, and code diffs for generated tools."""

    def __init__(self, tools_dir: Path | str):
        self.tools_dir = Path(tools_dir)
        ensure_directory(self.tools_dir)

    def get_tool_directory(self, tool_name: str) -> Path:
        """Returns the base directory for a specific tool."""
        target_path = self.tools_dir / tool_name
        if not check_path_traversal(self.tools_dir, target_path):
            raise ValueError("Path traversal detected")
        return target_path

    def get_versions(self, tool_name: str) -> list[int]:
        """Returns a sorted list of all available version numbers for a tool."""
        tool_dir = self.get_tool_directory(tool_name)
        if not tool_dir.exists():
            return []

        versions = []
        for p in tool_dir.iterdir():
            if p.is_dir() and p.name.startswith("v"):
                try:
                    versions.append(int(p.name[1:]))
                except ValueError:
                    pass
        return sorted(versions)

    def create_version(
        self,
        tool_name: str,
        code: str,
        requirements: list[str],
        manifest: dict,
        tests: str,
        readme: str,
        prompt: str,
        parent_version: int | None = None,
        change_reason: str = "initial",
    ) -> int:
        """Saves a new tool snapshot and updates the active pointer file."""
        tool_dir = self.get_tool_directory(tool_name)
        ensure_directory(tool_dir)

        # Determine next version number
        existing = self.get_versions(tool_name)
        next_version = max(existing, default=0) + 1

        version_dir = tool_dir / f"v{next_version}"
        ensure_directory(version_dir)

        # Write files
        (version_dir / "tool.py").write_text(code, encoding="utf-8")
        (version_dir / "requirements.txt").write_text(
            "\n".join(requirements), encoding="utf-8"
        )
        (version_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        (version_dir / "tests.py").write_text(tests, encoding="utf-8")
        (version_dir / "README.md").write_text(readme, encoding="utf-8")

        # Create combined code hash
        code_hash = calculate_sha256(code)

        # Write version metadata
        meta = {
            "version": next_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "code_hash": f"sha256:{code_hash}",
            "parent_version": parent_version,
            "change_reason": change_reason,
        }
        (version_dir / "version.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        # Update current version pointer
        (tool_dir / "current.json").write_text(
            json.dumps({"version": next_version}), encoding="utf-8"
        )

        logger.info(
            "version_manager_created_snapshot",
            tool_name=tool_name,
            version=next_version,
            hash=code_hash,
        )
        return next_version

    def get_current_version_number(self, tool_name: str) -> int | None:
        """Reads the current active version number from current.json."""
        pointer_file = self.get_tool_directory(tool_name) / "current.json"
        if not pointer_file.exists():
            return None
        try:
            data = json.loads(pointer_file.read_text(encoding="utf-8"))
            return int(data["version"])
        except Exception:
            return None

    def get_version_directory(self, tool_name: str, version: int) -> Path | None:
        """Returns the folder path for a specific version of a tool."""
        version_dir = self.get_tool_directory(tool_name) / f"v{version}"
        return version_dir if version_dir.exists() else None

    def rollback(self, tool_name: str, to_version: int) -> None:
        """Updates current.json to point to a previous version number."""
        tool_dir = self.get_tool_directory(tool_name)
        version_dir = tool_dir / f"v{to_version}"

        if not version_dir.exists():
            raise FileNotFoundError(
                f"Version v{to_version} does not exist for tool {tool_name}"
            )

        (tool_dir / "current.json").write_text(
            json.dumps({"version": to_version}), encoding="utf-8"
        )
        logger.info(
            "version_manager_rollback_successful",
            tool_name=tool_name,
            to_version=to_version,
        )

    def diff(self, tool_name: str, v1: int, v2: int) -> str:
        """Computes a unified line diff of tool.py between two versions."""
        dir1 = self.get_version_directory(tool_name, v1)
        dir2 = self.get_version_directory(tool_name, v2)

        if not dir1 or not dir2:
            raise FileNotFoundError(
                f"Cannot perform diff, one or both versions ({v1}, {v2}) do not exist."
            )

        code1 = (dir1 / "tool.py").read_text(encoding="utf-8").splitlines()
        code2 = (dir2 / "tool.py").read_text(encoding="utf-8").splitlines()

        diff_lines = difflib.unified_diff(
            code1, code2, fromfile=f"v{v1}/tool.py", tofile=f"v{v2}/tool.py"
        )
        return "\n".join(diff_lines)
