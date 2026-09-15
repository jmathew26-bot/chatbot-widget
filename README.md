# Personal Networking Agent

An executive-assistant-style system that discovers, verifies, researches,
scores, and drafts highly personalized outreach to high-value professional
contacts -- specifically UT Austin alumni in enterprise technology sales and
commercial real estate. It optimizes for relationship quality and meetings
booked, not send volume, and every email requires explicit human approval
before it goes out.

See `ARCHITECTURE.md` for the full design, directory layout, and
implementation checklist. This file is the quickstart.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .            # installs the `network` CLI command

cp .env.example .env                     # fill in whatever API keys you have (optional)
cp config/config.example.yaml config/config.yaml   # edit targeting rules, tone, cadence
$EDITOR USER_PROFILE.md                  # fill this out -- the Email Agent reads it

alembic upgrade head        # create the SQLite schema at data/networking.db
```

## Daily commands

```bash
network discover --category tech-sales --location Austin --count 20
network discover --category cre --location Texas --count 20

network review                  # walk VERIFIED, above-threshold prospects: [A]pprove [E]dit [S]kip [B]lock
network review --include-likely # also pull in LIKELY UT-status prospects for manual review

network send                    # sends everything APPROVED/EDITED, nothing else, ever

network followups               # shows + processes follow-ups due today (same A/E/S/B flow)
network inbox --person-id 12 --reply-text "..."   # manually classify a reply
network schedule --person-id 12                    # propose open meeting slots
network dashboard                # morning brief
```

## What works out of the box (no API keys)

- Full pipeline wiring: discovery -> UT verification -> research -> scoring
  -> networking thesis -> email draft -> approval -> send -> follow-up
  cadence -> reply classification -> meeting scheduling -> CRM state
  machine -> analytics.
- Deterministic, rule-based scoring (`services/scoring_rules.py`) -- no LLM
  required, fully unit tested.
- Deterministic fallback research summaries, networking theses, and email
  drafts (fact-only, never hallucinated) when no LLM is configured.
- Duplicate prevention, approval-gated sending, follow-up cadence and
  cancellation-on-reply, and calendar-collision checks all work against the
  local SQLite database with zero external services.
- `ConsoleEmailProvider` (writes approved emails to `data/outbox/` instead of
  sending) and `NullCalendarProvider` (in-app collision detection only) are
  the defaults, so nothing goes out over the network until you deliberately
  wire up real credentials.

## What needs credentials

| Capability | Provider | Env vars |
|---|---|---|
| Real web search (discovery) | Google Programmable Search Engine | `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX` |
| Fluent research/email/reply-classification prose | Anthropic | `ANTHROPIC_API_KEY` |
| Work email discovery | Hunter.io (pluggable: Apollo, PDL, RocketReach) | `HUNTER_API_KEY` |
| Sending real email | Gmail API (OAuth) | `GMAIL_CREDENTIALS_JSON`, `GMAIL_TOKEN_JSON` |
| Real calendar availability/booking | Google Calendar (OAuth) | `GOOGLE_CALENDAR_CREDENTIALS_JSON`, `GOOGLE_CALENDAR_TOKEN_JSON` |

Without the search provider configured, `network discover` always returns
zero results -- by design, so the system never fabricates prospects out of
synthetic data.

## Tests

```bash
pytest
```

Covers: duplicate prevention, UT Austin vs. other-UT-system verification,
deterministic scoring, schema validation, approval-gated send (never sends a
DRAFT/SKIPPED/BLOCKED message), follow-up cancellation on any reply
(positive or negative), opt-out / do-not-contact handling, and
calendar-collision detection.
