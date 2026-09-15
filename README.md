# Personal Networking Agent

An executive-assistant-style system that discovers, verifies, researches,
scores, and drafts highly personalized outreach to high-value professional
contacts -- specifically UT Austin alumni in enterprise technology sales and
commercial real estate. It optimizes for relationship quality and meetings
booked, not send volume, and every email requires explicit human approval
before it goes out.

See `ARCHITECTURE.md` for the full design, directory layout, and
implementation checklist. This file is the setup + operating guide.

## Setup, from a clean machine

Follow these in order. Every step after step 3 is optional -- the pipeline
runs end to end without any of them, just with reduced capability (see
"What each credential buys you" below). Run `network doctor` at any point
to see exactly what's configured.

**1. Clone the repo and enter it**

```bash
git clone <this-repo-url>
cd chatbot-widget
```

**2. Create a virtual environment and install dependencies**

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                   # installs the `network` CLI command
```

**3. Configure `.env`**

```bash
cp .env.example .env
```

Leave everything blank for now if you don't have credentials yet -- the app
runs in a safe, fully offline mode (search returns 0 results, LLM calls fall
back to deterministic templates, email writes to `data/outbox/` instead of
sending, calendar has no external visibility). Fill in keys as you get them;
`network doctor` (step 10) tells you what's still missing.

**4. Configure `USER_PROFILE.md`**

```bash
$EDITOR USER_PROFILE.md
```

This is read by the Email and Research agents to decide why a prospect might
reasonably want to meet you -- fill in who you are, what you do, your goals,
interests, and communication style. Also review `config/config.example.yaml`
and copy it:

```bash
cp config/config.example.yaml config/config.yaml
```

`config.yaml` holds the operational settings: target roles/companies/
locations, scoring weights, daily discovery/email limits, follow-up cadence,
meeting duration/types, and email tone/word limits/banned phrases. All of
these are actually read by discovery, scoring, and email drafting -- not
decorative.

**5. Create the database**

```bash
alembic upgrade head        # creates the SQLite schema at data/networking.db
```

**6. Connect Gmail (optional, for real sending + reply detection)**

1. In [Google Cloud Console](https://console.cloud.google.com/), create (or
   pick) a project, enable the **Gmail API**, and create an OAuth Client ID
   of type "Desktop app". Download the JSON.
2. Save it somewhere outside version control, e.g. `secrets/gmail_credentials.json`.
3. In `.env`, set:
   ```
   GMAIL_CREDENTIALS_JSON=./secrets/gmail_credentials.json
   GMAIL_TOKEN_JSON=./secrets/gmail_token.json
   GMAIL_SENDER_EMAIL=you@yourdomain.com
   ```
4. The first time the app needs to send (`network send`, or the dashboard's
   Outreach page), it opens a browser for you to grant `gmail.send` +
   `gmail.readonly` consent, then writes `gmail_token.json` so you don't have
   to repeat this. Do this once, deliberately, in a controlled test account
   first -- see the LIVE_TEST_MODE section below.

**7. Connect Google Calendar (optional, for real scheduling)**

Same Cloud Console project works. Enable the **Google Calendar API**, and
either reuse the same OAuth client or make a new one. In `.env`:

```
GOOGLE_CALENDAR_CREDENTIALS_JSON=./secrets/gmail_credentials.json
GOOGLE_CALENDAR_TOKEN_JSON=./secrets/calendar_token.json
GOOGLE_CALENDAR_ID=primary
```

**8. Configure a search provider (optional, for real discovery)**

Google Programmable Search Engine is the simplest to set up:
1. Create one at https://programmablesearchengine.google.com/ (search the
   whole web, not a specific site).
2. Get an API key from Cloud Console (enable "Custom Search API").
3. In `.env`:
   ```
   GOOGLE_CSE_API_KEY=...
   GOOGLE_CSE_CX=...
   ```

**9. Configure an email-discovery provider (optional, for finding work emails)**

Hunter.io is the simplest to set up (a free tier exists):
```
HUNTER_API_KEY=...
```
Also worth adding an `ANTHROPIC_API_KEY` here if you have one -- it upgrades
research summaries, the networking thesis, and email drafts from
deterministic fact-only templates to fluent, personalized prose (the
underlying facts and safety rules are identical either way).

**10. Check everything**

```bash
network doctor
```

Reports, without ever printing a secret value: database OK, whether each
provider (LLM/search/email-discovery/Gmail/Calendar) is configured, OAuth
authorization status, current send mode (dry-run vs. live), and whether
LIVE_TEST_MODE is on.

**11. Run a capped live test**

```bash
export LIVE_TEST_MODE=true   # or set it in .env
network live-test --category tech-sales --location Austin --count 20
network live-test --category cre --location Austin --count 20
```

This runs the real pipeline (discover -> verify UT Austin -> research ->
score -> find/verify email) with hard ceilings: at most 20 people discovered
per run, at most 5 emails sent per day (regardless of `config.yaml`'s
`daily_email_limit`), and -- as always -- nothing is ever sent without you
explicitly approving it first. Use this to validate real credentials before
trusting the full-volume pipeline.

**12. Run the dashboard**

```bash
network serve
```

Open http://127.0.0.1:8000 and review what `live-test` found under
Prospects/Outreach. Approve, edit, skip, or block each draft; only approved
messages can ever be sent.

## Daily commands

```bash
network doctor                  # configuration/credential health check
network discover --category tech-sales --location Austin --count 20
network discover --category cre --location Texas --count 20
network live-test --category tech-sales --location Austin  # capped, safer version of the above

network review                  # walk VERIFIED, above-threshold prospects: [A]pprove [E]dit [S]kip [B]lock
network review --include-likely # also pull in LIKELY UT-status prospects for manual review

network send                    # sends everything APPROVED/EDITED, nothing else, ever

network followups               # shows + processes follow-ups due today (same A/E/S/B flow)
network inbox                   # scans Gmail threads for new replies and applies them (stops follow-ups, updates state)
network inbox --person-id 12 --reply-text "..."   # manually classify a reply if Gmail isn't connected
network schedule --person-id 12                    # propose open meeting slots
network dashboard                # morning brief

network serve                    # web dashboard at http://127.0.0.1:8000
```

## Web dashboard

`network serve` starts a FastAPI + server-rendered-HTML dashboard (no JS
build step) with the same eight sections as the CLI, backed by the exact
same agent/service functions -- there's one source of truth for business
logic:

**Today · Prospects · Outreach · Replies · Meetings · Relationships ·
Analytics · Settings**

It binds to `127.0.0.1` by default. There is no login -- it's a local tool,
and pages can trigger real sends/calendar events once those providers are
configured, so don't bind it to a public interface without adding auth in
front of it.

## What works out of the box (no API keys)

- Full pipeline wiring: discovery -> UT verification -> research -> scoring
  -> networking thesis -> find/verify email -> email draft -> approval ->
  send -> follow-up cadence -> reply detection -> meeting scheduling -> CRM
  state machine -> analytics.
- Deterministic, rule-based scoring (`services/scoring_rules.py`) -- no LLM
  required, fully unit tested.
- Deterministic fallback research summaries, networking theses, and email
  drafts (fact-only, never hallucinated) when no LLM is configured.
- Duplicate prevention, approval-gated sending, only-verified-emails-may-send
  gating, daily send caps, follow-up cadence and cancellation-on-reply, and
  calendar-collision checks all work against the local SQLite database with
  zero external services.
- `ConsoleEmailProvider` (writes approved emails to `data/outbox/` instead of
  sending) and `NullCalendarProvider` (in-app collision detection only) are
  the defaults, so nothing goes out over the network until you deliberately
  wire up real credentials.

## What each credential buys you (and why it's needed)

| Provider | Why it's needed | What it supplies | Where the key goes |
|---|---|---|---|
| **Google Programmable Search Engine** | The Discovery Agent needs a real, ToS-compliant web search API -- not scraping -- to find candidate profiles, company bios, and news mentions | Search results (title/snippet/URL) that get parsed into candidate people | `.env`: `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX` |
| **Anthropic (Claude)** | Turns retained facts into fluent, personalized prose (research synthesis, networking thesis, email drafts, reply classification). Without it, the same *facts* are used but rendered through fixed, less fluent templates | Prose generation + structured JSON extraction, always validated against a schema before being trusted | `.env`: `ANTHROPIC_API_KEY` |
| **Hunter.io** | Professional email discovery is domain-based; Hunter's Email Finder API is the simplest legitimate provider to wire up first (Apollo/People Data Labs/RocketReach can be added later behind the same `PeopleDataProvider` interface) | A work email guess plus Hunter's own confidence score, which maps to our `HIGH_CONFIDENCE`/`UNVERIFIED` statuses | `.env`: `HUNTER_API_KEY` |
| **Gmail API (OAuth)** | The only way to actually send from your own mailbox and see reply threads, rather than a third-party relay | Real sends (with the message's Gmail thread ID recorded) and thread-based reply detection | `.env`: `GMAIL_CREDENTIALS_JSON`, `GMAIL_TOKEN_JSON`, `GMAIL_SENDER_EMAIL` |
| **Google Calendar (OAuth)** | Needed to read real free/busy time and create real events; without it, scheduling still prevents double-booking against this app's own meeting records, it just can't see your actual calendar | Free/busy windows, event creation | `.env`: `GOOGLE_CALENDAR_CREDENTIALS_JSON`, `GOOGLE_CALENDAR_TOKEN_JSON`, `GOOGLE_CALENDAR_ID` |

Only VERIFIED/HIGH_CONFIDENCE email records are ever allowed into the send
queue -- an UNVERIFIED, BOUNCED, or DO_NOT_CONTACT email blocks sending
regardless of approval status.

Without the search provider configured, `network discover` always returns
zero results -- by design, so the system never fabricates prospects out of
synthetic data.

## Safety: LIVE_TEST_MODE

Set `LIVE_TEST_MODE=true` in `.env` while you're validating real credentials
end to end. It does not change the approval requirement (nothing is ever
sent without approval, in any mode) -- it lowers the volume ceilings:

- Discovery is capped at 20 people per `network live-test` run.
- Sending is capped at 5 emails/day, regardless of `config.yaml`'s
  `daily_email_limit`, enforced centrally in `agents/sending.py` so both the
  CLI and the web dashboard obey it.
- `network live-test` also force-enables this cap for its own run even if
  you forgot to set the env var.

Turn it off (`LIVE_TEST_MODE=false` or unset) once you trust the pipeline and
want the normal `config.yaml` limits to apply.

## Tests

```bash
pytest
```

100+ tests covering: duplicate prevention, UT Austin vs. other-UT-system
verification, deterministic scoring, schema validation, approval-gated send
(never sends a DRAFT/SKIPPED/BLOCKED message), only-verified-email-may-send
gating, daily/live-test send caps, follow-up cancellation on any reply
(positive or negative), opt-out/do-not-contact handling, Gmail-thread reply
detection and matching (including never reprocessing the same message
twice), calendar-collision detection, the `network doctor` diagnostics
(never printing secrets), and the web dashboard's draft/approve/send/
schedule/note routes (FastAPI TestClient against an isolated in-memory DB).
