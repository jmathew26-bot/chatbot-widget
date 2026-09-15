from __future__ import annotations

import datetime as dt

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import select

from networking_agent.agents import analytics, crm, discovery, email_agent, followup, research, response, scheduling, scoring
from networking_agent.agents import verification as verification_agent
from networking_agent.agents.context import AgentContext
from networking_agent.config import get_settings
from networking_agent.db.models import EmailRecord, Outreach, Person, Relationship
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

        people = discovery.discover(ctx, category, location, count)
        if not people:
            console.print(
                "[yellow]No new prospects found.[/yellow] If GOOGLE_CSE_API_KEY / GOOGLE_CSE_CX are not "
                "set in .env, discovery has no search provider and will always return zero results -- "
                "this is intentional (no hallucinated prospects). See .env.example."
            )
            return

        for person in people:
            verification_agent.verify_ut_status(ctx, person)
            research.research_person(ctx, person)
            scoring.score_person(ctx, person)
            crm.promote_after_scoring(ctx, person)
        session.flush()
        console.print(_person_summary_table(people))
        console.print(f"[green]{len(people)} new prospect(s) discovered and scored.[/green]")


def _get_primary_email(person: Person) -> EmailRecord | None:
    for e in person.emails:
        if e.is_primary:
            return e
    return person.emails[0] if person.emails else None


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

        from networking_agent.adapters.base import EmailMessage

        sent = 0
        for outreach in pending:
            person = outreach.person
            crm.assert_approved_for_sending(outreach)
            email_record = _get_primary_email(person)
            if email_record is None:
                console.print(f"[red]Skipping {person.full_name}: no email on file.[/red]")
                continue
            if email_record.verification_status in ("BOUNCED", "DO_NOT_CONTACT"):
                console.print(f"[red]Skipping {person.full_name}: email is {email_record.verification_status}.[/red]")
                continue

            message = EmailMessage(to_address=email_record.email_address, subject=outreach.subject, body=outreach.body)
            result = ctx.email.send(message, idempotency_key=outreach.idempotency_key)
            now = dt.datetime.now(dt.timezone.utc)
            if result.success:
                outreach.status = OutreachStatus.SENT.value
                outreach.sent_at = now
                outreach.provider_message_id = result.provider_message_id
                followup.register_sent(ctx.settings, person.relationship, outreach.sequence_number, now)
                from networking_agent.db.models import Activity
                from networking_agent.enums import ActivityType
                session.add(Activity(person_id=person.id, activity_type=ActivityType.EMAIL_SENT.value, payload={"outreach_id": outreach.id}))
                sent += 1
                console.print(f"[green]Sent to {person.full_name}.[/green]")
            else:
                outreach.status = OutreachStatus.FAILED.value
                console.print(f"[red]Failed to send to {person.full_name}: {result.error}[/red]")
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
    """Show/process replies. Without a configured EmailProvider (Gmail),
    there is no live inbox to poll -- use --person-id/--reply-text to
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

        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
        raw_replies = ctx.email.fetch_replies(since)
        if not raw_replies:
            console.print(
                "[yellow]No replies fetched.[/yellow] (ConsoleEmailProvider never has replies -- configure "
                "Gmail credentials, or use `network inbox --person-id X --reply-text '...'` to manually record one.)"
            )
            return
        console.print(f"[bold]{len(raw_replies)} raw message(s) fetched -- manual matching required.[/bold]")
        for r in raw_replies:
            console.print(r)


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


if __name__ == "__main__":
    app()
