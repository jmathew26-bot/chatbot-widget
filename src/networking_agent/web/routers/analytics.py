from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from networking_agent.agents import analytics
from networking_agent.web.deps import get_db
from networking_agent.web.templating import templates

router = APIRouter()


@router.get("/analytics")
def show_analytics(request: Request, session: Session = Depends(get_db)):
    breakdowns = {
        "By category": analytics.response_rate_by_category(session),
        "By title": analytics.response_rate_by_title(session),
        "By industry": analytics.response_rate_by_industry(session),
        "By geography": analytics.response_rate_by_geography(session),
        "By email template": analytics.response_rate_by_template(session),
        "By UT grad period": analytics.response_rate_by_ut_grad_period(session),
    }
    companies = analytics.company_leaderboard(session)
    return templates.TemplateResponse(
        request, "analytics.html", {"breakdowns": breakdowns, "companies": companies, "active": "analytics"}
    )
