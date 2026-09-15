from __future__ import annotations

from fastapi import APIRouter, Request

from networking_agent.config import get_settings
from networking_agent.web.templating import templates

router = APIRouter()


@router.get("/settings")
def show_settings(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings": settings,
            "targets": settings.targets,
            "user_profile": settings.user_profile_text(),
            "active": "settings",
        },
    )
