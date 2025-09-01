"""Adapter interfaces and factories for external services.

This module exposes abstract base classes and minimal factories for:
- Repository providers (e.g., GitLab, future GitHub/Bitbucket)
- Airflow orchestration (base client adapter)
- Kubernetes integration (stub)

These abstractions decouple the orchestration core from vendor-specific SDKs
and enable plug-in support by implementing the corresponding base classes and
registering them in factories.
"""
from .repos import (
    BaseRepoAdapter,
    RepoInfo,
    get_repo_adapter_factory,
)
from .airflow import BaseAirflowAdapter, DagRunInfo, get_airflow_adapter
from .k8s import BaseKubernetesAdapter, get_kubernetes_adapter

__all__ = [
    # Repos
    "BaseRepoAdapter",
    "RepoInfo",
    "get_repo_adapter_factory",
    # Airflow
    "BaseAirflowAdapter",
    "DagRunInfo",
    "get_airflow_adapter",
    # Kubernetes
    "BaseKubernetesAdapter",
    "get_kubernetes_adapter",
]
