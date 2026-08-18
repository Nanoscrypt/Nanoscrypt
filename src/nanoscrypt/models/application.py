"""Data models for multi-file applications, polyglot language targets, and services."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProjectType(str, Enum):
    TOOL = "tool"
    APPLICATION = "application"
    SERVICE = "service"


class TargetLanguage(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    RUST = "rust"


@dataclass
class ProjectFile:
    """Represents an individual file within an application workspace."""

    path: str
    content: str
    file_type: str = "text"  # "text", "binary", "json"


@dataclass
class ApplicationManifest:
    """Represents a complete multi-file, multi-language application."""

    app_id: str
    name: str
    description: str
    language: TargetLanguage | str = TargetLanguage.PYTHON
    project_type: ProjectType = ProjectType.APPLICATION
    framework: str | None = None
    entry_point: str = "main.py"
    port: int | None = None
    files: dict[str, str] = field(default_factory=dict)  # relative_path -> content
    dependencies: list[str] = field(default_factory=list)
    is_daemon: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
