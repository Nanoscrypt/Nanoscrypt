from collections import deque
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select

from nanoscrypt.config.settings import settings

logger = structlog.get_logger()


class ShortTermMemory:
    """In-memory session buffer tracking recent interactions."""

    def __init__(self, max_entries: int = 50):
        self.buffer: deque[dict[str, Any]] = deque(maxlen=max_entries)

    def add(
        self, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> None:
        self.buffer.append(
            {
                "role": role,
                "content": content,
                "metadata": metadata or {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def get_context(self) -> list[dict[str, Any]]:
        return list(self.buffer)

    def clear(self) -> None:
        self.buffer.clear()


class LongTermMemory:
    """Queryable persistent memory stored in database for cross-session optimization."""

    def __init__(self, session_factory: Any):
        self.session_factory = session_factory

    async def store(self, key: str, value: str, category: str = "general") -> None:
        """Saves a memory entry in the database (we'll define DBMemoryEntry in database.py)."""
        if not settings.memory.long_term_enabled:
            return

        # We dynamic import or import from database directly
        from nanoscrypt.models.database import DBMemoryEntry

        async with self.session_factory() as session:
            async with session.begin():
                # Check if exact key exists to update it, or add new
                stmt = select(DBMemoryEntry).where(
                    DBMemoryEntry.key == key, DBMemoryEntry.category == category
                )
                res = await session.execute(stmt)
                entry = res.scalar_one_or_none()

                if entry:
                    entry.value = value
                    entry.updated_at = datetime.now(timezone.utc)
                else:
                    entry = DBMemoryEntry(key=key, value=value, category=category)
                    session.add(entry)
            await session.commit()

    async def recall(
        self, query: str, category: str = "general", limit: int = 5
    ) -> list[dict[str, Any]]:
        """Recalls matches based on keyword search over values."""
        if not settings.memory.long_term_enabled:
            return []

        from nanoscrypt.models.database import DBMemoryEntry

        async with self.session_factory() as session:
            like_pattern = f"%{query}%"
            stmt = (
                select(DBMemoryEntry)
                .where(
                    DBMemoryEntry.category == category,
                    DBMemoryEntry.value.like(like_pattern),
                )
                .limit(limit)
            )
            res = await session.execute(stmt)
            entries = res.scalars().all()
            return [
                {"key": e.key, "value": e.value, "category": e.category}
                for e in entries
            ]


class EntityMemory:
    """Tracks specialized metadata relationships: e.g. tools created, user preference, success scores."""

    def __init__(self, session_factory: Any):
        self.session_factory = session_factory

    async def track_tool_success(self, tool_name: str, score: float) -> None:
        """Updates internal statistics or preferences for tool combinations."""
        pass
