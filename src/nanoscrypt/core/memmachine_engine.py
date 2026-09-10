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
        self.session_factory = session_factory
        self.fallback_to_sqlite = settings.memmachine.fallback_to_sqlite
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
        """Stores a memory entry in MemMachine or falls back to SQLite."""
        if not text or not text.strip():
            return False

        # Attempt MemMachine if connected
        if self._connected and self.client:
            try:
                proj = self.client.project(self.project_id)
                mem = proj.memory(agent_id=agent_id, user_id=user_id)
                mem.add(text, metadata=metadata or {})
                return True
            except Exception as e:
                logger.debug("memmachine_add_memory_fallback", error=str(e))

        # Transparent SQLite fallback
        if self.fallback_to_sqlite and self.session_factory:
            try:
                from nanoscrypt.models.database import DBSemanticMemory
                async with self.session_factory() as session:
                    async with session.begin():
                        mem_entry = DBSemanticMemory(
                            user_id=user_id,
                            agent_id=agent_id,
                            text=text.strip(),
                            metadata_json=metadata or {},
                        )
                        session.add(mem_entry)
                    await session.commit()
                return True
            except Exception as e:
                logger.debug("sqlite_add_memory_fallback_error", error=str(e))

        return False

    async def search_memories(
        self, user_id: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Performs semantic search via MemMachine or falls back to SQLite search."""
        if not query or not query.strip():
            return []

        # Attempt MemMachine search if connected
        if self._connected and self.client:
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

        # SQLite fallback search
        if self.fallback_to_sqlite and self.session_factory:
            try:
                from sqlalchemy import or_, select
                from nanoscrypt.models.database import DBSemanticMemory

                query_terms = [t.lower() for t in query.strip().split() if len(t) > 1]
                async with self.session_factory() as session:
                    # Search matching user_id or general default
                    conditions = [DBSemanticMemory.user_id == user_id]

                    if query_terms:
                        term_clauses = [
                            DBSemanticMemory.text.ilike(f"%{term}%")
                            for term in query_terms
                        ]
                        conditions.append(or_(*term_clauses))

                    stmt = (
                        select(DBSemanticMemory)
                        .where(*conditions)
                        .order_by(DBSemanticMemory.id.desc())
                        .limit(limit * 3)
                    )
                    res = await session.execute(stmt)
                    rows = res.scalars().all()

                    # Simple score ranking based on keyword coverage
                    ranked: list[tuple[float, dict[str, Any]]] = []
                    for row in rows:
                        row_text_lower = row.text.lower()
                        matches = sum(1 for term in query_terms if term in row_text_lower)
                        score = (matches / len(query_terms)) if query_terms else 0.5
                        ranked.append(
                            (
                                score,
                                {
                                    "text": row.text,
                                    "source": "sqlite",
                                    "agent_id": row.agent_id,
                                    "score": round(score, 2),
                                    "created_at": row.created_at.isoformat() if row.created_at else None,
                                },
                            )
                        )

                    ranked.sort(key=lambda x: x[0], reverse=True)
                    return [item[1] for item in ranked[:limit]]
            except Exception as e:
                logger.debug("sqlite_search_memories_error", error=str(e))

        return []

