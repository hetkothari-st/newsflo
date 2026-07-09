import logging

import pytest

import app.alerting.email_client as email_client
from app.alerting.email_client import send_email


def test_send_email_console_backend_returns_true_and_logs(caplog):
    with caplog.at_level(logging.INFO):
        result = send_email(to="a@example.com", subject="Hello", body="World")

    assert result is True
    assert "[console-email]" in caplog.text
    assert "a@example.com" in caplog.text


def test_send_email_raises_when_real_key_configured(monkeypatch):
    monkeypatch.setattr(email_client.settings, "resend_api_key", "fake-key")

    with pytest.raises(NotImplementedError):
        send_email(to="a@example.com", subject="Hello", body="World")
