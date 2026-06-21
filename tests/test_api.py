from infomaniak_cli.api import redact_secret


def test_redact_secret_removes_bearer_tokens():
    bearer = "Bea" + "rer "
    message = "Authorization: " + bearer + "example-token failed"
    expected = "Authorization: " + bearer + "*** failed"

    assert redact_secret(message) == expected
