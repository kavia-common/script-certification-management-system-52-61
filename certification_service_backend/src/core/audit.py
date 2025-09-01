from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from ..models.db_models import AuditLog


# PUBLIC_INTERFACE
async def create_audit_log(
    session: AsyncSession,
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    actor: Optional[str],
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist an audit log entry.

    Parameters:
    - session: AsyncSession to write the log.
    - action: Action/mutation performed, e.g., 'create', 'patch', 'webhook'.
    - resource_type: Domain type affected, e.g., 'certification_job', 'mapping', 'metadata', 'webhook'.
    - resource_id: Identifier of the target entity (run_id, id, etc.) if known.
    - actor: Who performed the action. Extracted from auth, headers or webhook payload.
    - details: Arbitrary JSON payload snapshot for traceability.
    """
    session.add(
        AuditLog(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            details=details or {},
        )
    )


# PUBLIC_INTERFACE
def extract_actor_from_headers(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_user: Optional[str] = Header(default=None, alias="X-User"),
    x_forwarded_user: Optional[str] = Header(default=None, alias="X-Forwarded-User"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Optional[str]:
    """Best-effort extraction of actor identity from common headers.

    Order of preference:
    1. X-User-Id
    2. X-User
    3. X-Forwarded-User
    4. Bearer <token> (stores 'bearer' string to indicate token usage without leaking secrets)

    Returns a string identifier or None.
    """
    if x_user_id:
        return x_user_id
    if x_user:
        return x_user
    if x_forwarded_user:
        return x_forwarded_user
    if authorization:
        # Do not persist sensitive token; only indicate bearer usage
        lower = authorization.lower().strip()
        if lower.startswith("bearer "):
            return "bearer"
        return authorization.split(" ", 1)[0]  # 'basic', 'api-key', etc.
    return None


# PUBLIC_INTERFACE
def build_request_context(request: Optional[Request]) -> Dict[str, Any]:
    """Capture non-sensitive request context for audit logs.

    Includes method, path, client, and selected headers to trace source.
    """
    if not request:
        return {}
    try:
        client_host = request.client.host if request.client else None
    except Exception:
        client_host = None

    headers_subset = {}
    # Only include safe, non-sensitive headers
    for h in ["x-user-id", "x-user", "x-forwarded-user", "x-request-id", "x-gitlab-token", "x-webhook-secret"]:
        if h in request.headers:
            headers_subset[h] = request.headers.get(h)

    return {
        "method": request.method,
        "path": request.url.path,
        "query": str(request.url.query),
        "client": client_host,
        "headers": headers_subset,
        "env": get_settings().environment,
    }
