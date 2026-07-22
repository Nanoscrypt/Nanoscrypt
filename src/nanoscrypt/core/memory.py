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


class UserPersonalMemory:
    """Dedicated persistent memory manager for user personal information, attributes, and preferences."""

    def __init__(self, session_factory: Any):
        self.session_factory = session_factory

    async def set_trait(self, key: str, value: str) -> None:
        """Stores or updates a specific personal attribute (e.g. name, designation, age, favorite color)."""
        from nanoscrypt.models.database import DBMemoryEntry

        category = "user_personal"
        normalized_key = f"personal_{key.lower().strip().replace(' ', '_')}"

        async with self.session_factory() as session:
            async with session.begin():
                stmt = select(DBMemoryEntry).where(
                    DBMemoryEntry.key == normalized_key,
                    DBMemoryEntry.category == category,
                )
                res = await session.execute(stmt)
                entry = res.scalar_one_or_none()

                if entry:
                    entry.value = value
                    entry.updated_at = datetime.now(timezone.utc)
                else:
                    entry = DBMemoryEntry(
                        key=normalized_key, value=value, category=category
                    )
                    session.add(entry)
            await session.commit()

    async def get_profile(self) -> dict[str, str]:
        """Retrieves all stored personal user traits as a clean key-value dictionary."""
        from nanoscrypt.models.database import DBMemoryEntry

        category = "user_personal"
        async with self.session_factory() as session:
            stmt = select(DBMemoryEntry).where(DBMemoryEntry.category == category)
            res = await session.execute(stmt)
            entries = res.scalars().all()
            profile = {}
            for e in entries:
                clean_key = (
                    e.key.replace("personal_", "")
                    .replace("_", " ")
                    .title()
                )
                profile[clean_key] = e.value
            return profile

    async def _regex_extraction(self, text: str) -> None:
        """Internal helper for fast rule-based regex extraction."""
        import re

        # Extract Name
        name_match = re.search(
            r"(?:my name is|i'm|i am)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            text,
            re.IGNORECASE,
        )
        if name_match:
            name_val = name_match.group(1).strip()
            ignored = {"a", "an", "the", "ready", "functioning", "built", "here", "running", "going"}
            if name_val.lower() not in ignored:
                await self.set_trait("name", name_val)

        # Extract Favorite Color / Tastes
        color_match = re.search(
            r"(?:favorite color is|favourite color is|color which i like is|favorite color|color is|like color)\s+([a-zA-Z]+)",
            text,
            re.IGNORECASE,
        )
        if color_match:
            color_val = color_match.group(1).strip()
            if color_val.lower() not in {"is", "the", "my", "a"}:
                await self.set_trait("favorite_color", color_val)

        # Extract Designation / Role
        designation_match = re.search(
            r"(?:work as a|working as|designation is|my role is|job title is|i am a)\s+([a-zA-Z0-9\s]+?)(?:\.|,|\s+and|\s+at|$)",
            text,
            re.IGNORECASE,
        )
        if designation_match:
            role_val = designation_match.group(1).strip()
            if len(role_val) > 2 and role_val.lower() not in ["user", "human", "bot", "student"]:
                await self.set_trait("designation", role_val)

        # Extract Age
        age_match = re.search(
            r"(?:i am|age is)\s+(\d{1,3})\s*(?:years old|yrs old)?",
            text,
            re.IGNORECASE,
        )
        if age_match:
            await self.set_trait("age", age_match.group(1).strip())

    async def extract_and_store(self, text: str) -> None:
        """Extract personal attributes robustly using fast regex and a gated LLM extraction pass."""
        # 1. Run local regex extraction first
        await self._regex_extraction(text)

        # 2. Gating check: only trigger LLM pass if personal key indicators are present
        keywords = {
            "name",
            "age",
            "work",
            "role",
            "job",
            "color",
            "favourite",
            "favorite",
            "prefer",
            "like",
            "live",
            "call me",
            "i'm a",
            "i am a",
            "specialist",
            "engineer",
            "developer",
            "architect",
        }
        text_lower = text.lower()
        if not any(k in text_lower for k in keywords):
            return

        # 3. LLM Structured Extraction Pass
        try:
            from nanoscrypt.llm.litellm_provider import LiteLLMProvider
            from nanoscrypt.config.settings import settings
            import json

            provider = LiteLLMProvider(default_model=settings.llm.model)
            system_prompt = (
                "You are an expert personal trait extractor. Analyze the user prompt and extract any personal details "
                "about the user: their Name, Designation (job role), Age, Favorite Color, and general Preferences (tastes, tools they like, frameworks, hobbies).\n"
                "Return ONLY a valid JSON object matching this schema. If a field is not found, omit it. Do not explain anything.\n"
                '{"name": "string", "designation": "string", "age": "string", "favorite_color": "string", "preferences": "string"}'
            )
            response_str = await provider.generate(
                prompt=f"Extract personal traits from: '{text}'",
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=150,
            )

            # Clean JSON response
            cleaned_response = response_str.strip()
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response[7:]
            if cleaned_response.endswith("```"):
                cleaned_response = cleaned_response[:-3]
            cleaned_response = cleaned_response.strip()

            extracted = json.loads(cleaned_response)
            if isinstance(extracted, dict):
                for k, v in extracted.items():
                    if v and isinstance(v, str) and len(v.strip()) > 0:
                        await self.set_trait(k, v.strip())
        except Exception as e:
            logger.debug("llm_personal_memory_extraction_failed", error=str(e))

