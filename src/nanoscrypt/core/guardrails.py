import ast
import re
from typing import Any

from pydantic import BaseModel, Field

from nanoscrypt.config.settings import settings
from nanoscrypt.models.tool import GeneratedTool


class GuardrailRule(BaseModel):
    rule_type: str  # blocked_import, blocked_builtin, blocked_attribute, file_size_limit, network_allowlist
    parameters: dict[str, Any] = Field(default_factory=dict)
    severity: str = "error"  # error, warning
    message: str


class GuardrailPolicy(BaseModel):
    name: str
    description: str
    rules: list[GuardrailRule] = Field(default_factory=list)
    enforcement: str = "block"  # block, warn, log


class PolicyEngine:
    """Enforces configurable security rules and policies over dynamic tool code and execution parameters."""

    def __init__(self, policy: GuardrailPolicy | None = None):
        self.policy = policy or self._get_default_policy()

    def _get_default_policy(self) -> GuardrailPolicy:
        blocked_imports = []
        blocked_builtins = [
            "exec",
            "eval",
            "compile",
            "__import__",
            "globals",
            "locals",
        ]

        rules = [
            GuardrailRule(
                rule_type="blocked_import",
                parameters={"modules": blocked_imports},
                severity="error",
                message="Import of dangerous module '{item}' is blocked by policy.",
            ),
            GuardrailRule(
                rule_type="blocked_builtin",
                parameters={"builtins": blocked_builtins},
                severity="error",
                message="Calling dangerous builtin '{item}' is blocked by policy.",
            ),
            GuardrailRule(
                rule_type="file_size_limit",
                parameters={"max_mb": settings.security.max_file_write_mb},
                severity="error",
                message="File write operation might exceed maximum size limit of {max_mb}MB.",
            ),
        ]

        # Add domain allowlists/denylists if defined
        if settings.security.blocked_domains:
            rules.append(
                GuardrailRule(
                    rule_type="domain_denylist",
                    parameters={"domains": settings.security.blocked_domains},
                    severity="error",
                    message="Network access to blocked domain '{item}'.",
                )
            )
        if settings.security.allowed_domains:
            rules.append(
                GuardrailRule(
                    rule_type="domain_allowlist",
                    parameters={"domains": settings.security.allowed_domains},
                    severity="error",
                    message="Network access to domain '{item}' is not in the allowed list.",
                )
            )

        return GuardrailPolicy(
            name="default_enterprise_security",
            description="Default Nanoscrypt Enterprise Security Policy",
            rules=rules,
            enforcement="block",
        )

    def evaluate_code(self, code: str) -> list[dict[str, Any]]:
        """Statically scans the Python code against policy rules."""
        violations = []
        try:
            tree = ast.parse(code)
        except Exception as e:
            violations.append(
                {
                    "rule": "syntax",
                    "severity": "error",
                    "message": f"Syntax error preventing policy scan: {e!s}",
                    "line": None,
                }
            )
            return violations

        for rule in self.policy.rules:
            if rule.rule_type == "blocked_import":
                modules = rule.parameters.get("modules", [])
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            root = alias.name.split(".")[0]
                            if root in modules:
                                violations.append(
                                    {
                                        "rule": rule.rule_type,
                                        "severity": rule.severity,
                                        "message": rule.message.format(item=alias.name),
                                        "line": node.lineno,
                                    }
                                )
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            root = node.module.split(".")[0]
                            if root in modules:
                                violations.append(
                                    {
                                        "rule": rule.rule_type,
                                        "severity": rule.severity,
                                        "message": rule.message.format(
                                            item=node.module
                                        ),
                                        "line": node.lineno,
                                    }
                                )

            elif rule.rule_type == "blocked_builtin":
                builtins = rule.parameters.get("builtins", [])
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        if node.func.id in builtins:
                            violations.append(
                                {
                                    "rule": rule.rule_type,
                                    "severity": rule.severity,
                                    "message": rule.message.format(item=node.func.id),
                                    "line": node.lineno,
                                }
                            )

            elif (
                rule.rule_type == "domain_denylist"
                or rule.rule_type == "domain_allowlist"
            ):
                # Statically search code for URLs / Domains
                urls = re.findall(r'https?://[^\s\'"]+', code)
                domains = {re.sub(r"^https?://([^/]+).*$", r"\1", u) for u in urls}

                if rule.rule_type == "domain_denylist":
                    denied = rule.parameters.get("domains", [])
                    for d in domains:
                        if any(blocked in d for blocked in denied):
                            violations.append(
                                {
                                    "rule": rule.rule_type,
                                    "severity": rule.severity,
                                    "message": rule.message.format(item=d),
                                    "line": None,
                                }
                            )
                elif rule.rule_type == "domain_allowlist":
                    allowed = rule.parameters.get("domains", [])
                    if allowed:  # Only enforce if allowlist is not empty
                        for d in domains:
                            if not any(ok in d for ok in allowed):
                                violations.append(
                                    {
                                        "rule": rule.rule_type,
                                        "severity": rule.severity,
                                        "message": rule.message.format(item=d),
                                        "line": None,
                                    }
                                )

        return violations

    def check_tool(self, tool: GeneratedTool) -> list[dict[str, Any]]:
        """Scans the entire GeneratedTool bundle (code + requirements)."""
        violations = self.evaluate_code(tool.code)

        # Check requirements for blocked libraries
        for rule in self.policy.rules:
            if rule.rule_type == "blocked_import":
                modules = rule.parameters.get("modules", [])
                for req in tool.requirements:
                    clean_req = re.split(r"[=<>~]", req)[0].strip().lower()
                    if clean_req in modules:
                        violations.append(
                            {
                                "rule": "blocked_requirement",
                                "severity": rule.severity,
                                "message": f"Dependency '{req}' is blocked by policy.",
                                "line": None,
                            }
                        )
        return violations
