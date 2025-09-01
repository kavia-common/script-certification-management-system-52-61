from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field, HttpUrl


class CertificationType(str, Enum):
    """Enumeration of supported certification types."""
    code_quality = "code_quality"
    network_security = "network_security"
    manual_compliance = "manual_compliance"
    unit = "unit"
    extended_unit = "extended_unit"
    e2e = "e2e"
    soak = "soak"
    performance = "performance"


class CertificationStatus(str, Enum):
    """Status values for a certification run."""
    pending = "pending"
    running = "running"
    passed = "passed"
    failed = "failed"
    cancelled = "cancelled"


class RepositoryRef(BaseModel):
    """Represents a repository and branch/tag to certify."""
    provider: str = Field(..., description="Source provider, e.g., gitlab")
    project_id: str = Field(..., description="Unique project identifier at the provider")
    branch: str = Field(..., description="Branch or tag name")
    commit_sha: Optional[str] = Field(None, description="Specific commit SHA if known")


class TriggerCertificationRequest(BaseModel):
    """Request to trigger a certification pipeline for a repository reference."""
    repo: RepositoryRef = Field(..., description="Repository and ref details")
    types: List[CertificationType] = Field(..., description="Certification types to run")
    environment: Optional[str] = Field(None, description="Target environment mapping override")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata to attach to the run")
    notify_webhook: Optional[HttpUrl] = Field(None, description="Optional webhook to be called on status updates")


class CertificationRunResponse(BaseModel):
    """Response carrying certification run details."""
    run_id: str = Field(..., description="Unique identifier of the certification run")
    status: CertificationStatus = Field(..., description="Current status of the run")
    created_at: datetime = Field(..., description="Creation timestamp")
    types: List[CertificationType] = Field(..., description="Types included in the run")
    environment: Optional[str] = Field(None, description="Environment mapped for the run")


class HealthResponse(BaseModel):
    """Health check response."""
    message: str = Field(..., description="Service health message")
    db_connected: bool = Field(..., description="Whether DB connection succeeded")


# Branch-environment mappings
class MappingItem(BaseModel):
    """Branch to environment mapping item."""
    provider: str = Field(..., description="Source provider")
    project_id: str = Field(..., description="Project identifier")
    branch_pattern: str = Field(..., description="Glob/regex-like branch pattern")
    environment: str = Field(..., description="Target environment")
    is_active: bool = Field(default=True, description="Whether mapping is active")


class MappingResponse(BaseModel):
    """Response for mapping operations."""
    id: int = Field(..., description="Mapping ID")
    provider: str
    project_id: str
    branch_pattern: str
    environment: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# Metadata
class MetadataUpsert(BaseModel):
    """Create or update metadata entry."""
    key: str = Field(..., description="Metadata key")
    value: Dict[str, Any] = Field(..., description="Arbitrary JSON value")
    provider: Optional[str] = Field(None, description="Optional scope provider")
    project_id: Optional[str] = Field(None, description="Optional scope project ID")
    branch: Optional[str] = Field(None, description="Optional scope branch")


class MetadataItemResponse(BaseModel):
    """Metadata row response."""
    id: int
    key: str
    value: Dict[str, Any]
    provider: Optional[str]
    project_id: Optional[str]
    branch: Optional[str]
    created_at: datetime
    updated_at: datetime


class PatchCertificationRequest(BaseModel):
    """Patch fields for an existing certification job."""
    status: Optional[CertificationStatus] = Field(None, description="Update overall job status")
    environment: Optional[str] = Field(None, description="Update environment")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Replace metadata dictionary")
