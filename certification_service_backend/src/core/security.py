from __future__ import annotations

import hmac
import hashlib
from typing import Optional, Sequence

from fastapi import Header, HTTPException, status, Request

from .config import get_settings


# PUBLIC_INTERFACE
def get_bearer_token_auth_dependency():
    """Return a FastAPI dependency that enforces Bearer token authorization on protected routes.

    Behavior:
    - Reads AUTH_BEARER_TOKENS from environment (comma-separated). If unset:
      - In 'development' environment, allows requests (no-op) to ease local testing.
      - In non-development environments, denies all requests (401).
    - Validates 'Authorization: Bearer <token>'.
    - Supports multiple accepted tokens.
    """
    settings = get_settings()

    accepted_tokens_raw = (settings._get_env("AUTH_BEARER_TOKENS") or "").strip()
    # Normalize list of tokens
    accepted_tokens: Sequence[str] = (
        [t.strip() for t in accepted_tokens_raw.split(",") if t.strip()]
        if accepted_tokens_raw
        else []
    )

    async def _auth_dep(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> None:
        # Development convenience: if no tokens configured, allow only in development
        if not accepted_tokens:
            if settings.environment.lower() == "development":
                return
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Must present bearer header
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization scheme",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Constant-time compare against any accepted token
        for accepted in accepted_tokens:
            if hmac.compare_digest(token, accepted):
                return

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _auth_dep


# PUBLIC_INTERFACE
async def validate_hmac_signature(
    request: Request,
    x_signature: Optional[str] = Header(default=None, alias="X-Signature"),
    x_signature_algo: Optional[str] = Header(default="sha256", alias="X-Signature-Algo"),
) -> None:
    """Validate webhook HMAC signature for the raw request body using WEBHOOK_HMAC_SECRET.

    Headers:
    - X-Signature: hex-encoded HMAC signature.
    - X-Signature-Algo: hash algorithm (default: sha256). Supported: sha256, sha1.

    Behavior:
    - If WEBHOOK_HMAC_SECRET is not set:
        - In 'development', validation is skipped (allow).
        - In non-development environments, if header is present but secret not configured -> 401.
    - If secret is set:
        - Require X-Signature; compute HMAC over raw body; compare using constant-time compare.
        - On mismatch -> 401.

    Note:
    - This is independent of the simpler shared-secret headers already supported (X-Webhook-Secret / X-Gitlab-Token).
      You can combine them if desired.
    """
    settings = get_settings()
    secret = settings._get_env("WEBHOOK_HMAC_SECRET")

    if not secret:
        # Allow in development if no secret configured
        if settings.environment.lower() == "development":
            return
        # If no secret and no signature provided, accept for backward-compatibility on non-dev? To be strict, deny when header is provided or when configured as prod.
        # We deny in non-dev when no secret configured and signature is provided OR when strict mode expected.
        if x_signature:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized (signature provided but server secret not configured)")
        # If not provided, we accept for backward-compatibility with previous shared-secret validation.
        return

    # When secret is configured, signature header is required
    if not x_signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Signature")

    algo = (x_signature_algo or "sha256").lower()
    if algo not in ("sha256", "sha1"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported signature algorithm")

    # Read body (it can be awaited once; FastAPI/Starlette provide request.body())
    body = await request.body()
    key = secret.encode("utf-8")
    digestmod = hashlib.sha256 if algo == "sha256" else hashlib.sha1
    mac = hmac.new(key, body, digestmod=digestmod).hexdigest()

    # Constant-time compare
    if not hmac.compare_digest(mac, x_signature.strip()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
