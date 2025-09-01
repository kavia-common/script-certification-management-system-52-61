from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Request

from .config import get_settings

# Context variables to carry trace info across async boundaries
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
run_id_ctx: ContextVar[Optional[str]] = ContextVar("run_id", default=None)
job_id_ctx: ContextVar[Optional[str]] = ContextVar("job_id", default=None)
actor_ctx: ContextVar[Optional[str]] = ContextVar("actor", default=None)
component_ctx: ContextVar[str] = ContextVar("component", default="api")


class JsonFormatter(logging.Formatter):
    """JSON log formatter that enriches records with context vars and time."""

    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Inject context
        rid = request_id_ctx.get()
        if rid:
            base["request_id"] = rid
        rid2 = run_id_ctx.get()
        if rid2:
            base["run_id"] = rid2
        jid = job_id_ctx.get()
        if jid:
            base["job_id"] = jid
        actor = actor_ctx.get()
        if actor:
            base["actor"] = actor
        component = component_ctx.get()
        if component:
            base["component"] = component

        # Optional extras sent via logger.extra
        # record.__dict__ may contain arbitrary fields
        for key, val in record.__dict__.items():
            if key in (
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            ):
                continue
            if key in base:
                continue
            # Only include JSON-serializable extras
            try:
                json.dumps(val)
                base[key] = val
            except Exception:
                base[key] = str(val)

        # Exception info to structured field if present
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(base, ensure_ascii=False)


def _configure_root_logger() -> None:
    """Configure root logger with JSON formatter and level from settings."""
    settings = get_settings()
    level = logging.DEBUG if settings.debug else logging.INFO
    root = logging.getLogger()
    # Avoid duplicate handlers if reloaded
    if getattr(root, "_json_configured", False):
        return
    root.setLevel(level)
    # Remove existing handlers (e.g., uvicorn default) to standardize output
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root._json_configured = True  # type: ignore[attr-defined]

    # Tune noisy libraries
    logging.getLogger("httpx").setLevel(logging.INFO if settings.debug else logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)  # SQL logs separately controlled by settings.debug
    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# PUBLIC_INTERFACE
def init_logging(component: str = "api") -> None:
    """Initialize structured logging and set component context."""
    _configure_root_logger()
    component_ctx.set(component)


# PUBLIC_INTERFACE
def set_request_context_from_request(request: Optional[Request]) -> str:
    """Generate/propagate a request id and store into context var from FastAPI Request."""
    # Reuse incoming x-request-id if present, otherwise generate
    rid = None
    try:
        if request and "x-request-id" in request.headers:
            rid = request.headers.get("x-request-id")
    except Exception:
        rid = None
    if not rid:
        rid = uuid.uuid4().hex[:16]
    request_id_ctx.set(rid)
    return rid


# PUBLIC_INTERFACE
def set_run_context(run_id: Optional[str] = None, job_id: Optional[str] = None, actor: Optional[str] = None, component: Optional[str] = None) -> None:
    """Set context for run and actor; used by orchestrator/scheduler/background tasks."""
    if run_id:
        run_id_ctx.set(run_id)
    if job_id:
        job_id_ctx.set(job_id)
    if actor:
        actor_ctx.set(actor)
    if component:
        component_ctx.set(component)


# PUBLIC_INTERFACE
def clear_context() -> None:
    """Clear context vars; best-effort."""
    request_id_ctx.set(None)
    run_id_ctx.set(None)
    job_id_ctx.set(None)
    actor_ctx.set(None)


# PUBLIC_INTERFACE
def get_logger(name: str) -> logging.Logger:
    """Return a configured logger instance."""
    _configure_root_logger()
    return logging.getLogger(name)
