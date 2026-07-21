import pytest
from nanoscrypt.core.guardrails import PolicyEngine, GuardrailPolicy, GuardrailRule

def test_policy_engine_blocked_import():
    policy = GuardrailPolicy(
        name="test_policy",
        description="Test Policy",
        rules=[
            GuardrailRule(
                rule_type="blocked_import",
                parameters={"modules": ["os", "subprocess"]},
                severity="error",
                message="Blocked import of dangerous module '{item}'."
            )
        ]
    )
    engine = PolicyEngine(policy=policy)
    
    # OS import is blocked
    code_with_os = "import os\nprint('hello')"
    violations = engine.evaluate_code(code_with_os)
    assert len(violations) == 1
    assert violations[0]["rule"] == "blocked_import"
    assert "os" in violations[0]["message"]

    # Math import is allowed
    code_with_math = "import math\nprint(math.sqrt(4))"
    violations_math = engine.evaluate_code(code_with_math)
    assert len(violations_math) == 0

def test_policy_engine_blocked_builtin():
    policy = GuardrailPolicy(
        name="test_policy",
        description="Test Policy",
        rules=[
            GuardrailRule(
                rule_type="blocked_builtin",
                parameters={"builtins": ["eval", "exec"]},
                severity="error",
                message="Calling dangerous builtin '{item}' is blocked by policy."
            )
        ]
    )
    engine = PolicyEngine(policy=policy)

    # eval call is blocked
    code_with_eval = "eval('1 + 1')"
    violations = engine.evaluate_code(code_with_eval)
    assert len(violations) == 1
    assert violations[0]["rule"] == "blocked_builtin"
    assert "eval" in violations[0]["message"]

    # print call is allowed
    code_with_print = "print('hello')"
    violations_print = engine.evaluate_code(code_with_print)
    assert len(violations_print) == 0
