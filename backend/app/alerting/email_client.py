import logging

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    """Send an email, returning True on success.

    Default/dev backend (no RESEND_API_KEY set): log the message at INFO and
    return True — never touches the network, never needs a key, always
    "succeeds". This is the backend every test exercises.

    If RESEND_API_KEY is configured, a real HTTP-calling backend would go here.
    It is intentionally left as a loud NotImplementedError stub: no real Resend
    key was available to build/test an HTTP implementation against, so we fail
    loudly rather than silently pretend to send. (Same optional-at-dev-time
    pattern as anthropic_api_key in Plan 1.)
    """
    if not settings.resend_api_key:
        logger.info(f"[console-email] to={to} subject={subject!r} body={body!r}")
        return True
    raise NotImplementedError(
        "Real email sending not implemented — no Resend API key was available "
        "to build/test against"
    )
