import logging
import re

# Matches api_token=/api_key=/token=/key= query-param values anywhere in a
# rendered log message. Needed because httpx's own request logger writes
# the full request URL verbatim, and at least one ingestion source
# (thenewsapi.com) authenticates via a query param rather than a header --
# without this, the API key ends up in plaintext in every deployment's log
# history (confirmed in production: the real key was visible in Railway
# logs the first time this source polled).
_SECRET_QUERY_PARAM_PATTERN = re.compile(
    r"([?&](?:api_token|api_key|token|key)=)[^&\s\"]+", re.IGNORECASE
)


class RedactSecretsFilter(logging.Filter):
    """Masks secret query-param values in any log record before it reaches
    a handler. Renders the record's message first (record.getMessage(),
    which safely applies %-style args) rather than regexing record.msg
    directly -- the raw msg is often just a format string like "HTTP
    Request: %s %s", with the actual URL living in record.args, not msg
    itself.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _SECRET_QUERY_PARAM_PATTERN.sub(r"\1***REDACTED***", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
