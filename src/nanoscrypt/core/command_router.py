from typing import Tuple

class PrefixCommandRouter:
    """Parses double-slash prefixed developer instructions and routes them to target modes."""

    @staticmethod
    def parse(prompt: str) -> Tuple[str, str]:
        """Parses the user prompt and returns (mode, payload)."""
        stripped = prompt.strip()
        if stripped.startswith("//TODO"):
            payload = stripped[len("//TODO"):].strip()
            return "todo", payload
        elif stripped.startswith("//inject"):
            payload = stripped[len("//inject"):].strip()
            return "inject", payload
        elif stripped.startswith("//confluence"):
            payload = stripped[len("//confluence"):].strip()
            return "confluence", payload
        elif stripped.startswith("//"):
            parts = stripped.split(" ", 1)
            return "invalid", parts[0]
        return "normal", prompt
