from __future__ import annotations

import abc
from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel, Field


class RepoInfo(BaseModel):
    """Resolved repository information from a provider."""
    provider: str = Field(..., description="Provider name (e.g., gitlab)")
    project_id: str = Field(..., description="Project identifier at the provider")
    branch: str = Field(..., description="Branch or ref")
    commit_sha: Optional[str] = Field(None, description="Resolved commit SHA for branch/ref")
    default_branch: Optional[str] = Field(None, description="Project default branch")
    web_url: Optional[str] = Field(None, description="Project web URL")
    description: Optional[str] = Field(None, description="Project description")
    namespace: Optional[str] = Field(None, description="Namespace/group path")
    visibility: Optional[str] = Field(None, description="Project visibility")
    extra: Dict[str, Any] = Field(default_factory=dict, description="Provider-specific fields")


class BaseRepoAdapter(abc.ABC):
    """Abstract base class for repository provider adapters."""

    @classmethod
    @abc.abstractmethod
    def provider_name(cls) -> str:
        """Return canonical provider name (e.g., 'gitlab')."""
        raise NotImplementedError

    @abc.abstractmethod
    async def resolve_commit(self, project_id: str, branch: str) -> Optional[str]:
        """Resolve a commit SHA for a branch/ref."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_project_metadata(self, project_id: str) -> Dict[str, Any]:
        """Fetch provider-specific project metadata."""
        raise NotImplementedError

    # PUBLIC_INTERFACE
    async def get_repo_info(self, project_id: str, branch: str, commit_sha: Optional[str]) -> RepoInfo:
        """Compose RepoInfo by combining project metadata and commit SHA resolution."""
        meta = await self.get_project_metadata(project_id)
        sha = commit_sha or await self.resolve_commit(project_id, branch)
        return RepoInfo(
            provider=self.provider_name(),
            project_id=project_id,
            branch=branch,
            commit_sha=sha,
            default_branch=meta.get("default_branch"),
            web_url=meta.get("web_url") or meta.get("http_url_to_repo"),
            description=meta.get("description"),
            namespace=(meta.get("namespace") or {}).get("full_path") if isinstance(meta.get("namespace"), dict) else meta.get("namespace"),
            visibility=(meta.get("visibility") or meta.get("visibility_level")),
            extra=meta,
        )


# Simple registry for repo adapters to allow plug-in registration
_REPO_ADAPTER_REGISTRY: Dict[str, Callable[[], BaseRepoAdapter]] = {}


# PUBLIC_INTERFACE
def register_repo_adapter(provider: str, factory: Callable[[], BaseRepoAdapter]) -> None:
    """Register a provider adapter factory for get_repo_adapter_factory()."""
    _REPO_ADAPTER_REGISTRY[provider.lower()] = factory


# PUBLIC_INTERFACE
def get_repo_adapter_factory(provider: str) -> Optional[Callable[[], BaseRepoAdapter]]:
    """Return a factory callable for a given provider if registered."""
    return _REPO_ADAPTER_REGISTRY.get((provider or "").lower())
