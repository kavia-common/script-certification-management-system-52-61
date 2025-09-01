from __future__ import annotations

import abc
from typing import Any, Dict, Optional, Tuple

import httpx
from pydantic import BaseModel, Field

from .config import get_settings
from .logging_utils import get_logger

logger = get_logger(__name__)
from .logging_utils import get_logger

logger = get_logger(__name__)


class RepoInfo(BaseModel):
    """Resolved repository information."""
    provider: str = Field(..., description="Source provider, e.g., gitlab")
    project_id: str = Field(..., description="Project identifier at provider")
    branch: str = Field(..., description="Branch being certified")
    commit_sha: Optional[str] = Field(None, description="Resolved commit SHA for branch/ref")
    default_branch: Optional[str] = Field(None, description="Project default branch")
    web_url: Optional[str] = Field(None, description="Project web URL")
    description: Optional[str] = Field(None, description="Project description")
    namespace: Optional[str] = Field(None, description="Namespace/group path")
    visibility: Optional[str] = Field(None, description="Project visibility level")
    extra: Dict[str, Any] = Field(default_factory=dict, description="Provider-specific extra fields")


class BaseRepoAdapter(abc.ABC):
    """Abstract base class for repository adapters to support multiple providers."""

    @abc.abstractmethod
    async def resolve_commit(self, project_id: str, branch: str) -> Optional[str]:
        """Resolve commit SHA for a given branch/ref."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_project_metadata(self, project_id: str) -> Dict[str, Any]:
        """Fetch project-level metadata."""
        raise NotImplementedError

    # PUBLIC_INTERFACE
    async def get_repo_info(self, project_id: str, branch: str, commit_sha: Optional[str]) -> RepoInfo:
        """Return a RepoInfo object by combining project metadata and commit SHA resolution."""
        meta = await self.get_project_metadata(project_id)
        sha = commit_sha or await self.resolve_commit(project_id, branch)
        # Common fields from GitLab-like metadata
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

    @classmethod
    @abc.abstractmethod
    def provider_name(cls) -> str:
        """Return the adapter's provider name (e.g., 'gitlab')."""
        raise NotImplementedError


class GitLabAdapter(BaseRepoAdapter):
    """GitLab repository adapter using GitLab REST API."""

    def __init__(self, base_url: str, token: Optional[str], timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        headers = {"Accept": "application/json"}
        if token:
            headers["PRIVATE-TOKEN"] = token
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=self.timeout, follow_redirects=True)

    @classmethod
    def provider_name(cls) -> str:
        return "gitlab"

    async def _request(self, method: str, url: str, **kwargs) -> Tuple[int, Any]:
        res = await self._client.request(method, url, **kwargs)
        # Do not raise here; allow caller to interpret 404s etc.
        try:
            data = res.json()
        except Exception:
            data = None
        return res.status_code, data

    async def resolve_commit(self, project_id: str, branch: str) -> Optional[str]:
        """
        Resolve commit SHA for a ref using:
        - GET /projects/:id/repository/branches/:branch for branch info
        Fallback:
        - GET /projects/:id/repository/commits/:ref
        """
        # Branch info endpoint
        status, data = await self._request("GET", f"/api/v4/projects/{httpx.URL('').joinpath(str(project_id)).raw_path.decode()}/repository/branches/{httpx.utils.quote(branch, safe='')}")
        if status == 200 and isinstance(data, dict):
            commit = data.get("commit") or {}
            sha = commit.get("id") or commit.get("sha")
            if sha:
                return sha
        # Fallback to commits endpoint
        status2, data2 = await self._request("GET", f"/api/v4/projects/{httpx.URL('').joinpath(str(project_id)).raw_path.decode()}/repository/commits/{httpx.utils.quote(branch, safe='')}")
        if status2 == 200 and isinstance(data2, dict):
            return data2.get("id") or data2.get("sha")
        return None

    async def get_project_metadata(self, project_id: str) -> Dict[str, Any]:
        """
        Fetch project metadata:
        - GET /projects/:id
        """
        status, data = await self._request("GET", f"/api/v4/projects/{httpx.URL('').joinpath(str(project_id)).raw_path.decode()}")
        if status == 200 and isinstance(data, dict):
            return data
        return {}

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass


# PUBLIC_INTERFACE
def get_repo_adapter(provider: str) -> Optional[BaseRepoAdapter]:
    """Return a repository adapter based on provider name."""
    s = get_settings()
    provider_lower = (provider or "").lower()
    if provider_lower == "gitlab" and s.gitlab_base_url:
        return GitLabAdapter(base_url=str(s.gitlab_base_url), token=s.gitlab_token)
    # Extend here for future providers (e.g., GitHub, Bitbucket)
    return None
