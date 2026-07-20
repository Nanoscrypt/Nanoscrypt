import inspect
from collections.abc import Callable
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class HookType(str, Enum):
    BEFORE_PLAN = "before_plan"
    AFTER_PLAN = "after_plan"
    BEFORE_GENERATE = "before_generate"
    AFTER_GENERATE = "after_generate"
    BEFORE_VALIDATE = "before_validate"
    AFTER_VALIDATE = "after_validate"
    BEFORE_EXECUTE = "before_execute"
    AFTER_EXECUTE = "after_execute"
    BEFORE_REPAIR = "before_repair"
    AFTER_REPAIR = "after_repair"
    ON_ERROR = "on_error"
    ON_APPROVAL_REQUIRED = "on_approval_required"


class HookManager:
    """Manages system hooks that execute custom callbacks during orchestration lifecycle."""

    def __init__(self) -> None:
        self.hooks: dict[HookType, list[Callable[..., Any]]] = {h: [] for h in HookType}

    def register(self, hook_type: HookType, callback: Callable[..., Any]) -> None:
        """Registers a sync or async hook callback."""
        if callback not in self.hooks[hook_type]:
            self.hooks[hook_type].append(callback)
            logger.debug(
                "hook_registered", hook_type=hook_type, callback=callback.__name__
            )

    async def fire(
        self, hook_type: HookType, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Triggers all callbacks registered under the given hook type sequentially, passing context."""
        current_context = context.copy()

        for cb in self.hooks[hook_type]:
            try:
                if inspect.iscoroutinefunction(cb):
                    res = await cb(current_context)
                else:
                    res = cb(current_context)

                # If callback returns a dictionary, merge it back into context
                if isinstance(res, dict):
                    current_context.update(res)
            except Exception as e:
                logger.error(
                    "hook_execution_failed",
                    hook_type=hook_type,
                    callback=cb.__name__,
                    error=str(e),
                )
                if hook_type != HookType.ON_ERROR:
                    # Trigger error hook if it's not the error hook itself failing
                    await self.fire(
                        HookType.ON_ERROR,
                        {
                            "hook_type": hook_type,
                            "error": e,
                            "context": current_context,
                        },
                    )

        return current_context
