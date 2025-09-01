from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel, Field

from .config import get_settings


class DagRunInfo(BaseModel):
    """Container for Airflow DAG run information."""
    dag_id: str = Field(..., description="Airflow DAG identifier")
    dag_run_id: str = Field(..., description="Run identifier returned by Airflow")
    state: Optional[str] = Field(None, description="Current state of the run")
    external_trigger: Optional[bool] = Field(None, description="Whether run was externally triggered")
    conf: Optional[Dict[str, Any]] = Field(None, description="Run parameters")


# PUBLIC_INTERFACE
class AirflowClient:
    """Simple HTTP client for Airflow's REST API v2 using httpx."""

    def __init__(self, base_url: str, username: Optional[str] = None, password: Optional[str] = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AirflowClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_client(self) -> None:
        if self._client is None:
            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            self._client = httpx.AsyncClient(base_url=self.base_url, auth=auth, headers=headers, timeout=self.timeout, follow_redirects=True)

    # PUBLIC_INTERFACE
    async def trigger_dag(self, dag_id: str, conf: Optional[Dict[str, Any]] = None) -> DagRunInfo:
        """Trigger a DAG run and return DagRunInfo."""
        await self._ensure_client()
        assert self._client is not None
        payload = {"conf": conf or {}}
        # Airflow 2.3+: POST /api/v1/dags/{dag_id}/dagRuns OR /api/v1/dags/{dag_id}/dagRuns for v1; many use v2 with same path
        url = f"/api/v1/dags/{dag_id}/dagRuns"
        res = await self._client.post(url, json=payload)
        res.raise_for_status()
        data = res.json()
        return DagRunInfo(
            dag_id=dag_id,
            dag_run_id=data.get("dag_run_id") or data.get("run_id") or data.get("dag_run_id", ""),
            state=data.get("state"),
            external_trigger=data.get("external_trigger"),
            conf=data.get("conf"),
        )

    # PUBLIC_INTERFACE
    async def get_dag_run(self, dag_id: str, dag_run_id: str) -> DagRunInfo:
        """Fetch DAG run status by dag_id and dag_run_id. Used by orchestrator and in-process scheduler."""
        await self._ensure_client()
        assert self._client is not None
        url = f"/api/v1/dags/{dag_id}/dagRuns/{dag_run_id}"
        res = await self._client.get(url)
        res.raise_for_status()
        data = res.json()
        return DagRunInfo(
            dag_id=dag_id,
            dag_run_id=data.get("dag_run_id") or data.get("run_id") or dag_run_id,
            state=data.get("state"),
            external_trigger=data.get("external_trigger"),
            conf=data.get("conf"),
        )

    # PUBLIC_INTERFACE
    async def wait_for_dag_run(self, dag_id: str, dag_run_id: str, poll_interval: float = 10.0, timeout: float = 3600.0) -> DagRunInfo:
        """Poll DAG run until completion or timeout."""
        start = asyncio.get_event_loop().time()
        while True:
            info = await self.get_dag_run(dag_id, dag_run_id)
            # Typical terminal states: success, failed. Airflow states: success, failed, queued, running
            if info.state in {"success", "failed"}:
                return info
            now = asyncio.get_event_loop().time()
            if now - start >= timeout:
                return info
            await asyncio.sleep(poll_interval)


def get_airflow_client() -> AirflowClient:
    """Factory to build AirflowClient from settings."""
    s = get_settings()
    return AirflowClient(
        base_url=s.airflow_base_url or "",
        username=s.airflow_username,
        password=s.airflow_password,
        timeout=s.airflow_timeout,
    )
