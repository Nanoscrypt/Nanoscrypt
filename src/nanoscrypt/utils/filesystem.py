import os
import shutil
from pathlib import Path

def ensure_directory(path: Path | str) -> Path:
    """Ensures a directory exists, creating it if necessary."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

def clear_directory(path: Path | str) -> None:
    """Safely deletes all contents inside a directory without deleting the directory itself."""
    p = Path(path)
    if not p.exists():
        return
    for item in p.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

def remove_directory(path: Path | str) -> None:
    """Safely removes a directory and all of its contents."""
    p = Path(path)
    if p.exists() and p.is_dir():
        shutil.rmtree(p)

def check_path_traversal(base_dir: Path | str, target_path: Path | str) -> bool:
    """Validates that target_path falls inside base_dir to protect against directory traversal attacks."""
    try:
        base = Path(base_dir).resolve()
        target = Path(target_path).resolve()
        return base in target.parents or base == target
    except Exception:
        return False
