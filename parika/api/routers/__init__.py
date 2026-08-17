"""
PARIKA API - Routers

One `APIRouter` per domain, composed into a single `/api/v1` router
by `build_v1_router()`. `parika/server/app.py` mounts that single
router on the FastAPI app -- no unversioned route is ever exposed.
See `docs/guides/Running.md` section 12 for the Server Platform this
package implements.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..ws import chat as ws_chat
from ..ws import media as ws_media
from . import (
    capabilities,
    chat,
    config,
    expense,
    health,
    media,
    modules,
    providers,
    status,
    tools,
    voice,
    weather,
)

API_V1_PREFIX = "/api/v1"


def build_v1_router() -> APIRouter:
    """
    Compose every domain router under one `/api/v1`-prefixed
    `APIRouter`.

    `health`/`live`/`ready` are still mounted under `/api/v1` for
    consistency with every other endpoint (`/api/v1/health`, etc. --
    see `docs/guides/Running.md` section 12.4), but never require
    authentication (see `health.py`).
    """

    v1 = APIRouter(prefix=API_V1_PREFIX)

    v1.include_router(health.router)
    v1.include_router(status.router)
    v1.include_router(tools.router)
    v1.include_router(modules.router)
    v1.include_router(capabilities.router)
    v1.include_router(providers.router)
    v1.include_router(config.router)
    v1.include_router(expense.router)
    v1.include_router(chat.router)
    v1.include_router(ws_chat.router)
    v1.include_router(voice.router)
    v1.include_router(media.router)
    v1.include_router(ws_media.router)
    v1.include_router(weather.router)

    return v1


__all__ = ["API_V1_PREFIX", "build_v1_router"]
