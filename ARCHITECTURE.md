# Architecture

## 0. Starting state

The repository contained a single unrelated placeholder file (`README.md`
with a snippet for an embeddable chat-bubble widget, never wired into any
build). There was no existing stack to integrate with, so this project was
built fresh on the designated branch.

**Stack chosen:** Python 3.11, SQLAlchemy 2.0 + Alembic, Typer + Rich for
the CLI, Pydantic for schema validation. Python was chosen over TypeScript
because the system is fundamentally an ETL + rules-engine + LLM-orchestration
pipeline over a relational schema, which SQLAlchemy/Alembic/Pydantic handle
well, and because it keeps the CLI, agents, and data layer in one consistent
type-checked codebase.

## 1. Directory structure

```
config/
  config.example.yaml     # targeting rules, scoring weights, cadence, tone (copy -> config.yaml)
migrations/                # Alembic migrations (source of truth for schema)
src/networking_agent/
  cli.py                   # `network discover|review|send|followups|inbox|schedule|dashboard`
  config.py                # loads config.yaml + .env into a validated Settings object
  enums.py                 # shared vocabulary (UTStatus, RelationshipStatus, ReplyClassification, ...)
  logging_utils.py          # structured agent-action logging (data/agent.log), secret redaction
  db/
    models.py               # people, companies, education, employment, sources, emails,
                             # outreach, activities, meetings, relationships, campaigns, settings
    session.py, base.py
  schemas/
    prospect.py              # pydantic I/O contracts for every LLM call (schema-validated JSON)
  adapters/                  # one interface + swappable implementations per external capability
    base.py                  # SearchProvider, LLMProvider, EmailProvider, CalendarProvider,
                              # PeopleDataProvider, EmailVerificationProvider (all ABCs)
    search_provider.py        # GoogleCSEProvider | MockSearchProvider
    llm_provider.py            # AnthropicLLMProvider | NullLLMProvider (fact-only fallback)
    email_provider.py          # ConsoleEmailProvider (writes data/outbox/*) | GmailEmailProvider
    calendar_provider.py       # NullCalendarProvider | GoogleCalendarProvider
    people_data_provider.py    # NullPeopleDataProvider | HunterEmailFinder
    email_verification_provider.py  # MXCheckEmailVerifier (free, local, caps at HIGH_CONFIDENCE)
  agents/                    # the 10 agents from the design doc, one module each
    context.py                # AgentContext: bundles session + settings + all providers
    discovery.py, verification.py, research.py, scoring.py, email_agent.py,
    followup.py, response.py, scheduling.py, crm.py, analytics.py
    pipeline.py                # shared discover->verify->research->score->promote->email-discover
                                # sequence used by both `network discover` and `network live-test`
    email_discovery.py         # calls PeopleDataProvider + EmailVerificationProvider per person
    sending.py                 # single choke point for actually sending: approval gate,
                                # verification-status gate, daily/live-test send cap, idempotent send
    diagnostics.py              # `network doctor` checks -- read-only, never prints secrets
  services/                  # pure-function helpers agents share, independently unit-testable
    query_builder.py           # varied multi-pattern search query generation
    dedupe.py                  # normalized-identity duplicate prevention
    scoring_rules.py            # deterministic 0-100 scoring (not LLM-based -- reproducible)
    cadence.py                  # business-day arithmetic for follow-up scheduling
    companies.py                 # get-or-create Company rows
    llm_json.py                  # parse+validate LLM JSON output against a pydantic schema
  web/                        # FastAPI dashboard -- server-rendered HTML, no JS build step
    app.py                      # create_app(), mounts routers + /static
    deps.py                      # per-request DB session + AgentContext dependency
    templating.py                 # shared Jinja2Templates instance
    routers/                      # today, prospects, outreach, replies, meetings,
                                   # relationships, analytics, settings_page -- each one
                                   # calls the same agents/services the CLI calls
    templates/, static/style.css
tests/                       # pytest; in-memory SQLite + fake providers, no network calls
USER_PROFILE.md              # you fill this out; read by the Email/Research agents
.env.example                 # every optional credential, documented, never committed
```

## 2. Data flow (per the design doc's numbered agents)

```
DISCOVERY        -> Person rows (status DISCOVERED), Source rows with URLs
VERIFICATION     -> UTStatus (VERIFIED/LIKELY/UNVERIFIED/FALSE) + rationale + Education row
RESEARCH         -> additional Source rows, FACT/INFERENCE-tagged findings, personalization angles
SCORING          -> 7 sub-scores + total (0-100) + networking_thesis; CRM promotes to
                    READY_FOR_REVIEW automatically only if VERIFIED + score >= review threshold
EMAIL DISCOVERY  -> PeopleDataProvider.find_email() + EmailVerificationProvider.verify();
                    creates an EmailRecord if (and only if) one is found -- never guessed
EMAIL            -> Outreach row, status=DRAFT (never auto-sent)
[human]          -> network review: Approve / Edit / Skip / Block
SEND             -> agents/sending.py: approval gate -> daily/live-test cap -> only
                    VERIFIED/HIGH_CONFIDENCE emails -> real send, thread_id captured
FOLLOW-UP        -> computes next_action_date (business days), enforces 3-attempt max
RESPONSE         -> `network inbox` scans each contacted person's Gmail thread for
                    messages not already processed and not from us, classifies them,
                    and cancels remaining follow-ups on ANY reply (+/-)
SCHEDULING       -> proposes/creates calendar events, collision-checked against calendar + DB
CRM              -> owns the Relationship state machine + Activity audit log
ANALYTICS        -> read-only response/meeting-rate rollups by industry/title/geo/template/etc.
```

Every agent receives one `AgentContext` (DB session + Settings + all six
providers) rather than ad hoc parameters, and every LLM call goes through
`services/llm_json.py`, which parses and pydantic-validates the response
before anything touches the database -- invalid output is never persisted,
the caller falls back to a deterministic path instead.

## 3. External APIs / integrations

| Capability | Works today without a key? | Provider(s) |
|---|---|---|
| Web search (discovery) | No -- returns 0 results, by design (never fabricates prospects) | Google Programmable Search Engine (`GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_CX`) |
| Research/email prose, reply classification | Yes -- deterministic fact-only fallback; better with a key | Anthropic (`ANTHROPIC_API_KEY`) |
| UT Austin verification | Yes -- keyword-based fallback distinguishing UT Austin from other UT-system schools; better with an LLM | (same Anthropic key) |
| Scoring | Yes, always -- intentionally rule-based, not LLM-based, so it's reproducible/testable | none |
| Work email discovery | No -- returns nothing rather than guessing (`agents/email_discovery.py` runs automatically during discovery, just finds nothing without a key) | Hunter.io (`HUNTER_API_KEY`); Apollo/PDL/RocketReach pluggable behind the same `PeopleDataProvider` interface |
| Email verification | Partial -- free MX/A-record check caps at HIGH_CONFIDENCE, used to upgrade (never downgrade) a provider's own verdict | any paid verifier (ZeroBounce, NeverBounce, ...) can be added behind `EmailVerificationProvider` |
| Sending email | Yes -- writes to `data/outbox/` instead of sending (dry-run); real send still requires an email that's VERIFIED/HIGH_CONFIDENCE and under the daily send cap | Gmail API OAuth (`GMAIL_CREDENTIALS_JSON`/`GMAIL_TOKEN_JSON`) for real sending |
| Reply detection | No -- `network inbox` reports nothing new without real Gmail threads to scan; manual `--person-id --reply-text` always works | Gmail API OAuth (same credentials as sending) |
| Calendar | Yes -- in-app collision detection only, no real calendar visibility | Google Calendar OAuth (`GOOGLE_CALENDAR_CREDENTIALS_JSON`/`GOOGLE_CALENDAR_TOKEN_JSON`) |

## 4. Implementation checklist / phase status

- [x] **Phase 1** -- project architecture, DB schema + Alembic migration, config loader, CLI skeleton, prospect schemas
- [x] **Phase 2** -- search/discovery wiring (Google CSE adapter + LLM/heuristic extraction), UT verification, research pipeline, deterministic scoring
- [x] **Phase 3** -- email generation (LLM + fact-only fallback), human review workflow (`network review`, Approve/Edit/Skip/Block), approval-gated send guard
- [x] **Phase 4** -- email discovery (`agents/email_discovery.py`) wired into the pipeline: calls `PeopleDataProvider.find_email()` + `EmailVerificationProvider.verify()` for every discovered person; send gating (`agents/sending.py`) only allows VERIFIED/HIGH_CONFIDENCE addresses through, regardless of approval status. Needs `HUNTER_API_KEY` to actually find emails; without it, people simply have no email on file.
- [x] **Phase 5** -- `GmailEmailProvider` sends and captures the Gmail `threadId`; `agents/response.py` scans each contacted person's thread (`list_thread_messages`), skips messages already processed (`Outreach.last_reply_checked_message_id`) and messages from our own sender address, classifies the newest new one, and applies it (stops follow-ups, updates relationship state). `network inbox` / the web Replies page trigger this. Needs `GMAIL_CREDENTIALS_JSON`/`GMAIL_TOKEN_JSON` to have real threads to scan; manual ingestion (`--person-id --reply-text`) always works.
- [x] **Phase 6** -- `SchedulingAgent` + `GoogleCalendarProvider` implemented; collision detection works today against the app's own Meeting table even without Google Calendar credentials.
- [x] **Phase 7** -- web dashboard (`network serve`): Today/Prospects/Outreach/Replies/Meetings/Relationships/Analytics/Settings, server-rendered (FastAPI + Jinja2, no JS build step), calling the same agent/service functions as the CLI so there's one source of truth for business logic. Binds to `127.0.0.1` by default; no auth layer, so keep it local unless you put one in front of it.
- [x] **Phase 8** -- `LIVE_TEST_MODE` (env-driven, also force-enabled by the `network live-test` command itself): caps discovery at 20/run and sends at 5/day, enforced centrally in `agents/sending.py` so the CLI and web dashboard can't drift out of sync. Approval is required in every mode, always.
- [x] **Phase 9** -- `network doctor`: reports DB connectivity, LLM/search/email-discovery provider configuration, Gmail/Calendar OAuth status (via `refresh_token` presence, never constructing a real provider so it never triggers an interactive OAuth flow), missing recommended env vars, current send mode, and live-test mode -- without ever printing a secret value.

## 5. Safety properties enforced in code (not just docs)

- `crm.assert_approved_for_sending()` raises unless an Outreach is
  `APPROVED` or `EDITED`, and additionally blocks anything tied to an
  excluded/do-not-contact person -- `network send` cannot bypass this.
- `services/dedupe.py` is consulted before every new Person is created
  (by profile URL, then normalized name+company, then email).
- `enums.STOP_FOLLOWUP_CLASSIFICATIONS` cancels all pending follow-ups on
  *any* reply classification except NEEDS_FOLLOW_UP/AUTOMATED/UNKNOWN --
  positive or negative, the cadence stops.
- `EmailProvider.send()` implementations are keyed by `idempotency_key`
  (the Outreach's UUID) so a retried send can never double-send.
- UT status FALSE (a different UT-system school) caps the total score at
  40 regardless of every other factor, so it can never auto-queue.
- `agents/sending.py` is the only code path that actually sends: it gates
  on approval status, then on email `verification_status` (only
  VERIFIED/HIGH_CONFIDENCE), then on the daily/live-test send cap, in that
  order -- both `network send` and the web dashboard's Outreach page call
  this one function, so neither can drift out of sync with the other.
- `network doctor` and `agents/diagnostics.py` never construct a real
  `GmailEmailProvider`/`GoogleCalendarProvider` (which would trigger an
  interactive OAuth flow) -- they only check file presence and whether a
  saved token has a `refresh_token`, and never print a secret value.
