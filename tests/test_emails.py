"""Source-level tests for the approved native Gmail email channel.

These tests do not connect to Gmail or send messages.
"""

import inspect

import email_utils


def test_supported_email_channel_is_native_gmail_ssl():
    source = inspect.getsource(email_utils)
    assert email_utils.SMTP_SERVER == "smtp.gmail.com"
    assert email_utils.SMTP_PORT == 465
    assert "smtplib.SMTP_SSL" in source
    assert "win32com" not in source


def test_email_credentials_are_read_from_environment():
    source = inspect.getsource(email_utils)
    assert "GMAIL_USER" in source
    assert "GMAIL_APP_PASSWORD" in source
