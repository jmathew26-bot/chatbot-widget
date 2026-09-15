"""FastAPI web dashboard. Server-rendered (Jinja2 + plain HTML forms) on
purpose -- no JS build step, no client-side state to keep in sync with the
DB. Every action here calls the exact same agent/service functions as the
CLI (`network review`, `network send`, ...), so there's one source of
truth for business logic; this module is presentation + routing only.

Local-only by default (see cli.py `serve` command binds 127.0.0.1) --
there is no authentication layer, and actions here can send real email and
create real calendar events once those providers are configured.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from networking_agent.logging_utils import configure_logging
from networking_agent.web.routers import analytics, meetings, outreach, prospects, relationships, replies, settings_page, today

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Personal Networking Agent")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(today.router)
    app.include_router(prospects.router)
    app.include_router(outreach.router)
    app.include_router(replies.router)
    app.include_router(meetings.router)
    app.include_router(relationships.router)
    app.include_router(analytics.router)
    app.include_router(settings_page.router)
    return app


app = create_app()
