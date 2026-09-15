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

**6. Google Cloud Console setup (one project, one OAuth client, covers both Gmail + Calendar)**

The application expects a standard **OAuth 2.0 Client ID of type "Desktop app"**
(sometimes called an "installed application" credential) -- the JSON you
download has an `"installed": {...}` key. This is *not* a service-account
key and *not* a simple API key; Gmail/Calendar send-as-you APIs require
delegated user consent, which only an OAuth client provides. "Desktop app"
is the correct type (not "Web application") because the code uses Google's
loopback flow (`InstalledAppFlow.run_local_server`), which needs no
pre-registered redirect URI -- Google auto-allows any `http://localhost:<port>`
for this client type, so you can skip any "Authorized redirect URIs" field.

Step by step:

1. **Create or select a project.** Go to https://console.cloud.google.com/,
   and either pick an existing project from the top project-picker dropdown
   or click "New Project" (any name, e.g. "networking-agent").
2. **Enable the Gmail API.** In the left sidebar: APIs & Services > Library
   > search "Gmail API" > Enable.
3. **Enable the Google Calendar API.** Same Library page > search "Google
   Calendar API" > Enable.
4. **Configure the OAuth consent screen.** APIs & Services > OAuth consent
   screen.
   - **User type**: choose **External** unless you have a Google Workspace
     organization and only ever intend this for accounts inside it, in
     which case **Internal** is simpler (no test-user list, no verification
     needed). For a personal `@gmail.com` account, External is the only
     option available.
   - Fill in the required fields (app name, your email as support/developer
     contact). You do not need to submit for verification -- an
     unverified External app works fine in "Testing" mode for your own
     account, which is exactly what step 5 sets up.
   - **Scopes**: you can skip adding scopes here: the app requests them
     directly in the OAuth flow (see "Minimum scopes" below), and
     Console-level scope configuration is optional for apps in Testing mode.
5. **Add yourself as a test user** (External + Testing mode only). Same
   OAuth consent screen page > "Test users" > Add your own Google account
   email. Without this, Google will refuse to let you complete consent as
   an unverified app.
6. **Create the OAuth client credentials.** APIs & Services > Credentials >
   Create Credentials > OAuth client ID.
   - **Application type: Desktop app** (this is the one setting most likely
     to be picked wrong -- "Web application" will not work with this code's
     loopback flow without extra config).
   - Name it anything (e.g. "networking-agent-desktop").
   - No redirect URIs to add.
7. **Download the credential JSON.** After creation, click the download
   icon next to the new client ID (or find it later under Credentials).

**7. Save the credential file and configure `.env`**

Save the downloaded JSON to `secrets/google_oauth_client.json` (create the
`secrets/` directory if it doesn't exist -- it's already gitignored). One
file covers both APIs -- point both env vars at it:

```
GMAIL_CREDENTIALS_JSON=./secrets/google_oauth_client.json
GMAIL_TOKEN_JSON=./secrets/gmail_token.json
GMAIL_SENDER_EMAIL=you@yourdomain.com

GOOGLE_CALENDAR_CREDENTIALS_JSON=./secrets/google_oauth_client.json
GOOGLE_CALENDAR_TOKEN_JSON=./secrets/calendar_token.json
GOOGLE_CALENDAR_ID=primary
```

Gmail and Calendar still get separate *token* files (`gmail_token.json` /
`calendar_token.json`) because each is authorized independently, with its
own scopes, and refreshed independently.

**Minimum scopes** (already what the code requests -- nothing broader):

| API | Scopes | Why |
|---|---|---|
| Gmail | `gmail.send`, `gmail.readonly` | `gmail.send` to send networking emails; `gmail.readonly` to read thread messages for reply detection -- Gmail has no narrower read scope for specific threads, so this is the smallest read grant that works |
| Calendar | `calendar.events`, `calendar.freebusy` | `calendar.freebusy` to check availability/conflicts (read-only, can't see event details); `calendar.events` to create meetings. Deliberately narrower than the blanket `calendar` scope, which also grants calendar-list/ACL/settings management this app never touches |

**First-run authentication:** the first time `network gmail-test` (or
`network send`, or the dashboard) needs Gmail, it opens your browser to
`http://localhost:<random-port>`, asks you to sign in and consent, then
writes the resulting token to `GMAIL_TOKEN_JSON` so you don't repeat this.
Same for `network calendar-test` and `GOOGLE_CALENDAR_TOKEN_JSON`. Do this
once, deliberately -- see LIVE_TEST_MODE below -- and never commit either
token file (`.gitignore` already excludes `secrets/`, `*_token.json`, and
`*_credentials.json` as defense in depth).

**Token refresh** happens automatically: both providers check
`creds.expired and creds.refresh_token` on every construction and call
`creds.refresh()` before falling back to the interactive browser flow, so
a still-valid refresh token never triggers a new consent screen.

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
provider (LLM/search/email-discovery) is configured, current send mode
(dry-run vs. live), and whether LIVE_TEST_MODE is on. For Gmail and
Calendar specifically, it distinguishes:

- `not_configured` -- no OAuth client credentials file on disk yet
- `error` -- credentials file isn't a valid OAuth client JSON, or the
  saved token file is invalid/incomplete (delete it and re-authenticate)
- `warning` (auth required) -- client credentials present, but no token
  yet -- run `network gmail-test` / `network calendar-test`
- `warning` (expired) -- token present and will refresh automatically on
  next use, nothing to do
- `ok` -- fully authorized

**10a. Authenticate and verify Gmail + Calendar**

```bash
network gmail-test       # opens a browser once, then confirms access (never sends)
network calendar-test    # opens a browser once, then confirms access (never creates an event)
network doctor           # should now show gmail: ok, google_calendar: ok
```

If you want to confirm actual send/create behavior (message IDs, thread
IDs, event IDs coming back correctly), two explicit, confirmation-gated
commands exist for exactly that -- each asks "Proceed?" before doing
anything real:

```bash
network gmail-test-send --to you@example.com   # sends one clearly-labeled test email
network calendar-test-create                    # creates one clearly-labeled test event,
                                                  # then offers to delete it immediately
```

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
network gmail-test              # authenticate + verify Gmail access (never sends)
network calendar-test           # authenticate + verify Calendar access (never creates an event)
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
| **Gmail API (OAuth, scopes: `gmail.send` + `gmail.readonly`)** | The only way to actually send from your own mailbox and see reply threads, rather than a third-party relay | Real sends (with the message's Gmail thread ID recorded) and thread-based reply detection | `.env`: `GMAIL_CREDENTIALS_JSON`, `GMAIL_TOKEN_JSON`, `GMAIL_SENDER_EMAIL` |
| **Google Calendar (OAuth, scopes: `calendar.events` + `calendar.freebusy`)** | Needed to read real free/busy time and create real events; without it, scheduling still prevents double-booking against this app's own meeting records, it just can't see your actual calendar | Free/busy windows, event creation | `.env`: `GOOGLE_CALENDAR_CREDENTIALS_JSON`, `GOOGLE_CALENDAR_TOKEN_JSON`, `GOOGLE_CALENDAR_ID` |

Gmail and Calendar share **one** Google Cloud OAuth client (Desktop app
type) -- see "Google Cloud Console setup" above for the full walkthrough,
including which consent-screen user type to pick and how to add yourself
as a test user.

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
