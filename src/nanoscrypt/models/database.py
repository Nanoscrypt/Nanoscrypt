from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class DBTool(Base):
    __tablename__ = "tools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, index=True, nullable=False)
    purpose = Column(Text, nullable=False)
    language = Column(String, default="python", nullable=False)
    entry_point = Column(String, default="tool.py", nullable=False)
    dependencies = Column(JSON, default=list, nullable=False)  # List of strings
    input_schema = Column(JSON, default=dict, nullable=False)  # Expected inputs
    output_schema = Column(JSON, default=dict, nullable=False)  # Expected outputs
    tags = Column(JSON, default=list, nullable=False)  # Categorization tags
    current_version = Column(Integer, default=1, nullable=False)
    success_rate = Column(Float, default=0.0, nullable=False)
    usage_count = Column(Integer, default=0, nullable=False)
    status = Column(
        String, default="active", nullable=False
    )  # active, deprecated, failed
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    last_used = Column(DateTime, nullable=True)

    versions = relationship(
        "DBToolVersion", back_populates="tool", cascade="all, delete-orphan"
    )
    executions = relationship(
        "DBToolExecution", back_populates="tool", cascade="all, delete-orphan"
    )


class DBToolVersion(Base):
    __tablename__ = "tool_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_id = Column(Integer, ForeignKey("tools.id"), nullable=False)
    version = Column(Integer, nullable=False)
    code_hash = Column(String, nullable=False)
    prompt_used = Column(Text, nullable=False)
    change_reason = Column(Text, default="initial", nullable=False)
    test_results = Column(JSON, default=dict, nullable=False)  # test outcome metrics
    runtime_stats = Column(
        JSON, default=dict, nullable=False
    )  # avg latency, max memory, etc.
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    tool = relationship("DBTool", back_populates="versions")


class DBToolExecution(Base):
    __tablename__ = "tool_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_id = Column(Integer, ForeignKey("tools.id"), nullable=False)
    version = Column(Integer, nullable=False)
    success = Column(Boolean, nullable=False)
    input_data = Column(JSON, default=dict, nullable=False)
    output_data = Column(JSON, default=dict, nullable=True)
    error = Column(Text, nullable=True)
    runtime_ms = Column(Integer, nullable=False)
    started_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    completed_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    tool = relationship("DBTool", back_populates="executions")


# --- ENTERPRISE TABLES V0.2.0 ---


class DBMemoryEntry(Base):
    __tablename__ = "memory_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, index=True, nullable=False)
    value = Column(Text, nullable=False)
    category = Column(String, default="general", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class DBAuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String, index=True, nullable=False)
    session_id = Column(String, index=True, nullable=False)
    agent_name = Column(String, nullable=False)
    details = Column(JSON, default=dict, nullable=False)
    cost = Column(Float, default=0.0, nullable=False)
    token_usage = Column(Integer, default=0, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class DBAgentDefinition(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, nullable=False)
    goal = Column(Text, nullable=False)
    backstory = Column(Text, default="", nullable=False)
    tools = Column(JSON, default=list, nullable=False)
    permissions = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class DBApprovalRecord(Base):
    __tablename__ = "approvals"

    id = Column(String, primary_key=True)
    session_id = Column(String, index=True, nullable=False)
    approval_type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    risk_level = Column(String, nullable=False)
    resource_details = Column(JSON, default=dict, nullable=False)
    agent_name = Column(String, default="orchestrator", nullable=False)
    status = Column(String, default="pending", nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    reason = Column(Text, nullable=True)
