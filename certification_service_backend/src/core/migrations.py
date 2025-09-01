from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from .db import get_engine
from ..models.db_models import Base


# PUBLIC_INTERFACE
async def init_models(engine: AsyncEngine | None = None) -> None:
    """Create all tables if they do not exist (dev bootstrap)."""
    eng = engine or get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
