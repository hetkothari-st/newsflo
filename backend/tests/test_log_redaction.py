import logging

from app.log_redaction import RedactSecretsFilter


def _record(msg: str, args: tuple = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name="httpx", level=logging.INFO, pathname="x", lineno=0,
        msg=msg, args=args, exc_info=None,
    )


def test_redacts_api_token_query_param():
    record = _record(
        'HTTP Request: %s %s "%s %d %s"',
        ("GET", "https://api.thenewsapi.com/v1/news/all?api_token=SECRET123&categories=tech", "HTTP/1.1", 200, "OK"),
    )
    RedactSecretsFilter().filter(record)
    assert "SECRET123" not in record.getMessage()
    assert "***REDACTED***" in record.getMessage()


def test_redacts_api_key_query_param():
    record = _record("GET https://example.com/x?api_key=SECRET456&lang=en")
    RedactSecretsFilter().filter(record)
    assert "SECRET456" not in record.getMessage()


def test_redacts_bare_token_and_key_params():
    record = _record("GET https://example.com/x?token=abc123&key=def456")
    RedactSecretsFilter().filter(record)
    message = record.getMessage()
    assert "abc123" not in message
    assert "def456" not in message


def test_leaves_message_without_a_secret_unchanged():
    record = _record("GET https://example.com/x?categories=tech&language=en")
    original = record.getMessage()
    RedactSecretsFilter().filter(record)
    assert record.getMessage() == original


def test_preserves_non_secret_parts_of_the_url():
    record = _record("GET https://api.thenewsapi.com/v1/news/all?api_token=SECRET123&categories=business,tech")
    RedactSecretsFilter().filter(record)
    message = record.getMessage()
    assert "categories=business,tech" in message
    assert "https://api.thenewsapi.com/v1/news/all" in message


def test_filter_always_returns_true_never_drops_the_record():
    record = _record("GET https://example.com/x?api_token=SECRET")
    assert RedactSecretsFilter().filter(record) is True
