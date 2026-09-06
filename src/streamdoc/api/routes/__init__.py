"""Router aggregation for all API routes."""
from __future__ import annotations

from fastapi import APIRouter

from streamdoc.api.routes import (
    agy,
    channels,
    cleanup,
    cli_tools,
    dashboard,
    fetch,
    jobs,
    notebooklm,
    notifications,
    presets,
    prompts,
    reports,
    scheduler,
    tools,
)
from streamdoc.api.routes import (
    settings as settings_routes,
)
from streamdoc.api.routes import (
    social as social_routes,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(presets.router)
api_router.include_router(fetch.router)
api_router.include_router(jobs.router)
api_router.include_router(scheduler.router)
api_router.include_router(cleanup.router)
api_router.include_router(notebooklm.router)
api_router.include_router(agy.router)
api_router.include_router(cli_tools.router)
api_router.include_router(settings_routes.router)
api_router.include_router(social_routes.router)
api_router.include_router(dashboard.router)
api_router.include_router(channels.router)
api_router.include_router(prompts.router)
api_router.include_router(reports.router)
api_router.include_router(tools.router)
api_router.include_router(notifications.router)
