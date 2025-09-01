from __future__ import annotations

import uuid
from typing import List, Optional, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import (
    AuditLog,
    BranchEnvironmentMapping,
    CertificationJob,
    CertificationResult,
    MetadataItem,
)
from ..models.schemas import CertificationStatus, TriggerCertificationRequest, PatchCertificationRequest


# PUBLIC_INTERFACE
async def create_audit_log(session: AsyncSession, action: str, resource_type: str, resource_id: Optional[str], actor: Optional[str], details: Optional[Dict[str, Any]] = None) -> None:
    """Create an audit log entry for a mutating operation."""
    session.add(AuditLog(action=action, resource_type=resource_type, resource_id=resource_id, actor=actor, details=details or {}))


# PUBLIC_INTERFACE
async def create_certification_job(session: AsyncSession, req: TriggerCertificationRequest) -> CertificationJob:
    """Create a new certification job and its per-type result rows."""
    run_id = uuid.uuid4().hex[:16]
    job = CertificationJob(
        run_id=run_id,
        provider=req.repo.provider,
        project_id=req.repo.project_id,
        branch=req.repo.branch,
        commit_sha=req.repo.commit_sha,
        types_csv=CertificationJob.types_to_csv(req.types),
        environment=req.environment,
        status=CertificationStatus.pending,
        metadata=req.metadata or {},
        notify_webhook=str(req.notify_webhook) if req.notify_webhook else None,
    )
    session.add(job)
    await session.flush()
    # per-type results initialized as pending
    for t in req.types:
        session.add(CertificationResult(job_id=job.id, type=t, status=CertificationStatus.pending))
    return job


# PUBLIC_INTERFACE
async def get_certification_job_by_run_id(session: AsyncSession, run_id: str) -> Optional[CertificationJob]:
    """Fetch a job by run_id."""
    res = await session.execute(select(CertificationJob).where(CertificationJob.run_id == run_id))
    return res.scalar_one_or_none()


# PUBLIC_INTERFACE
async def patch_certification_job(session: AsyncSession, run_id: str, patch: PatchCertificationRequest) -> Optional[CertificationJob]:
    """Patch updatable fields on job."""
    job = await get_certification_job_by_run_id(session, run_id)
    if not job:
        return None
    if patch.status is not None:
        job.status = patch.status
    if patch.environment is not None:
        job.environment = patch.environment
    if patch.metadata is not None:
        job.metadata = patch.metadata
    await session.flush()
    return job


# PUBLIC_INTERFACE
async def list_mappings(session: AsyncSession, provider: Optional[str] = None, project_id: Optional[str] = None) -> List[BranchEnvironmentMapping]:
    """List branch-environment mappings with optional filtering."""
    stmt = select(BranchEnvironmentMapping)
    if provider:
        stmt = stmt.where(BranchEnvironmentMapping.provider == provider)
    if project_id:
        stmt = stmt.where(BranchEnvironmentMapping.project_id == project_id)
    res = await session.execute(stmt.order_by(BranchEnvironmentMapping.id.desc()))
    return list(res.scalars().all())


# PUBLIC_INTERFACE
async def create_mapping(session: AsyncSession, item: Dict[str, Any]) -> BranchEnvironmentMapping:
    """Create a branch-environment mapping."""
    mapping = BranchEnvironmentMapping(
        provider=item["provider"],
        project_id=item["project_id"],
        branch_pattern=item["branch_pattern"],
        environment=item["environment"],
        is_active=item.get("is_active", True),
    )
    session.add(mapping)
    await session.flush()
    return mapping


# PUBLIC_INTERFACE
async def list_metadata(session: AsyncSession, filters: Dict[str, Optional[str]]) -> List[MetadataItem]:
    """List metadata items filtered by optional scope and key."""
    stmt = select(MetadataItem)
    if filters.get("provider"):
        stmt = stmt.where(MetadataItem.provider == filters["provider"])
    if filters.get("project_id"):
        stmt = stmt.where(MetadataItem.project_id == filters["project_id"])
    if filters.get("branch"):
        stmt = stmt.where(MetadataItem.branch == filters["branch"])
    if filters.get("key"):
        stmt = stmt.where(MetadataItem.key == filters["key"])
    res = await session.execute(stmt.order_by(MetadataItem.id.desc()))
    return list(res.scalars().all())


# PUBLIC_INTERFACE
async def upsert_metadata(session: AsyncSession, payload: Dict[str, Any]) -> MetadataItem:
    """Upsert metadata by (provider, project_id, branch, key)."""
    stmt = select(MetadataItem).where(
        MetadataItem.key == payload["key"],
        MetadataItem.provider == payload.get("provider"),
        MetadataItem.project_id == payload.get("project_id"),
        MetadataItem.branch == payload.get("branch"),
    )
    res = await session.execute(stmt)
    existing = res.scalar_one_or_none()
    if existing:
        existing.value = payload["value"]
        await session.flush()
        return existing
    # create new
    item = MetadataItem(
        key=payload["key"],
        value=payload["value"],
        provider=payload.get("provider"),
        project_id=payload.get("project_id"),
        branch=payload.get("branch"),
    )
    session.add(item)
    await session.flush()
    return item
