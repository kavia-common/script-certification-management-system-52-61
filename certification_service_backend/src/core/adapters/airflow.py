from __future__ import annotations

import abc
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DagRunInfo(BaseModel):
    """Minimal DAG run info used by orchestration and scheduler."""
    dag_id: str = Field(..., description="Airflow DAG identifier")
    dag_run_id: str = Field(..., description="Run identifier")
    state: Optional[str] = Field(None, description="Current state, e.g., success/failed")
    external_trigger: Optional[bool] = Field(None, description="Externally triggered flag")
    conf: Optional[Dict[str, Any]] = Field(None, description="Run configuration")


class BaseAirflowAdapter(abc.ABC):
    """Abstract adapter for Airflow operations."""

    @abc.abstractmethod
    async def trigger_dag(self, dag_id: str, conf: Optional[Dict[str, Any]] = None) -> DagRunInfo:
        """Trigger a DAG run and return run info."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_dag_run(self, dag_id: str, dag_run_id: str) -> DagRunInfo:
        """Fetch DAG run info."""
        raise NotImplementedError

    # PUBLIC_INTERFACE
    async def wait_for_dag_run(self, dag_id: str, dag_run_id: str, poll_interval: float = 10.0, timeout: float = 3600.0) -> DagRunInfo:
        """Default polling implementation; adapters may override for efficiency."""
        import asyncio
        from time import monotonic
        start = monotonic()
        while True:
            info = await self.get_dag_run(dag_id, dag_run_id)
            if (info.state or "").lower() in {"success", "failed"}:
                return info
            if monotonic() - start >= timeout:
                return info
            await asyncio.sleep(poll_interval)


# Simple indirection hook for obtaining an airflow adapter.
# By default, the concrete httpx client in src/core/airflow_client.py is used.
_AIRFLOW_ADAPTER_FACTORY = None


# PUBLIC_INTERFACE
def set_airflow_adapter_factory(factory):
    """Set a global factory used by get_airflow_adapter(). Useful for plug-ins or tests."""
    global _AIRFLOW_ADAPTER_FACTORY
    _AIRFLOW_ADAPTER_FACTORY = factory


# PUBLIC_INTERFACE
def get_airflow_adapter() -> BaseAirflowAdapter:
    """Return the current airflow adapter instance."""
    if _AIRFLOW_ADAPTER_FACTORY:
        return _AIRFLOW_ADAPTER_FACTORY()
    # Fallback adapter wraps the existing AirflowClient to preserve current behavior
    from ..airflow_client import get_airflow_client
    client = get_airflow_client()

    class _WrappedAdapter(BaseAirflowAdapter):
        async def trigger_dag(self, dag_id: str, conf: Optional[Dict[str, Any]] = None) -> DagRunInfo:
            info = await client.trigger_dag(dag_id=dag_id, conf=conf)
            return DagRunInfo.model_validate(info.model_dump())

        async def get_dag_run(self, dag_id: str, dag_run_id: str) -> DagRunInfo:
            info = await client.get_dag_run(dag_id=dag_id, dag_run_id=dag_run_id)
            return DagRunInfo.model_validate(info.model_dump())

        async def wait_for_dag_run(self, dag_id: str, dag_run_id: str, poll_interval: float = 10.0, timeout: float = 3600.0) -> DagRunInfo:
            info = await client.wait_for_dag_run(dag_id=dag_id, dag_run_id=dag_run_id, poll_interval=poll_interval, timeout=timeout)
            return DagRunInfo.model_validate(info.model_dump())

    return _WrappedAdapter()
