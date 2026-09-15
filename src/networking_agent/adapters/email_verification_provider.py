from __future__ import annotations

import logging
import re

from networking_agent.adapters.base import EmailVerificationProvider
from networking_agent.enums import EmailVerificationStatus

logger = logging.getLogger("networking_agent.email_verification")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MXCheckEmailVerifier(EmailVerificationProvider):
    """Free, local best-effort check: syntax validity + the domain has an
    MX (or A) record. This can only ever prove a domain *can* receive mail,
    not that the specific mailbox exists -- so it caps out at
    HIGH_CONFIDENCE, never VERIFIED. A paid provider (ZeroBounce, Hunter
    verifier, NeverBounce, ...) is needed for a true VERIFIED/BOUNCED
    result and can be plugged in behind this same interface.
    """

    def verify(self, email: str) -> str:
        if not _EMAIL_RE.match(email):
            return EmailVerificationStatus.UNVERIFIED.value
        domain = email.rsplit("@", 1)[-1]
        try:
            import dns.resolver

            try:
                dns.resolver.resolve(domain, "MX")
                return EmailVerificationStatus.HIGH_CONFIDENCE.value
            except dns.resolver.NoAnswer:
                dns.resolver.resolve(domain, "A")
                return EmailVerificationStatus.HIGH_CONFIDENCE.value
        except Exception as e:  # noqa: BLE001 - any DNS failure just means "can't confirm"
            logger.info("MX/A lookup failed for domain=%s: %s", domain, e)
            return EmailVerificationStatus.UNVERIFIED.value


def get_email_verification_provider() -> EmailVerificationProvider:
    return MXCheckEmailVerifier()
