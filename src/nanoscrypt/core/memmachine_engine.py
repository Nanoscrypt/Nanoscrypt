import structlog
from typing import Any
from nanoscrypt.config.settings import settings

logger = structlog.get_logger()

try:
    import memmachine_client
    from memmachine_client import MemMachineClient
    MEMMACHINE_AVAILABLE = True
except Exception as e:
    MEMMACHINE_AVAILABLE = False
    logger.warning("memmachine_import_warning", error=str(e))


class MemMachineEngine:
    """Semantic vector memory provider wrapping memmachine-client with zero-crash fallback."""

    def __init__(self, session_factory: Any = None) -> None:
        self.enabled = settings.memmachine.enabled and MEMMACHINE_AVAILABLE
        self.base_url = settings.memmachine.base_url
        self.project_id = settings.memmachine.project_id
        self.client = None
        self._connected = False

        if self.enabled:
            try:
                self.client = MemMachineClient(base_url=self.base_url)
                self._connected = True
            except Exception as e:
                logger.debug("memmachine_connection_fallback", error=str(e))
                self._connected = False

    async def add_memory(
        self, user_id: str, agent_id: str, text: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        """Stores a memory entry in MemMachine or falls back smoothly."""
        if not self._connected or not self.client:
            return False

        try:
            proj = self.client.project(self.project_id)
            mem = proj.memory(agent_id=agent_id, user_id=user_id)
            mem.add(text, metadata=metadata or {})
            return True
        except Exception as e:
            logger.debug("memmachine_add_memory_fallback", error=str(e))
            return False

    async def search_memories(
        self, user_id: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Performs semantic vector search over past episodic memories and facts."""
        if not self._connected or not self.client or not query:
            return []

        try:
            proj = self.client.project(self.project_id)
            mem = proj.memory(agent_id="orchestrator", user_id=user_id)
            results = mem.search(query)
            recalled = []
            if isinstance(results, list):
                for res in results[:limit]:
                    if isinstance(res, dict):
                        recalled.append(res)
                    elif hasattr(res, "text"):
                        recalled.append(
                            {
                                "text": getattr(res, "text", str(res)),
                                "score": getattr(res, "score", 1.0),
                            }
                        )
                    else:
                        recalled.append({"text": str(res)})
            return recalled
        except Exception as e:
            logger.debug("memmachine_search_memories_fallback", error=str(e))
            return []
