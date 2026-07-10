from datetime import UTC, datetime

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from nanoscrypt.models.database import Base, DBTool, DBToolExecution, DBToolVersion
from nanoscrypt.models.tool import GeneratedTool

logger = structlog.get_logger()


class ToolRegistry:
    """Handles persistence, metadata indexing, and metric updates for tools in the SQLite database."""

    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url, echo=False)
        self.session_factory = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def initialize_db(self) -> None:
        """Initializes database tables if they do not exist."""
        # Ensure database directory exists for SQLite
        if "sqlite" in self.engine.url.drivername:
            database_path = self.engine.url.database
            if database_path and database_path != ":memory:":
                from pathlib import Path

                db_dir = Path(database_path).parent
                db_dir.mkdir(parents=True, exist_ok=True)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def register(
        self,
        tool: GeneratedTool,
        code_hash: str,
        prompt_used: str,
        change_reason: str = "initial",
    ) -> DBTool:
        """Saves tool metadata and its version details inside the registry."""
        log = logger.bind(component="registry", tool_name=tool.name)
        log.debug("registry_registering_tool")

        async with self.session_factory() as session:
            async with session.begin():
                # Check if tool already exists
                stmt = select(DBTool).where(DBTool.name == tool.name)
                result = await session.execute(stmt)
                db_tool = result.scalar_one_or_none()

                if not db_tool:
                    # Create new tool record
                    db_tool = DBTool(
                        name=tool.name,
                        purpose=tool.manifest.input_schema.get("purpose")
                        or tool.readme[:200],
                        language=tool.manifest.language,
                        entry_point=tool.manifest.entry,
                        dependencies=tool.manifest.dependencies,
                        input_schema=tool.manifest.input_schema,
                        output_schema=tool.manifest.output_schema,
                        tags=[tool.name],
                        current_version=1,
                        success_rate=1.0,
                        usage_count=0,
                        status="active",
                    )
                    session.add(db_tool)
                    # Flush to get the tool ID
                    await session.flush()
                    version_num = 1
                else:
                    # Increment version
                    version_num = db_tool.current_version + 1
                    db_tool.current_version = version_num
                    db_tool.updated_at = datetime.now(UTC)
                    db_tool.dependencies = list(
                        set(db_tool.dependencies + tool.manifest.dependencies)
                    )

                # Add version snapshot details
                db_version = DBToolVersion(
                    tool_id=db_tool.id,
                    version=version_num,
                    code_hash=code_hash,
                    prompt_used=prompt_used,
                    change_reason=change_reason,
                    test_results={"status": "passed"},
                    runtime_stats={"avg_ms": 0},
                )
                session.add(db_version)

            await session.commit()
            log.info("registry_tool_registered", version=version_num)
            return db_tool

    async def get(self, name: str) -> DBTool | None:
        """Retrieves active tool metadata by name."""
        async with self.session_factory() as session:
            stmt = select(DBTool).where(DBTool.name == name, DBTool.status == "active")
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def search(self, query: str, limit: int = 5) -> list[DBTool]:
        """Performs simple keyword search matching tool name, purpose, or tags."""
        async with self.session_factory() as session:
            like_pattern = f"%{query}%"
            stmt = (
                select(DBTool)
                .where(
                    DBTool.status == "active",
                    or_(
                        DBTool.name.like(like_pattern),
                        DBTool.purpose.like(like_pattern),
                    ),
                )
                .order_by(DBTool.success_rate.desc(), DBTool.usage_count.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_stats(
        self,
        tool_name: str,
        success: bool,
        runtime_ms: int,
        input_data: dict,
        output_data: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Updates tool usage counts, metrics, and logs the individual execution run."""
        log = logger.bind(component="registry", tool_name=tool_name)

        async with self.session_factory() as session:
            async with session.begin():
                # Find the tool
                stmt = select(DBTool).where(DBTool.name == tool_name)
                result = await session.execute(stmt)
                db_tool = result.scalar_one_or_none()

                if not db_tool:
                    log.warning("registry_stats_update_skipped_tool_not_found")
                    return

                # Record execution details
                exec_record = DBToolExecution(
                    tool_id=db_tool.id,
                    version=db_tool.current_version,
                    success=success,
                    input_data=input_data,
                    output_data=output_data,
                    error=error,
                    runtime_ms=runtime_ms,
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
                session.add(exec_record)

                # Fetch all execution stats to re-compute success rate
                stmt_all = select(DBToolExecution.success).where(
                    DBToolExecution.tool_id == db_tool.id
                )
                res_all = await session.execute(stmt_all)
                runs = res_all.scalars().all()

                total_runs = len(runs)
                successful_runs = sum(1 for r in runs if r)

                # Update DBTool attributes
                db_tool.usage_count = total_runs
                db_tool.success_rate = float(successful_runs / total_runs)
                db_tool.last_used = datetime.now(UTC)
                db_tool.updated_at = datetime.now(UTC)

            await session.commit()
            log.info(
                "registry_stats_updated",
                total_runs=total_runs,
                success_rate=db_tool.success_rate,
            )
