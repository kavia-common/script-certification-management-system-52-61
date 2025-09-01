from __future__ import annotations

import abc
from typing import Any, Dict, Optional


class BaseKubernetesAdapter(abc.ABC):
    """Abstract base for Kubernetes integration used during extended unit or other tests.

    This is a stub to allow future plug-ins to provide real implementations.
    """

    # PUBLIC_INTERFACE
    @abc.abstractmethod
    async def apply_manifest(self, manifest: Dict[str, Any], namespace: Optional[str] = None) -> None:
        """Apply a K8s manifest to a cluster."""
        raise NotImplementedError

    # PUBLIC_INTERFACE
    @abc.abstractmethod
    async def wait_for_job(self, name: str, namespace: str, timeout_seconds: int = 600) -> bool:
        """Wait for a Kubernetes Job to complete. Return True on success."""
        raise NotImplementedError

    # PUBLIC_INTERFACE
    @abc.abstractmethod
    async def delete_resource(self, kind: str, name: str, namespace: Optional[str] = None) -> None:
        """Delete a resource by kind/name/namespace."""
        raise NotImplementedError


# Factory hook to supply a Kubernetes adapter (None by default).
_K8S_ADAPTER_FACTORY = None


# PUBLIC_INTERFACE
def set_kubernetes_adapter_factory(factory) -> None:
    """Register a global factory for creating Kubernetes adapter instances."""
    global _K8S_ADAPTER_FACTORY
    _K8S_ADAPTER_FACTORY = factory


# PUBLIC_INTERFACE
def get_kubernetes_adapter() -> Optional[BaseKubernetesAdapter]:
    """Return a Kubernetes adapter instance if a factory was registered; else None."""
    if _K8S_ADAPTER_FACTORY:
        return _K8S_ADAPTER_FACTORY()
    return None
