from datetime import datetime, timezone
from typing import Any
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Text, ForeignKey, Boolean
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
    input_schema = Column(JSON, default=dict, nullable=False)   # Expected inputs
    output_schema = Column(JSON, default=dict, nullable=False)  # Expected outputs
    tags = Column(JSON, default=list, nullable=False)           # Categorization tags
    current_version = Column(Integer, default=1, nullable=False)
    success_rate = Column(Float, default=0.0, nullable=False)
    usage_count = Column(Integer, default=0, nullable=False)
    status = Column(String, default="active", nullable=False)  # active, deprecated, failed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    last_used = Column(DateTime, nullable=True)
    
    versions = relationship("DBToolVersion", back_populates="tool", cascade="all, delete-orphan")
    executions = relationship("DBToolExecution", back_populates="tool", cascade="all, delete-orphan")

class DBToolVersion(Base):
    __tablename__ = "tool_versions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_id = Column(Integer, ForeignKey("tools.id"), nullable=False)
    version = Column(Integer, nullable=False)
    code_hash = Column(String, nullable=False)
    prompt_used = Column(Text, nullable=False)
    change_reason = Column(Text, default="initial", nullable=False)
    test_results = Column(JSON, default=dict, nullable=False)   # test outcome metrics
    runtime_stats = Column(JSON, default=dict, nullable=False)  # avg latency, max memory, etc.
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
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
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    tool = relationship("DBTool", back_populates="executions")
