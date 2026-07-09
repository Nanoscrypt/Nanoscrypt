from typing import AsyncGenerator
from fastapi import Request
from nanoscrypt.config.settings import settings
from nanoscrypt.core.context import ContextBuilder
from nanoscrypt.core.planner import Planner
from nanoscrypt.core.generator import ToolGenerator
from nanoscrypt.core.validator import ToolValidator
from nanoscrypt.core.runtime import RuntimeManager
from nanoscrypt.core.registry import ToolRegistry
from nanoscrypt.core.versioning import VersionManager
from nanoscrypt.core.repair import RepairLoop
from nanoscrypt.core.orchestrator import Orchestrator
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
        max_tokens=cfg.llm.max_tokens
    )

    registry = await get_registry()
    
    context_builder = ContextBuilder(workspace_root="./") # Scan workspace root
    planner = Planner(llm=llm)
    generator = ToolGenerator(llm=llm)
    validator = ToolValidator()
    runtime_manager = RuntimeManager(
        workspace_root=cfg.runtime.workspace_root,
        timeout_seconds=cfg.runtime.timeout_seconds
    )
    version_manager = VersionManager(tools_dir=cfg.registry.tools_dir)
    
    repair_loop = RepairLoop(
        llm=llm,
        validator=validator,
        runtime_manager=runtime_manager,
        max_attempts=3
    )

    _orchestrator = Orchestrator(
        context_builder=context_builder,
        planner=planner,
        generator=generator,
        validator=validator,
        runtime_manager=runtime_manager,
        registry=registry,
        version_manager=version_manager,
        repair_loop=repair_loop
    )
    return _orchestrator
