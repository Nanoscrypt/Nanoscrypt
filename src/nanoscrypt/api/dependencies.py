from nanoscrypt.config.settings import settings
from nanoscrypt.core.approval import ApprovalGate
from nanoscrypt.core.audit import AuditLogger
from nanoscrypt.core.context import ContextBuilder
from nanoscrypt.core.generator import ToolGenerator

# Enterprise imports v0.2.0
from nanoscrypt.core.hooks import HookManager
from nanoscrypt.core.memory import LongTermMemory, ShortTermMemory
from nanoscrypt.core.orchestrator import Orchestrator
from nanoscrypt.core.planner import Planner
from nanoscrypt.core.registry import ToolRegistry
from nanoscrypt.core.repair import RepairLoop
from nanoscrypt.core.runtime import RuntimeManager
from nanoscrypt.core.validator import ToolValidator
from nanoscrypt.core.versioning import VersionManager
from nanoscrypt.llm.litellm_provider import LiteLLMProvider

# We cache registry instance globally to prevent re-opening database connections
_registry: ToolRegistry | None = None
_orchestrator: Orchestrator | None = None


def get_settings():
    return settings


async def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        cfg = get_settings()
        _registry = ToolRegistry(cfg.registry.database_url)
        await _registry.initialize_db()
    return _registry


async def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is not None:
        return _orchestrator

    cfg = get_settings()

    # Initialize LiteLLM wrapper
    llm = LiteLLMProvider(
        default_model=cfg.llm.model,
        temperature=cfg.llm.temperature,
        max_tokens=cfg.llm.max_tokens,
    )

    registry = await get_registry()

    context_builder = ContextBuilder(workspace_root="./")  # Scan workspace root
    planner = Planner(llm=llm)
    generator = ToolGenerator(llm=llm)
    validator = ToolValidator(llm=llm)
    runtime_manager = RuntimeManager(
        workspace_root=cfg.runtime.workspace_root,
        timeout_seconds=cfg.runtime.timeout_seconds,
    )
    version_manager = VersionManager(tools_dir=cfg.registry.tools_dir)

    repair_loop = RepairLoop(
        llm=llm,
        validator=validator,
        runtime_manager=runtime_manager,
        max_attempts=cfg.resilience.max_repair_attempts,
    )

    # Instantiate enterprise helpers
    hook_manager = HookManager()
    approval_gate = ApprovalGate()
    audit_logger = AuditLogger(session_factory=registry.session_factory)
    short_term_memory = ShortTermMemory(max_entries=cfg.memory.short_term_max_entries)
    long_term_memory = LongTermMemory(session_factory=registry.session_factory)

    _orchestrator = Orchestrator(
        context_builder=context_builder,
        planner=planner,
        generator=generator,
        validator=validator,
        runtime_manager=runtime_manager,
        registry=registry,
        version_manager=version_manager,
        repair_loop=repair_loop,
        hook_manager=hook_manager,
        approval_gate=approval_gate,
        audit_logger=audit_logger,
        short_term_memory=short_term_memory,
        long_term_memory=long_term_memory,
    )
    return _orchestrator
