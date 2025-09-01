from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import httpx

from .logging_utils import get_logger
from .adapters.repos import BaseRepoAdapter, register_repo_adapter, get_repo_adapter_factory

logger = get_logger(__name__)


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
        try:
            data = res.json()
        except Exception:
            data = None
        return res.status_code, data

    async def resolve_commit(self, project_id: str, branch: str) -> Optional[str]:
        # Attempt branch lookup
        status, data = await self._request(
            "GET",
            f"/api/v4/projects/{httpx.URL('').joinpath(str(project_id)).raw_path.decode()}/repository/branches/{httpx.utils.quote(branch, safe='')}",
        )
        if status == 200 and isinstance(data, dict):
            commit = data.get("commit") or {}
            sha = commit.get("id") or commit.get("sha")
            if sha:
                return sha
        # Fallback to commits by ref
        status2, data2 = await self._request(
            "GET",
            f"/api/v4/projects/{httpx.URL('').joinpath(str(project_id)).raw_path.decode()}/repository/commits/{httpx.utils.quote(branch, safe='')}",
        )
        if status2 == 200 and isinstance(data2, dict):
            return data2.get("id") or data2.get("sha")
        return None

    async def get_project_metadata(self, project_id: str) -> Dict[str, Any]:
        status, data = await self._request("GET", f"/api/v4/projects/{httpx.URL('').joinpath(str(project_id)).raw_path.decode()}")
        if status == 200 and isinstance(data, dict):
            return data
        return {}

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass


# Register GitLab adapter factory on module import
def _register_defaults() -> None:
    from .config import get_settings as _get_settings

    def _factory() -> BaseRepoAdapter:
        s = _get_settings()
        if not s.gitlab_base_url:
            raise RuntimeError("GITLAB_BASE_URL not configured")
        return GitLabAdapter(base_url=str(s.gitlab_base_url), token=s.gitlab_token)

    register_repo_adapter("gitlab", _factory)


_register_defaults()


# PUBLIC_INTERFACE
def get_repo_adapter(provider: str) -> Optional[BaseRepoAdapter]:
    """Return a repository adapter instance for the given provider if registered."""
    factory = get_repo_adapter_factory(provider)
    if not factory:
        return None
    try:
        return factory()
    except Exception:
        # Fail soft and let callers proceed without enrichment
        logger.debug("Repo adapter factory failed for provider %s", provider, exc_info=True)
        return None
