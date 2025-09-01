from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .schemas import CertificationStatus, CertificationType


class Base(DeclarativeBase):
    """Base declarative model."""
    pass


class AuditLog(Base):
    """Audit log entries for mutating API operations."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class CertificationJob(Base):
    """Represents a certification job/run."""
    __tablename__ = "certification_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    branch: Mapped[str] = mapped_column(String(128), nullable=False)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    types_csv: Mapped[str] = mapped_column(String(256), nullable=False)
    environment: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[CertificationStatus] = mapped_column(Enum(CertificationStatus), default=CertificationStatus.pending, nullable=False)
    metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    notify_webhook: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # relationships
    results: Mapped[list["CertificationResult"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    @staticmethod
    def types_to_csv(types: list[CertificationType]) -> str:
        return ",".join(t.value for t in types)

    @staticmethod
    def csv_to_types(csv: str) -> list[CertificationType]:
        if not csv:
            return []
        return [CertificationType(x) for x in csv.split(",")]


class CertificationResult(Base):
    """Per-type result details for a job."""
    __tablename__ = "certification_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("certification_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[CertificationType] = mapped_column(Enum(CertificationType), nullable=False)
    status: Mapped[CertificationStatus] = mapped_column(Enum(CertificationStatus), nullable=False, default=CertificationStatus.pending)
    logs_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    job: Mapped[CertificationJob] = relationship(back_populates="results")


class BranchEnvironmentMapping(Base):
    """Configurable mapping between branches and target environments."""
    __tablename__ = "branch_env_mappings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    branch_pattern: Mapped[str] = mapped_column(String(256), nullable=False)
    environment: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MetadataItem(Base):
    """Arbitrary key/value metadata entries, optionally scoped to provider/project/branch."""
    __tablename__ = "metadata_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    branch: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    value: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
