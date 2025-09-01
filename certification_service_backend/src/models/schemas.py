from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

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
    metadata: Dict[str, str] = Field(default_factory=dict, description="Additional metadata to attach to the run")
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
