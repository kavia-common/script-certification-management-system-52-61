from __future__ import annotations

from typing import List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.db import db_healthcheck, get_db_session
from ..core.migrations import init_models
from ..core.repository import (
    create_audit_log,
    create_certification_job,
    create_mapping,
    get_certification_job_by_run_id,
    list_mappings,
    list_metadata,
    patch_certification_job,
    upsert_metadata,
    update_result_state_by_webhook,
)
from ..core.audit import extract_actor_from_headers, build_request_context
from ..models.db_models import CertificationJob
from ..models.schemas import (
    CertificationRunResponse,
    HealthResponse,
    MappingItem,
    MappingResponse,
    MetadataItemResponse,
    MetadataUpsert,
    PatchCertificationRequest,
    TriggerCertificationRequest,
    AirflowTaskEvent,
    WebhookAck,
    GitLabWebhookPush,
)

settings = get_settings()

openapi_tags = [
    {"name": "Health", "description": "Health and readiness endpoints"},
    {"name": "Certifications", "description": "Create and manage certification jobs"},
    {"name": "Mappings", "description": "Branch to environment mappings"},
    {"name": "Metadata", "description": "Certification metadata management"},
    {"name": "Webhooks", "description": "Inbound webhook endpoints for orchestration updates and triggers"},
]

app = FastAPI(
    title=settings.app_name,
    description="Service to manage and orchestrate certification jobs for scripts.",
    version="0.1.0",
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)


from ..core.db import get_session_factory
from ..core.orchestration import orchestrate_job
from sqlalchemy import select

async def _background_trigger_orchestration(run_id: str) -> None:
    """Background task to orchestrate the certification job via Airflow DAGs."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        from ..models.db_models import CertificationJob  # local import to avoid cycles
        res = await session.execute(select(CertificationJob).where(CertificationJob.run_id == run_id))
        job = res.scalar_one_or_none()
        if not job:
            return
        try:
            await orchestrate_job(session, job)
        except Exception:
            # Best-effort error handling: mark job as failed
            job.status = job.status or None  # no-op: keep last known status; individual types will be updated already
            await session.commit()
    return None


@app.on_event("startup")
async def on_startup() -> None:
    """Initialize database models on startup (dev convenience) and start scheduler."""
    await init_models()
    # Start in-process scheduler for job reconciliation
    from ..core.scheduler import start_scheduler
    await start_scheduler()


# PUBLIC_INTERFACE
@app.get("/", tags=["Health"], summary="Health Check")
def health_check_sync() -> dict:
    """Quick synchronous health check."""
    return {"message": "Healthy"}


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Gracefully stop scheduler."""
    from ..core.scheduler import stop_scheduler
    await stop_scheduler()


# PUBLIC_INTERFACE
@app.get("/health", tags=["Health"], summary="Health with DB status", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return health and DB connectivity status."""
    ok = await db_healthcheck()
    return HealthResponse(message="Healthy", db_connected=ok)


def _job_to_response(job: CertificationJob) -> CertificationRunResponse:
    return CertificationRunResponse(
        run_id=job.run_id,
        status=job.status,
        created_at=job.created_at,
        types=CertificationJob.csv_to_types(job.types_csv),
        environment=job.environment,
    )


# PUBLIC_INTERFACE
@app.post(
    "/certifications",
    status_code=status.HTTP_201_CREATED,
    tags=["Certifications"],
    summary="Create a certification job",
    response_model=CertificationRunResponse,
    responses={
        201: {"description": "Certification job created"},
        400: {"description": "Invalid request"},
    },
)
async def create_certification(
    payload: TriggerCertificationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    request: Request = None,
    actor_header: Optional[str] = Depends(extract_actor_from_headers),
) -> CertificationRunResponse:
    """Create a certification job, persist in DB, audit log, and trigger background orchestration.

    Audit:
    - action: create
    - resource_type: certification_job
    - resource_id: run_id
    - actor: extracted from headers/token
    - details: provider/project/branch, payload snapshot, and request context
    """
    job = await create_certification_job(db, payload)
    await create_audit_log(
        db,
        action="create",
        resource_type="certification_job",
        resource_id=job.run_id,
        actor=actor_header,
        details={
            "provider": job.provider,
            "project_id": job.project_id,
            "branch": job.branch,
            "payload": payload.model_dump(exclude_none=True),
            "request": build_request_context(request),
        },
    )
    await db.commit()
    # trigger background orchestration without blocking request
    background_tasks.add_task(_background_trigger_orchestration, job.run_id)
    return _job_to_response(job)


# PUBLIC_INTERFACE
@app.post(
    "/webhooks/gitlab",
    tags=["Webhooks"],
    summary="GitLab webhook (optional trigger)",
    description="Optional: Trigger a default certification job from GitLab push/MR events. Secured via X-Gitlab-Token or X-Webhook-Secret.",
    response_model=WebhookAck,
    responses={
        200: {"description": "Accepted"},
        401: {"description": "Unauthorized"},
    },
)
async def gitlab_webhook(
    payload: GitLabWebhookPush,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    x_gitlab_token: Optional[str] = Header(default=None, alias="X-Gitlab-Token"),
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
    request: Request = None,
) -> WebhookAck:
    """Optionally accept GitLab push/MR events and trigger a certification job.
    Minimal implementation: when object_kind in {push} it triggers job for the branch in `ref`.
    Mapping of types/environment should be done by client metadata or defaults.
    """
    s = settings
    expected_gl = s.gitlab_webhook_secret
    expected_generic = s.webhook_secret
    if expected_gl:
        if (x_gitlab_token or "") != expected_gl:
            raise HTTPException(status_code=401, detail="Invalid GitLab token")
    elif expected_generic:
        if (x_webhook_secret or "") != expected_generic:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
    # else if no secret configured, accept (dev mode)

    # Only react to push events
    if (payload.object_kind or "").lower() != "push":
        return WebhookAck(accepted=True, message="Ignored event")

    # Get branch from ref like 'refs/heads/feature-x'
    ref = payload.ref or ""
    branch = ref.split("/", 2)[-1] if ref.startswith("refs/") and "/" in ref else ref

    # Build a default TriggerCertificationRequest; choose conservative type 'code_quality'
    from ..models.schemas import RepositoryRef, TriggerCertificationRequest, CertificationType
    if (not payload.project or "id" not in (payload.project or {})) and payload.project_id is None:
        return WebhookAck(accepted=True, message="Missing project info; ignored")

    project_id = str(payload.project.get("id") if payload.project else payload.project_id)
    req = TriggerCertificationRequest(
        repo=RepositoryRef(provider="gitlab", project_id=project_id, branch=branch, commit_sha=payload.checkout_sha),
        types=[CertificationType.code_quality],
        environment=None,
        metadata={"trigger": "gitlab_webhook", "user": payload.user_username},
    )
    job = await create_certification_job(db, req)
    await create_audit_log(
        db,
        action="webhook_create",
        resource_type="certification_job",
        resource_id=job.run_id,
        actor=payload.user_username,
        details={
            "provider": job.provider,
            "project_id": job.project_id,
            "branch": job.branch,
            "source": "gitlab_webhook",
            "payload": payload.model_dump(exclude_none=True),
            "request": {
                **build_request_context(request),
                "secrets_present": {
                    "x_gitlab_token": bool(x_gitlab_token),
                    "x_webhook_secret": bool(x_webhook_secret),
                },
            },
        },
    )
    await db.commit()
    # Trigger orchestration in background
    background_tasks.add_task(_background_trigger_orchestration, job.run_id)

    return WebhookAck(accepted=True, message="Triggered certification job")


# PUBLIC_INTERFACE
@app.get(
    "/certifications/{run_id}",
    tags=["Certifications"],
    summary="Get certification job by run_id",
    response_model=CertificationRunResponse,
    responses={404: {"description": "Not found"}},
)
async def get_certification(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> CertificationRunResponse:
    """Retrieve certification job by its run_id."""
    job = await get_certification_job_by_run_id(db, run_id)
    if not job:
        raise HTTPException(status_code=404, detail="Certification job not found")
    return _job_to_response(job)


# PUBLIC_INTERFACE
@app.patch(
    "/certifications/{run_id}",
    tags=["Certifications"],
    summary="Patch certification job",
    response_model=CertificationRunResponse,
    responses={404: {"description": "Not found"}},
)
async def patch_certification(
    run_id: str,
    payload: PatchCertificationRequest,
    db: AsyncSession = Depends(get_db_session),
    request: Request = None,
    actor_header: Optional[str] = Depends(extract_actor_from_headers),
) -> CertificationRunResponse:
    """Patch fields of an existing certification job and audit the change.

    Audit:
    - action: patch
    - resource_type: certification_job
    - resource_id: run_id
    - actor: extracted from headers
    - details: patch payload and request context
    """
    job = await patch_certification_job(db, run_id, payload)
    if not job:
        raise HTTPException(status_code=404, detail="Certification job not found")
    await create_audit_log(
        db,
        action="patch",
        resource_type="certification_job",
        resource_id=run_id,
        actor=actor_header,
        details={"payload": payload.model_dump(exclude_none=True), "request": build_request_context(request)},
    )
    await db.commit()
    return _job_to_response(job)


# Mappings endpoints
# PUBLIC_INTERFACE
@app.get(
    "/mappings",
    tags=["Mappings"],
    summary="List branch-environment mappings",
    response_model=List[MappingResponse],
)
async def get_mappings(
    provider: Optional[str] = Query(default=None, description="Filter by provider"),
    project_id: Optional[str] = Query(default=None, description="Filter by project_id"),
    db: AsyncSession = Depends(get_db_session),
) -> List[MappingResponse]:
    """List mappings filtered by optional provider and project_id."""
    rows = await list_mappings(db, provider=provider, project_id=project_id)
    return [
        MappingResponse(
            id=r.id,
            provider=r.provider,
            project_id=r.project_id,
            branch_pattern=r.branch_pattern,
            environment=r.environment,
            is_active=r.is_active,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


# PUBLIC_INTERFACE
@app.post(
    "/mappings",
    tags=["Mappings"],
    summary="Create a branch-environment mapping",
    status_code=status.HTTP_201_CREATED,
    response_model=MappingResponse,
)
async def post_mapping(
    payload: MappingItem,
    db: AsyncSession = Depends(get_db_session),
    request: Request = None,
    actor_header: Optional[str] = Depends(extract_actor_from_headers),
) -> MappingResponse:
    """Create a new branch-environment mapping and audit the operation.

    Audit:
    - action: create
    - resource_type: mapping
    - resource_id: id
    - actor: extracted from headers
    - details: payload and request context
    """
    mapping = await create_mapping(db, payload.model_dump())
    await create_audit_log(
        db,
        action="create",
        resource_type="mapping",
        resource_id=str(mapping.id),
        actor=actor_header,
        details={"payload": payload.model_dump(), "request": build_request_context(request)},
    )
    await db.commit()
    return MappingResponse(
        id=mapping.id,
        provider=mapping.provider,
        project_id=mapping.project_id,
        branch_pattern=mapping.branch_pattern,
        environment=mapping.environment,
        is_active=mapping.is_active,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


# Metadata endpoints
# PUBLIC_INTERFACE
@app.get(
    "/metadata",
    tags=["Metadata"],
    summary="List metadata",
    response_model=List[MetadataItemResponse],
)
async def get_metadata(
    key: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    project_id: Optional[str] = Query(default=None),
    branch: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> List[MetadataItemResponse]:
    """List metadata items filtered by optional scope and key."""
    items = await list_metadata(db, {"key": key, "provider": provider, "project_id": project_id, "branch": branch})
    return [
        MetadataItemResponse(
            id=i.id,
            key=i.key,
            value=i.value,
            provider=i.provider,
            project_id=i.project_id,
            branch=i.branch,
            created_at=i.created_at,
            updated_at=i.updated_at,
        )
        for i in items
    ]


# PUBLIC_INTERFACE
@app.post(
    "/metadata",
    tags=["Metadata"],
    summary="Upsert metadata item",
    response_model=MetadataItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_metadata(
    payload: MetadataUpsert,
    db: AsyncSession = Depends(get_db_session),
    request: Request = None,
    actor_header: Optional[str] = Depends(extract_actor_from_headers),
) -> MetadataItemResponse:
    """Upsert a metadata item (insert if not exists, else update).

    Audit:
    - action: upsert
    - resource_type: metadata
    - resource_id: id
    - actor: extracted from headers
    - details: payload and request context
    """
    item = await upsert_metadata(db, payload.model_dump())
    await create_audit_log(
        db,
        action="upsert",
        resource_type="metadata",
        resource_id=str(item.id),
        actor=actor_header,
        details={"payload": payload.model_dump(), "request": build_request_context(request)},
    )
    await db.commit()
    return MetadataItemResponse(
        id=item.id,
        key=item.key,
        value=item.value,
        provider=item.provider,
        project_id=item.project_id,
        branch=item.branch,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


# PUBLIC_INTERFACE
@app.post(
    "/webhooks/airflow",
    tags=["Webhooks"],
    summary="Airflow state webhook",
    description="Receive Airflow DAG/task events to update certification states. Secured via X-Webhook-Secret header.",
    response_model=WebhookAck,
    responses={
        200: {"description": "Accepted"},
        401: {"description": "Unauthorized"},
        400: {"description": "Invalid payload"},
    },
)
async def airflow_webhook(
    payload: AirflowTaskEvent,
    db: AsyncSession = Depends(get_db_session),
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
    request: Request = None,
) -> WebhookAck:
    """Accept Airflow callbacks to update result/job states by run_id and optional type.
    The service uses shared secret validation. When accepted, updates the corresponding
    CertificationResult and recomputes the aggregate CertificationJob status. Polling remains active concurrently.

    Audit:
    - action: webhook_update
    - resource_type: certification_job
    - resource_id: run_id
    - actor: 'airflow' (system) when secret checked, else None (dev)
    - details: payload snapshot, request context, token presence indicator
    """
    s = settings
    expected = s.webhook_secret
    if expected and (x_webhook_secret or "") != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    job = await update_result_state_by_webhook(db, run_id=payload.run_id, cert_type=payload.type, state=payload.state, logs_url=payload.logs_url)
    if not job:
        raise HTTPException(status_code=400, detail="Unknown run_id")

    # audit webhook
    await create_audit_log(
        db,
        action="webhook_update",
        resource_type="certification_job",
        resource_id=payload.run_id,
        actor="airflow" if expected else None,
        details={
            "payload": payload.model_dump(exclude_none=True),
            "request": {
                **build_request_context(request),
                "secrets_present": {"x_webhook_secret": bool(x_webhook_secret)},
            },
        },
    )

    await db.commit()
    return WebhookAck(accepted=True, message="Airflow event processed")
