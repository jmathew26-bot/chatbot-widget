from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import select

from networking_agent.agents import analytics, crm, diagnostics, discovery, email_agent, followup, pipeline, response, scheduling, sending
from networking_agent.agents.context import AgentContext
from networking_agent.config import get_settings
from networking_agent.db.models import Outreach, Person, Relationship
from networking_agent.db.session import init_db, session_scope
from networking_agent.enums import OutreachStatus, RelationshipStatus, UTStatus
from networking_agent.logging_utils import configure_logging

app = typer.Typer(help="Personal Networking Agent -- discover, verify, research, score, and draft outreach to high-value professional contacts.")
console = Console()


def _person_summary_table(people: list[Person]) -> Table:
    table = Table(title="Prospects")
    for col in ["Score", "Name", "Company", "Title", "Location", "UT", "Category", "Status"]:
        table.add_column(col)
    for p in people:
        table.add_row(
            str(p.total_score),
            p.full_name,
            p.current_company.name if p.current_company else "UNKNOWN",
            p.current_title,
            p.location,
            p.ut_status,
            p.category,
            p.relationship.status if p.relationship else "-",
        )
    return table


@app.command("init-db")
def init_db_cmd() -> None:
    """Create tables directly (dev convenience). Prefer `alembic upgrade head`
    once you have a real, persistent database you care about migrating."""
    configure_logging()
    init_db()
    console.print("[green]Database initialized.[/green]")


@app.command()
def discover(
    category: str = typer.Option(..., help="tech-sales | cre"),
    location: str = typer.Option(None, help="e.g. Austin"),
    count: int = typer.Option(None, help="How many new prospects to find"),
) -> None:
    """Discover, verify, research, and score new prospects. Does not draft
    emails or send anything -- see `network review`."""
    configure_logging()
    with session_scope() as session:
        ctx = AgentContext.build(session)
        count = count or ctx.settings.limits.default_discover_count
        count = min(count, ctx.settings.limits.daily_discovery_limit)
        _run_discovery(ctx, category, location, count)


@app.command("live-test")
def live_test(
    category: str = typer.Option(..., help="tech-sales | cre"),
    location: str = typer.Option(None, help="e.g. Austin"),
    count: int = typer.Option(20, help="Hard-capped at 20 regardless of this value"),
) -> None:
    """Run the real pipeline (discover -> verify UT -> research -> score ->
    find/verify email) with hard safety ceilings for validating credentials:
    max 20 discovered, max 5 sends/day, approval always required. Forces
    LIVE_TEST_MODE on for this run regardless of the .env setting, so the
    5/day send cap applies even if you forgot to set it."""
    configure_logging()
    with session_scope() as session:
        ctx = AgentContext.build(session)
        ctx.settings.live_test_mode = True
        count = min(count, ctx.settings.live_test_max_discover)
        console.print(
            f"[bold]LIVE TEST MODE[/bold]: discovering up to {count} real prospects, "
            f"max {ctx.settings.live_test_max_sends_per_day} sends/day, approval required for every message."
        )
        _run_discovery(ctx, category, location, count)


def _run_discovery(ctx: AgentContext, category: str, location: str | None, count: int) -> None:
    people = discovery.discover(ctx, category, location, count)
    if not people:
        console.print(
            "[yellow]No new prospects found.[/yellow] If GOOGLE_CSE_API_KEY / GOOGLE_CSE_CX are not "
            "set in .env, discovery has no search provider and will always return zero results -- "
            "this is intentional (no hallucinated prospects). See .env.example."
        )
        return

    pipeline.enrich_discovered_people(ctx, people)
    console.print(_person_summary_table(people))
    console.print(f"[green]{len(people)} new prospect(s) discovered, verified, researched, scored, and email-checked.[/green]")


_get_primary_email = sending.get_primary_email


def _display_prospect(ctx: AgentContext, person: Person, outreach: Outreach, warnings: list[str]) -> None:
    company = person.current_company.name if person.current_company else "UNKNOWN"
    email_record = _get_primary_email(person)
    body_lines = [
        f"[bold]{person.full_name}[/bold] -- {person.current_title} at {company}",
        f"Location: {person.location}    Category: {person.category}",
        f"UT status: {person.ut_status}  ({person.ut_status_rationale or 'n/a'})",
        f"Score: {person.total_score}  "
        f"(UT {person.ut_score} / Career {person.career_relevance_score} / Company {person.company_quality_score} / "
        f"Seniority {person.seniority_score} / Geo {person.geography_score} / Interest {person.career_interest_score} / "
        f"Relationship {person.relationship_value_score})",
        "",
        f"[italic]{person.networking_thesis or 'No thesis generated.'}[/italic]",
        "",
        "Sources:",
    ]
    for s in person.sources[:5]:
        body_lines.append(f"  - {s.url}")
    body_lines += [
        "",
        f"Email on file: {email_record.email_address if email_record else '[red]UNKNOWN[/red]'} "
        f"({email_record.verification_status if email_record else 'n/a'})",
        "",
        f"Draft subject options: {outreach.subject_options}",
        f"Chosen subject: {outreach.subject}",
        "",
        outreach.body,
        "",
        f"Word count: {len(outreach.body.split())}",
    ]
    if warnings:
        body_lines.append(f"[red]Warnings: {'; '.join(warnings)}[/red]")

    console.print(Panel("\n".join(body_lines), title=f"Sequence {outreach.sequence_number}"))


def _interactive_review(ctx: AgentContext, items: list[tuple[Person, int]]) -> None:
    if not items:
        console.print("[yellow]Nothing to review.[/yellow]")
        return
    for person, sequence_number in items:
        existing_draft = next(
            (o for o in person.outreach if o.sequence_number == sequence_number and o.status == OutreachStatus.DRAFT.value),
            None,
        )
        outreach = existing_draft
        warnings: list[str] = []
        if outreach is None:
            outreach, warnings = email_agent.draft_email(ctx, person, sequence_number)

        _display_prospect(ctx, person, outreach, warnings)
        choice = typer.prompt("[A]pprove / [E]dit / [S]kip / [B]lock", default="S").strip().lower()

        if choice.startswith("a"):
            crm.approve_outreach(ctx, outreach)
            console.print("[green]Approved.[/green]")
        elif choice.startswith("e"):
            new_subject = typer.prompt("Subject", default=outreach.subject)
            new_body = typer.edit(outreach.body) or outreach.body
            crm.edit_outreach(ctx, outreach, new_subject, new_body)
            if typer.confirm("Approve this edited version now?", default=True):
                crm.approve_outreach(ctx, outreach)
                console.print("[green]Edited and approved.[/green]")
            else:
                console.print("[yellow]Edited, left unapproved.[/yellow]")
        elif choice.startswith("b"):
            reason = typer.prompt("Block reason", default="not a fit")
            crm.block_person(ctx, person, reason)
            console.print("[red]Blocked.[/red]")
        else:
            crm.skip_outreach(ctx, outreach)
            console.print("[yellow]Skipped.[/yellow]")
        ctx.session.commit()


@app.command()
def review(include_likely: bool = typer.Option(False, "--include-likely"), limit: int = 20) -> None:
    """Walk through READY_FOR_REVIEW prospects (VERIFIED UT status,
    score >= review threshold) one at a time: Approve / Edit / Skip / Block."""
    configure_logging()
    with session_scope() as session:
        ctx = AgentContext.build(session)

        if include_likely:
            likely_people = session.execute(
                select(Person).join(Relationship).where(
                    Relationship.status == RelationshipStatus.RESEARCHED.value,
                    Person.ut_status == UTStatus.LIKELY.value,
                    Person.excluded.is_(False),
                )
            ).scalars().all()
            for p in likely_people:
                crm.include_for_manual_review(ctx, p)
            session.flush()

        people = session.execute(
            select(Person).join(Relationship).where(
                Relationship.status == RelationshipStatus.READY_FOR_REVIEW.value
            ).order_by(Person.total_score.desc()).limit(limit)
        ).scalars().all()

        _interactive_review(ctx, [(p, 1) for p in people])


@app.command()
def send(limit: int = 50) -> None:
    """Send every APPROVED/EDITED-and-approved outreach via the configured
    EmailProvider. Never sends a DRAFT/SKIPPED/BLOCKED message."""
    configure_logging()
    with session_scope() as session:
        ctx = AgentContext.build(session)
        pending = session.execute(
            select(Outreach).where(Outreach.status.in_([OutreachStatus.APPROVED.value, OutreachStatus.EDITED.value]))
            .limit(limit)
        ).scalars().all()
        if not pending:
            console.print("[yellow]Nothing approved and ready to send.[/yellow]")
            return

        sent = 0
        for outreach in pending:
            outcome = sending.send_outreach(ctx, outreach)
            if outcome.sent:
                sent += 1
                console.print(f"[green]Sent to {outreach.person.full_name}.[/green]")
            else:
                console.print(f"[red]Skipping {outreach.person.full_name}: {outcome.reason}[/red]")
            session.commit()
        console.print(f"[bold]{sent}/{len(pending)} sent.[/bold]")


@app.command()
def followups() -> None:
    """Show follow-ups due today and walk through Approve/Edit/Skip/Block
    for each, same as `network review`."""
    configure_logging()
    with session_scope() as session:
        ctx = AgentContext.build(session)
        no_response = followup.mark_exhausted_no_response(session, ctx.settings)
        for p in no_response:
            console.print(f"[dim]{p.full_name}: marked NO_RESPONSE (cadence exhausted).[/dim]")

        due_people = followup.get_due_followups(session, ctx.settings)
        if not due_people:
            console.print("[yellow]No follow-ups due.[/yellow]")
            return
        items = [(p, p.relationship.attempts_count + 1) for p in due_people]
        _interactive_review(ctx, items)


@app.command()
def schedule(
    person_id: int = typer.Option(..., help="Person id to schedule with"),
    days_ahead: int = typer.Option(7, help="How many days out to look for open slots"),
    duration: int = typer.Option(None, help="Meeting duration in minutes"),
    meeting_type: str = typer.Option("zoom", help="coffee | lunch | office | phone | zoom"),
    confirm_start: str = typer.Option(None, help="ISO datetime to book directly, skipping proposal"),
) -> None:
    """Propose open meeting slots for a person, or book one directly with
    --confirm-start. Never double-books: checks both the calendar provider
    and this app's own meetings table."""
    configure_logging()
    with session_scope() as session:
        ctx = AgentContext.build(session)
        person = session.get(Person, person_id)
        if person is None:
            console.print(f"[red]No person with id {person_id}[/red]")
            raise typer.Exit(1)
        duration = duration or ctx.settings.meetings.default_duration_minutes

        if confirm_start:
            start = dt.datetime.fromisoformat(confirm_start)
            try:
                email_record = _get_primary_email(person)
                meeting = scheduling.schedule_meeting(
                    ctx, person, start, duration, meeting_type,
                    attendee_email=email_record.email_address if email_record else None,
                )
            except scheduling.SchedulingConflictError as e:
                console.print(f"[red]{e}[/red]")
                raise typer.Exit(1)
            console.print(f"[green]Scheduled {meeting.meeting_type} with {person.full_name} at {start.isoformat()}.[/green]")
            return

        window_start = dt.datetime.now(dt.timezone.utc)
        window_end = window_start + dt.timedelta(days=days_ahead)
        slots = scheduling.propose_slots(ctx, window_start, window_end, duration)
        if not slots:
            console.print("[yellow]No open slots found in that window.[/yellow]")
            return
        for slot in slots:
            console.print(f"  {slot.start.isoformat()} - {slot.end.isoformat()}")
        console.print("Book one with: network schedule --person-id ... --confirm-start '<ISO datetime>'")


@app.command()
def inbox(
    person_id: int = typer.Option(None, help="Manually classify a reply for this person id"),
    reply_text: str = typer.Option(None, help="Raw reply text (used with --person-id)"),
) -> None:
    """Check for replies and apply them (stop follow-ups, update relationship
    state). With Gmail configured, scans the thread of every CONTACTED/
    FOLLOW_UP person's most recent sent email for new messages and matches
    them automatically. Without Gmail, use --person-id/--reply-text to
    manually ingest a reply you received outside the system."""
    configure_logging()
    with session_scope() as session:
        ctx = AgentContext.build(session)

        if person_id is not None and reply_text:
            person = session.get(Person, person_id)
            if person is None:
                console.print(f"[red]No person with id {person_id}[/red]")
                raise typer.Exit(1)
            result = response.apply_reply(ctx, person, reply_text)
            console.print(f"[green]Classified as {result.classification.value}[/green] ({result.rationale})")
            return

        found = response.check_all_replies(ctx)
        if not found:
            console.print(
                "[yellow]No new replies found.[/yellow] (Requires Gmail credentials to scan threads -- "
                "otherwise use `network inbox --person-id X --reply-text '...'` to manually record one.)"
            )
            return
        for person, result in found:
            console.print(f"[green]{person.full_name}: classified as {result.classification.value}[/green] ({result.rationale})")


@app.command()
def dashboard() -> None:
    """Morning brief: discovery/review/follow-up/reply/meeting counts."""
    configure_logging()
    with session_scope() as session:
        brief = analytics.morning_brief(session)
        table = Table(title="NETWORKING BRIEF")
        table.add_column("Metric")
        table.add_column("Count")
        labels = {
            "new_prospects_discovered": "New prospects discovered",
            "high_priority": "High priority (score >= 80)",
            "emails_awaiting_approval": "Emails awaiting approval",
            "followups_due": "Follow-ups due",
            "replies_received_today": "Replies received today",
            "meetings_scheduled_this_week": "Meetings scheduled this week",
        }
        for key, label in labels.items():
            table.add_row(label, str(brief[key]))
        console.print(table)

        top = session.execute(
            select(Person).where(Person.excluded.is_(False)).order_by(Person.total_score.desc()).limit(5)
        ).scalars().all()
        if top:
            console.print(_person_summary_table(top))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address. Keep this local -- there is no auth layer."),
    port: int = typer.Option(8000),
    reload: bool = typer.Option(False, help="Auto-reload on code changes (dev only)."),
) -> None:
    """Run the web dashboard (Today/Prospects/Outreach/Replies/Meetings/
    Relationships/Analytics/Settings). Binds to localhost by default: the
    dashboard can approve outreach and trigger real sends/calendar events
    once those providers are configured, and has no login of its own."""
    configure_logging()
    import uvicorn

    if host not in ("127.0.0.1", "localhost"):
        console.print(
            f"[yellow]Warning: binding to {host} exposes this dashboard (and its send/schedule actions) "
            f"to anything that can reach this host. There is no authentication.[/yellow]"
        )
    console.print(f"[green]Serving dashboard at http://{host}:{port}[/green]")
    uvicorn.run("networking_agent.web.app:app", host=host, port=port, reload=reload)


_STATUS_STYLE = {"ok": "green", "warning": "yellow", "not_configured": "yellow", "error": "red"}


@app.command()
def doctor() -> None:
    """Diagnose configuration: database, LLM/search/email-discovery
    providers, Gmail/Calendar OAuth status, missing env vars, send mode,
    and live-test mode. Never prints secret values."""
    settings = get_settings()
    results = diagnostics.run_diagnostics(settings)
    table = Table(title="network doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    any_error = False
    for r in results:
        style = _STATUS_STYLE.get(r.status, "white")
        table.add_row(r.name, f"[{style}]{r.status}[/{style}]", r.detail)
        any_error = any_error or r.status == "error"
    console.print(table)
    if any_error:
        raise typer.Exit(1)


@app.command("gmail-test")
def gmail_test() -> None:
    """Authenticate through the real GmailEmailProvider (opens a browser
    the first time; reuses/refreshes the saved token after that) and
    confirm access by fetching the connected account's own profile.
    Never sends anything."""
    settings = get_settings()
    if not settings.gmail_credentials_json or not Path(settings.gmail_credentials_json).exists():
        console.print(
            "[red]No Gmail OAuth client credentials configured (GMAIL_CREDENTIALS_JSON). See README.[/red]"
        )
        raise typer.Exit(1)
    from networking_agent.adapters.email_provider import GmailEmailProvider

    try:
        provider = GmailEmailProvider(
            settings.gmail_credentials_json, settings.gmail_token_json, settings.gmail_sender_email
        )
        email_address = provider.whoami()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Gmail authentication/access failed: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Gmail OK[/green] -- authenticated as {email_address}")


@app.command("calendar-test")
def calendar_test() -> None:
    """Authenticate through the real GoogleCalendarProvider (opens a
    browser the first time) and confirm access by reading the primary
    calendar's info and upcoming busy windows. Never creates anything."""
    settings = get_settings()
    if not settings.google_calendar_credentials_json or not Path(settings.google_calendar_credentials_json).exists():
        console.print(
            "[red]No Google Calendar OAuth client credentials configured "
            "(GOOGLE_CALENDAR_CREDENTIALS_JSON). See README.[/red]"
        )
        raise typer.Exit(1)
    from networking_agent.adapters.calendar_provider import GoogleCalendarProvider

    try:
        provider = GoogleCalendarProvider(
            settings.google_calendar_credentials_json, settings.google_calendar_token_json,
            settings.google_calendar_id,
        )
        info = provider.get_calendar_info()
        now = dt.datetime.now(dt.timezone.utc)
        busy = provider.list_busy(now, now + dt.timedelta(days=7))
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Calendar authentication/access failed: {e}[/red]")
        raise typer.Exit(1)

    console.print(
        f"[green]Calendar OK[/green] -- {info.get('summary', settings.google_calendar_id)} "
        f"(timezone {info.get('timeZone', '?')})"
    )
    if busy:
        console.print("Upcoming busy windows (next 7 days, up to 5 shown):")
        for slot in busy[:5]:
            console.print(f"  {slot.start.isoformat()} - {slot.end.isoformat()}")
    else:
        console.print("No busy windows found in the next 7 days.")


@app.command("gmail-test-send")
def gmail_test_send(to: str = typer.Option(..., "--to", help="Recipient for the test email")) -> None:
    """Sends ONE clearly-labeled test email through the real
    GmailEmailProvider, to verify a message/thread ID comes back
    correctly. Requires explicit confirmation -- never runs unattended."""
    settings = get_settings()
    console.print(
        f"[yellow]This will send a REAL email to {to} through your connected Gmail account "
        f"({settings.gmail_sender_email or 'the authenticated account'}).[/yellow]"
    )
    if not typer.confirm("Proceed?", default=False):
        console.print("Cancelled -- nothing sent.")
        raise typer.Exit(0)

    from networking_agent.adapters.base import EmailMessage
    from networking_agent.adapters.email_provider import GmailEmailProvider

    provider = GmailEmailProvider(
        settings.gmail_credentials_json, settings.gmail_token_json, settings.gmail_sender_email
    )
    message = EmailMessage(
        to_address=to,
        subject="[TEST] Networking Agent connectivity check",
        body=(
            "This is a one-time connectivity test sent by the Personal Networking Agent's "
            "`network gmail-test-send` command. Safe to ignore or delete."
        ),
    )
    result = provider.send(message, idempotency_key=f"gmail-test-send-{uuid.uuid4()}")
    if result.success:
        console.print(f"[green]Sent.[/green] message_id={result.provider_message_id} thread_id={result.thread_id}")
        if not result.provider_message_id or not result.thread_id:
            console.print("[yellow]Warning: Gmail did not return both a message_id and thread_id.[/yellow]")
    else:
        console.print(f"[red]Send failed: {result.error}[/red]")
        raise typer.Exit(1)


@app.command("calendar-test-create")
def calendar_test_create(
    minutes_from_now: int = typer.Option(60, help="When to schedule the test event, minutes from now"),
    duration: int = typer.Option(15, help="Test event duration in minutes"),
) -> None:
    """Creates ONE clearly-labeled temporary test event through the real
    GoogleCalendarProvider, to verify an event ID comes back correctly.
    Requires explicit confirmation, and offers to delete it again
    immediately afterward."""
    settings = get_settings()
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes_from_now)
    end = start + dt.timedelta(minutes=duration)
    console.print(
        f"[yellow]This will create a REAL event '[TEST] Networking Agent connectivity check' "
        f"on calendar '{settings.google_calendar_id}' at {start.isoformat()}.[/yellow]"
    )
    if not typer.confirm("Proceed?", default=False):
        console.print("Cancelled -- nothing created.")
        raise typer.Exit(0)

    from networking_agent.adapters.calendar_provider import GoogleCalendarProvider

    provider = GoogleCalendarProvider(
        settings.google_calendar_credentials_json, settings.google_calendar_token_json, settings.google_calendar_id
    )
    event_id = provider.create_event(
        title="[TEST] Networking Agent connectivity check",
        start=start, end=end, attendee_email=None,
        description="Created by `network calendar-test-create`. Safe to delete.",
    )
    console.print(f"[green]Created.[/green] event_id={event_id}")
    if typer.confirm("Delete this test event now?", default=True):
        provider.delete_event(event_id)
        console.print("[green]Deleted.[/green]")
    else:
        console.print(f"Leaving it in place -- delete manually later if needed (event_id={event_id}).")


if __name__ == "__main__":
    app()
