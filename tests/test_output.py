import json

from infomaniak_cli.output import compact_json, error_json, pretty_json, render_table


def test_pretty_and_compact_json_rendering():
    data = {"profile": "work", "items": [{"id": "1"}]}

    assert pretty_json(data) == '{\n  "items": [\n    {\n      "id": "1"\n    }\n  ],\n  "profile": "work"\n}'
    assert compact_json(data) == '{"items":[{"id":"1"}],"profile":"work"}'


def test_error_json_shape_and_redaction():
    rendered = error_json("auth_failure", "Authorization: Bearer secret-token failed", 4)

    assert "secret-token" not in rendered
    assert json.loads(rendered) == {
        "error": {
            "type": "auth_failure",
            "message": "Authorization: Bearer *** failed",
            "exit_code": 4,
        }
    }


def test_render_table_uses_headers_and_rows():
    rendered = render_table(
        [{"id": "1", "name": "Admin"}, {"id": "22", "name": "Documents"}],
        columns=[("id", "ID"), ("name", "Name")],
    )

    assert rendered.splitlines() == [
        "ID  Name",
        "--  ---------",
        "1   Admin",
        "22  Documents",
    ]
