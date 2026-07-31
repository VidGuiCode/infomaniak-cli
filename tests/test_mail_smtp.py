"""Offline tests for SMTP submission and mail connectivity diagnostics (0.3.6).

The reported failure was a hang that looked like an auth problem but was a
blocked port, so these tests pin the transport, the error classification, and
that a timed-out send is never retried.
"""

import smtplib
import socket
import ssl

import pytest

from infomaniak_cli.services.mail import (
    DEFAULT_SMTP_PORT,
    DEFAULT_SMTP_SECURITY,
    MailError,
    SMTPClient,
    probe_connectivity,
)


def _message():
    import email.message

    msg = email.message.EmailMessage()
    msg["From"] = "user@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = "Test"
    msg.set_content("Body")
    return msg


class FakeSMTP:
    """Records the handshake order so STARTTLS sequencing can be asserted."""

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls = []
        self.refused = {}

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        assert context is not None, "STARTTLS must verify certificates"
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(f"login:{username}")

    def send_message(self, message):
        self.calls.append("send")
        return self.refused

    def quit(self):
        self.calls.append("quit")


def _client(factory=None, ssl_factory=None, **kwargs):
    return SMTPClient(
        "mail.example.com",
        kwargs.pop("port", DEFAULT_SMTP_PORT),
        "user@example.com",
        "device-password",
        smtp_factory=factory,
        smtp_ssl_factory=ssl_factory,
        **kwargs,
    )


def test_defaults_are_starttls_on_587():
    client = _client()

    assert client.port == 587
    assert client.security == DEFAULT_SMTP_SECURITY == "starttls"


def test_starttls_handshake_order_ehlo_starttls_ehlo_login():
    created = []

    def factory(host, port, timeout=None):
        conn = FakeSMTP(host, port, timeout)
        created.append(conn)
        return conn

    assert _client(factory).send_message(_message()) == {"status": "sent"}

    assert created[0].calls == [
        "ehlo", "starttls", "ehlo", "login:user@example.com", "send", "quit",
    ]
    assert created[0].timeout is not None, "a blocked port must fail, not hang"


def test_ssl_mode_uses_implicit_tls_and_no_starttls():
    created = []

    def ssl_factory(host, port, timeout=None):
        conn = FakeSMTP(host, port, timeout)
        created.append(conn)
        return conn

    client = _client(ssl_factory=ssl_factory, port=465, security="ssl")
    assert client.send_message(_message()) == {"status": "sent"}

    assert "starttls" not in created[0].calls
    assert created[0].port == 465


def test_unknown_security_mode_is_refused():
    with pytest.raises(MailError) as excinfo:
        _client(security="carrier-pigeon")

    assert "starttls" in str(excinfo.value)


def _failing_client(exc, **kwargs):
    class Failing(FakeSMTP):
        def login(self, username, password):
            raise exc

    def factory(host, port, timeout=None):
        return Failing(host, port, timeout)

    return _client(factory, **kwargs)


def test_authentication_failure_is_reported_as_such():
    client = _failing_client(smtplib.SMTPAuthenticationError(535, b"auth failed"))

    with pytest.raises(MailError) as excinfo:
        client.send_message(_message())

    message = str(excinfo.value)
    assert "authentication failed" in message
    assert "config.infomaniak.com" in message
    assert "timed out" not in message


def test_timeout_is_reported_as_a_network_problem_not_an_auth_problem():
    def factory(host, port, timeout=None):
        raise socket.timeout("timed out")

    with pytest.raises(MailError) as excinfo:
        _client(factory).send_message(_message())

    message = str(excinfo.value)
    assert "timed out" in message
    assert "mail.example.com:587" in message
    assert "outbound TCP" in message
    assert "not an authentication problem" in message


def test_starttls_negotiation_failure_suggests_the_ssl_transport():
    class NoTLS(FakeSMTP):
        def starttls(self, context=None):
            raise smtplib.SMTPNotSupportedError("STARTTLS not supported")

    with pytest.raises(MailError) as excinfo:
        _client(lambda h, p, timeout=None: NoTLS(h, p, timeout)).send_message(_message())

    message = str(excinfo.value)
    assert "STARTTLS" in message
    assert "--smtp-security ssl" in message


def test_tls_error_is_classified_as_a_negotiation_failure():
    class BadTLS(FakeSMTP):
        def starttls(self, context=None):
            raise ssl.SSLError("handshake failure")

    with pytest.raises(MailError) as excinfo:
        _client(lambda h, p, timeout=None: BadTLS(h, p, timeout)).send_message(_message())

    assert "STARTTLS negotiation failed" in str(excinfo.value)


def test_dns_failure_is_named_as_such():
    def factory(host, port, timeout=None):
        raise socket.gaierror("Name or service not known")

    with pytest.raises(MailError) as excinfo:
        _client(factory).send_message(_message())

    assert "resolve" in str(excinfo.value)


def test_connection_refused_points_at_outbound_access():
    def factory(host, port, timeout=None):
        raise ConnectionRefusedError("refused")

    with pytest.raises(MailError) as excinfo:
        _client(factory).send_message(_message())

    assert "outbound TCP" in str(excinfo.value)


def test_refused_recipient_is_reported():
    class Refusing(FakeSMTP):
        def send_message(self, message):
            return {"recipient@example.com": (550, b"no such user")}

    with pytest.raises(MailError) as excinfo:
        _client(lambda h, p, timeout=None: Refusing(h, p, timeout)).send_message(_message())

    assert "refused 1 recipient" in str(excinfo.value)


@pytest.mark.parametrize(
    "exc",
    [
        smtplib.SMTPAuthenticationError(535, b"bad device-password"),
        smtplib.SMTPException("failure for device-password"),
        socket.timeout("device-password timed out"),
    ],
)
def test_the_password_never_appears_in_any_error(exc):
    with pytest.raises(MailError) as excinfo:
        _failing_client(exc).send_message(_message())

    assert "device-password" not in str(excinfo.value)


def test_a_timed_out_send_is_never_retried():
    """Retrying could deliver twice if the server accepted but the reply was lost."""
    attempts = []

    def factory(host, port, timeout=None):
        attempts.append((host, port))
        raise socket.timeout("timed out")

    with pytest.raises(MailError):
        _client(factory).send_message(_message())

    assert len(attempts) == 1


def test_probe_connectivity_reports_reachable_without_sending():
    class FakeSocket:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    opened = []

    def connect(address, timeout):
        opened.append((address, timeout))
        return FakeSocket()

    result = probe_connectivity("mail.example.com", 587, connect=connect)

    assert result == {"host": "mail.example.com", "port": 587, "reachable": True, "error": None}
    assert opened == [(("mail.example.com", 587), 5)]


def test_probe_connectivity_reports_failure_instead_of_raising():
    def connect(address, timeout):
        raise socket.timeout("timed out")

    result = probe_connectivity("mail.example.com", 587, connect=connect)

    assert result["reachable"] is False
    assert result["error"]
