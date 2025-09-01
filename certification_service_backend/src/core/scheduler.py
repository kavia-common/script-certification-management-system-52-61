from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .airflow_client import get_airflow_client
from .config import get_settings
from .db import get_session_factory
from ..models.db_models import CertificationJob, CertificationResult
from ..models.schemas import CertificationStatus


class _SchedulerState:
    """Internal scheduler state holder."""
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def set_task(self, task: asyncio.Task) -> None:
        self._task = task

    def stop_event(self) -> asyncio.Event:
        return self._stop_event

    def clear(self) -> None:
        self._task = None
        self._stop_event = asyncio.Event()


_state = _SchedulerState()


async def _reconcile_job(session: AsyncSession, job: CertificationJob) -> None:
    """Reconcile one job: check each active type's Airflow run and update status."""
    # Determine active (non-terminal) results
    active_results = [r for r in job.results if r.status in (CertificationStatus.pending, CertificationStatus.running)]
    if not active_results:
        return

    client = get_airflow_client()
    updated_any = False

    for r in active_results:
        # Try to find airflow dag_run_id in metrics
        dag_run_id = None
        dag_id = None
        if r.metrics and isinstance(r.metrics, dict):
            af = (r.metrics or {}).get("airflow") or {}
            dag_run_id = af.get("dag_run_id")
            dag_id = af.get("dag_id")
        # If no DAG info known yet, skip. Orchestration is responsible for creation.
        if not dag_run_id or not dag_id:
            continue

        try:
            info = await client.get_dag_run(dag_id=dag_id, dag_run_id=dag_run_id)
            state = (info.state or "").lower()
            if state in {"success", "failed"}:
                # Terminalize the result
                r.status = CertificationStatus.passed if state == "success" else CertificationStatus.failed
                updated_any = True
        except Exception:
            # On error, do not flip state; rely on next runs or webhook
            continue

    if updated_any:
        # Recompute aggregate status similar to orchestration
        from .orchestration import _update_job_status
        await _update_job_status(session, job)
        await session.flush()


async def _scheduler_loop() -> None:
    """Main scheduler loop that periodically polls active certification jobs."""
    s = get_settings()
    poll_interval = max(5.0, float(s.orchestration_poll_interval))  # ensure not too aggressive
    session_factory = get_session_factory()

    stop_evt = _state.stop_event()

    while not stop_evt.is_set():
        try:
            async with session_factory() as session:
                # Load jobs that have any non-terminal results OR overall non-terminal status
                # We check both to be resilient to out-of-sync aggregate status.
                jobs_stmt = (
                    select(CertificationJob)
                    .where(
                        or_(
                            CertificationJob.status.in_(
                                [CertificationStatus.pending, CertificationStatus.running]
                            ),
                            CertificationJob.id.in_(
                                select(CertificationResult.job_id).where(
                                    CertificationResult.status.in_(
                                        [CertificationStatus.pending, CertificationStatus.running]
                                    )
                                )
                            ),
                        )
                    )
                    .order_by(CertificationJob.id.desc())
                )
                jobs_res = await session.execute(jobs_stmt)
                jobs = list(jobs_res.scalars().unique().all())

                # Eagerly load results for each job (relationship may be lazy)
                # Using access triggers lazy load anyway in sqlalchemy async
                for job in jobs:
                    _ = job.results  # access relationship

                for job in jobs:
                    await _reconcile_job(session, job)

                await session.commit()
        except Exception:
            # Avoid crashing the loop on transient errors
            with suppress(Exception):
                async with session_factory() as s2:
                    await s2.rollback()
            # Sleep a minimal backoff before retry cycle
            await asyncio.sleep(poll_interval)
        else:
            # Normal cycle sleep
            await asyncio.sleep(poll_interval)


# PUBLIC_INTERFACE
async def start_scheduler() -> None:
    """Start the in-process certification reconciliation scheduler, if not already running."""
    if _state.is_running():
        return
    _state.clear()
    task = asyncio.create_task(_scheduler_loop(), name="cert_scheduler_loop")
    _state.set_task(task)


# PUBLIC_INTERFACE
async def stop_scheduler() -> None:
    """Stop the in-process scheduler and wait for graceful shutdown."""
    if not _state.is_running():
        _state.clear()
        return
    _state.stop_event().set()
    task = getattr(_state, "_task", None)
    if task:
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=10.0)
    _state.clear()
