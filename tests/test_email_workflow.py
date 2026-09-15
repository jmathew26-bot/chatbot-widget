import pytest

from networking_agent.agents import crm, email_agent
from networking_agent.adapters.base import EmailMessage
from networking_agent.enums import OutreachStatus
from tests.factories import make_person


def test_draft_starts_in_draft_status(db_session, ctx):
    person = make_person(db_session)
    outreach, warnings = email_agent.draft_email(ctx, person, sequence_number=1)
    assert outreach.status == OutreachStatus.DRAFT.value


def test_cannot_send_a_draft_outreach(db_session, ctx):
    person = make_person(db_session)
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)
    with pytest.raises(crm.ApprovalRequiredError):
        crm.assert_approved_for_sending(outreach)


def test_approve_transitions_to_approved_and_allows_sending(db_session, ctx):
    person = make_person(db_session)
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)
    crm.approve_outreach(ctx, outreach)
    assert outreach.status == OutreachStatus.APPROVED.value
    crm.assert_approved_for_sending(outreach)  # should not raise


def test_skip_leaves_outreach_unsendable(db_session, ctx):
    person = make_person(db_session)
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)
    crm.skip_outreach(ctx, outreach)
    assert outreach.status == OutreachStatus.SKIPPED.value
    with pytest.raises(crm.ApprovalRequiredError):
        crm.assert_approved_for_sending(outreach)


def test_block_prevents_sending_even_if_previously_approved(db_session, ctx):
    person = make_person(db_session)
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)
    crm.approve_outreach(ctx, outreach)
    crm.block_person(ctx, person, reason="asked not to be contacted")
    with pytest.raises(crm.ApprovalRequiredError):
        crm.assert_approved_for_sending(outreach)


def test_edited_outreach_can_be_sent(db_session, ctx):
    person = make_person(db_session)
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)
    crm.edit_outreach(ctx, outreach, subject="New subject", body="New body text.")
    assert outreach.status == OutreachStatus.EDITED.value
    crm.assert_approved_for_sending(outreach)  # EDITED counts as human-reviewed


def test_email_provider_send_is_idempotent(db_session, ctx):
    person = make_person(db_session)
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)
    crm.approve_outreach(ctx, outreach)
    message = EmailMessage(to_address="jane@example.com", subject=outreach.subject, body=outreach.body)

    result1 = ctx.email.send(message, idempotency_key=outreach.idempotency_key)
    result2 = ctx.email.send(message, idempotency_key=outreach.idempotency_key)

    assert result1.success and result2.success
    assert len(ctx.email.sent) == 1  # second call was a no-op, not a duplicate send


def test_fallback_draft_respects_word_limits(db_session, ctx):
    person = make_person(db_session)
    outreach, warnings = email_agent.draft_email(ctx, person, sequence_number=1)
    word_count = len(outreach.body.split())
    assert word_count <= ctx.settings.email.hard_max_words


def test_fallback_draft_never_claims_ut_connection_when_unverified(db_session, ctx):
    person = make_person(db_session, ut_status="UNVERIFIED")
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)
    assert "longhorn" not in outreach.body.lower()
    assert "ut austin" not in outreach.body.lower()


def test_fallback_draft_mentions_ut_when_verified(db_session, ctx):
    person = make_person(db_session, ut_status="VERIFIED")
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)
    assert "longhorn" in outreach.body.lower() or "ut alumni" in outreach.body.lower()
