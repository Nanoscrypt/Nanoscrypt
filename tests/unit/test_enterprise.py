import pytest
from pathlib import Path
from nanoscrypt.core.guardrails import PolicyEngine, GuardrailPolicy, GuardrailRule
from nanoscrypt.core.approval import ApprovalGate, ApprovalType, ApprovalStatus
from nanoscrypt.core.memory import ShortTermMemory, LongTermMemory
from nanoscrypt.core.runtime import RuntimeManager
from nanoscrypt.models.tool import GeneratedTool, ToolManifest

def test_policy_engine_blocked_imports():
    """PolicyEngine should correctly flag blocked imports in tool code."""
    policy = GuardrailPolicy(
        name="test_policy",
        description="Test security policy",
        rules=[
            GuardrailRule(
                rule_type="blocked_import",
                parameters={"modules": ["subprocess", "os"]},
                severity="error",
                message="Blocked import '{item}'."
            )
        ]
    )
    engine = PolicyEngine(policy=policy)
    
    # Safe code
    violations_safe = engine.evaluate_code("def run(x: int) -> int:\n    return x + 1")
    assert len(violations_safe) == 0

    # Unsafe code importing subprocess
    violations_unsafe = engine.evaluate_code("import subprocess\ndef run(x: int) -> int:\n    return 0")
    assert len(violations_unsafe) == 1
    assert violations_unsafe[0]["rule"] == "blocked_import"

def test_short_term_memory():
    """ShortTermMemory should buffer entries up to max size."""
    mem = ShortTermMemory(max_entries=3)
    mem.add("user", "first")
    mem.add("assistant", "second")
    mem.add("user", "third")
    mem.add("assistant", "fourth") # Should evict the first entry

    ctx = mem.get_context()
    assert len(ctx) == 3
    assert ctx[0]["content"] == "second"
    assert ctx[2]["content"] == "fourth"

@pytest.mark.asyncio
async def test_approval_gate_low_risk(mock_settings):
    """ApprovalGate should auto-approve low risk actions if below threshold."""
    gate = ApprovalGate()
    
    # Let's mock settings value for threshold to high
    mock_settings.security.default_risk_threshold = "high"
    
    approved = await gate.request_approval(
        session_id="test_sess",
        approval_type=ApprovalType.TOOL_EXECUTION,
        description="safe operation",
        risk_level="low",
        resource_details={}
    )
    assert approved is True

@pytest.mark.asyncio
async def test_approval_gate_high_risk_required(mock_settings):
    """ApprovalGate should require user callback resolution for high risk actions."""
    # Register callback that returns True
    gate = ApprovalGate(approval_callback=lambda req: True)
    
    mock_settings.security.default_risk_threshold = "medium"
    
    approved = await gate.request_approval(
        session_id="test_sess",
        approval_type=ApprovalType.WEB_ACCESS,
        description="network fetch",
        risk_level="high",
        resource_details={}
    )
    assert approved is True
