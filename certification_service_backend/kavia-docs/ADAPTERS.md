# Adapter Layer (Repositories, Airflow, Kubernetes)

## Overview
To enable future plug-in support without refactoring the orchestration core, the service introduces base adapter classes and factories for:
- Repository providers (src/core/adapters/repos.py)
- Airflow orchestration (src/core/adapters/airflow.py)
- Kubernetes integration (src/core/adapters/k8s.py) — stub

These abstractions allow you to register new providers or swap implementations at runtime (e.g., tests, different environments).

## Repository Adapters

- Base class: BaseRepoAdapter
- Data model: RepoInfo
- Registry-based factory:
  - register_repo_adapter(provider: str, factory: Callable[[], BaseRepoAdapter])
  - get_repo_adapter_factory(provider: str) -> Optional[Callable]

The built-in GitLab adapter is still implemented in src/core/repo_adapters.py and is registered automatically at import time. Existing code that calls core.repo_adapters.get_repo_adapter continues to function.

To add a new provider:
1. Implement a subclass of BaseRepoAdapter.
2. Register a factory:
   ```
   from src.core.adapters.repos import register_repo_adapter
   register_repo_adapter("github", lambda: GitHubAdapter(...))
   ```

## Airflow Adapter

- Base class: BaseAirflowAdapter
- Model: DagRunInfo
- Factory hook: set_airflow_adapter_factory(factory), get_airflow_adapter()

The default implementation wraps the existing httpx-based AirflowClient to preserve current behavior. Orchestration code can be migrated to use get_airflow_adapter() when needed, with no API changes to callers.

## Kubernetes Adapter (Stub)

- Base class: BaseKubernetesAdapter
- Factory hook: set_kubernetes_adapter_factory(factory), get_kubernetes_adapter()

This is a stub to allow future integration patterns (e.g., preparing cluster resources for extended unit tests). No current code depends on it; it exists to provide a stable extension point.

## Backwards Compatibility

- No changes are needed to callers today. Existing functions and behaviors remain.
- Adapters can be introduced incrementally without modifying orchestration logic.
