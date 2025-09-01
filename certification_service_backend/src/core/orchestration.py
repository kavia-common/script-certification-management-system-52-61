from __future__ import annotations

import asyncio
import math
from typing import List, Optional

from .logging_utils import get_logger
logger = get_logger(__name__)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import CertificationJob
from ..models.schemas import CertificationStatus, CertificationType
from .airflow_client import get_airflow_client
from .config import get_settings
from .audit import create_audit_log


async def _with_retries(coro_fn, attempts: int, backoff: float, base_delay: float = 0.5):
    """Execute an async callable with simple exponential backoff."""
    last_exc: Optional[Exception] = None
    for i in range(attempts):
        try:
            return await coro_fn()
        except Exception as e:
            last_exc = e
            delay = base_delay * math.pow(backoff, i)
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc


def _dag_id_for_type(cert_type: CertificationType) -> Optional[str]:
    s = get_settings()
    dag_map = s.airflow_dag_map or {}
    return dag_map.get(cert_type.value)


async def _update_job_status(session: AsyncSession, job: CertificationJob) -> None:
    """Update overall job status based on per-type results."""
    # If any running -> running; if any failed -> failed; if all passed -> passed; else pending
    await session.refresh(job)
    statuses = [r.status for r in job.results]
    if any(s == CertificationStatus.running for s in statuses):
        job.status = CertificationStatus.running
    elif any(s == CertificationStatus.failed for s in statuses):
        job.status = CertificationStatus.failed
    elif statuses and all(s == CertificationStatus.passed for s in statuses):
        job.status = CertificationStatus.passed
    else:
        job.status = CertificationStatus.pending
    await session.flush()


async def _save_dag_run_info(session: AsyncSession, job: CertificationJob, cert_type: CertificationType, dag_run_id: str) -> None:
    """Persist DAG run id into the per-type metrics for traceability."""
    # We use metrics JSON to store orchestration details minimally invasive
    result = next((r for r in job.results if r.type == cert_type), None)
    if not result:
        return
    metrics = result.metrics or {}
    metrics.setdefault("airflow", {})
    metrics["airflow"]["dag_run_id"] = dag_run_id
    metrics["airflow"]["dag_id"] = _dag_id_for_type(cert_type)
    result.metrics = metrics
    await session.flush()


async def _mark_running(session: AsyncSession, job: CertificationJob, cert_type: CertificationType) -> None:
    result = next((r for r in job.results if r.type == cert_type), None)
    if result:
        result.status = CertificationStatus.running
        await session.flush()
        await _update_job_status(session, job)
        # Audit running transition
        await create_audit_log(
            session,
            action="orchestrate_running",
            resource_type="certification_result",
            resource_id=str(result.id),
            actor="orchestrator",
            details={"job_run_id": job.run_id, "type": cert_type.value},
        )


async def _mark_terminal(session: AsyncSession, job: CertificationJob, cert_type: CertificationType, success: bool, logs_url: Optional[str] = None) -> None:
    result = next((r for r in job.results if r.type == cert_type), None)
    if result:
        result.status = CertificationStatus.passed if success else CertificationStatus.failed
        if logs_url:
            result.logs_url = logs_url
        await session.flush()
        await _update_job_status(session, job)
        # Audit terminalization
        await create_audit_log(
            session,
            action="orchestrate_terminal",
            resource_type="certification_result",
            resource_id=str(result.id),
            actor="orchestrator",
            details={"job_run_id": job.run_id, "type": cert_type.value, "success": success, "logs_url": logs_url},
        )


async def _poll_one(session_factory, job_run_id: str, cert_type: CertificationType, dag_id: str, dag_run_id: str) -> None:
    """Poll a single DAG run until completion and update DB."""
    settings = get_settings()
    async with session_factory() as session:
        res = await session.execute(select(CertificationJob).where(CertificationJob.run_id == job_run_id))
        job = res.scalar_one_or_none()
        if not job:
            return
        try:
            client = get_airflow_client()
            info = await client.wait_for_dag_run(
                dag_id=dag_id,
                dag_run_id=dag_run_id,
                poll_interval=settings.orchestration_poll_interval,
                timeout=settings.orchestration_max_poll_seconds,
            )
            success = info.state == "success"
            await _mark_terminal(session, job, cert_type, success=success)
            await session.commit()
        except Exception:
            # Mark as failed on unexpected errors
            await _mark_terminal(session, job, cert_type, success=False)
            await session.commit()


# PUBLIC_INTERFACE
async def orchestrate_job(session: AsyncSession, job: CertificationJob) -> None:
    """Trigger Airflow DAGs per certification type and start polling tasks."""
    settings = get_settings()
    client = get_airflow_client()

    # Prepare common conf to send to Airflow
    conf = {
        "run_id": job.run_id,
        "provider": job.provider,
        "project_id": job.project_id,
        "branch": job.branch,
        "commit_sha": job.commit_sha,
        "environment": job.environment,
        "metadata": job.metadata or {},
        "types": [t.value for t in CertificationJob.csv_to_types(job.types_csv)],
    }

    session_factory = type(session)  # get class
    # trigger and start polls
    poll_tasks: List[asyncio.Task] = []
    for cert_type in CertificationJob.csv_to_types(job.types_csv):
        dag_id = _dag_id_for_type(cert_type)
        if not dag_id:
            # If there is no mapping, mark as failed quickly
            await _mark_terminal(session, job, cert_type, success=False)
            continue

        async def trigger_for_type(ct: CertificationType, d_id: str):
            async def do_trigger():
                return await client.trigger_dag(dag_id=d_id, conf={**conf, "type": ct.value})

            dag_run = await _with_retries(
                do_trigger,
                attempts=settings.orchestration_retry_attempts,
                backoff=settings.orchestration_retry_backoff,
            )
            await _mark_running(session, job, ct)
            await _save_dag_run_info(session, job, ct, dag_run_id=dag_run.dag_run_id)
            # Audit trigger with dag run
            await create_audit_log(
                session,
                action="orchestrate_trigger",
                resource_type="certification_result",
                resource_id=None,
                actor="orchestrator",
                details={
                    "job_run_id": job.run_id,
                    "type": ct.value,
                    "dag_id": d_id,
                    "dag_run_id": dag_run.dag_run_id,
                },
            )
            await session.commit()
            # start background polling
            poll_tasks.append(asyncio.create_task(_poll_one(session_factory, job.run_id, ct, d_id, dag_run.dag_run_id)))

        try:
            await trigger_for_type(cert_type, dag_id)
        except Exception:
            # Mark particular type as failed if trigger fails after retries
            await _mark_terminal(session, job, cert_type, success=False)
            await session.commit()

    # Do not await poll tasks here; they run in background
    # But we can detach; caller should not be blocked.
    return None
