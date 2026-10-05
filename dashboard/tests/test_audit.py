import json

from mcdash.audit import audit
from conftest import login, read_audit


def test_each_event_is_one_json_line(client, audit_path):
    login(client, password="wrong")
    login(client)
    lines = audit_path.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        record = json.loads(line)
        assert set(record) >= {"timestamp", "app", "event", "user", "src_ip"}
        assert record["timestamp"].endswith("+00:00")


def test_extra_fields_and_newline_injection(app, audit_path):
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        audit("whitelist_add", user="admin", player="evil\n{\"event\": \"fake\"}")
    events = read_audit(audit_path)
    # The newline is escaped by JSON encoding, so the attacker-controlled
    # value can't start a forged second log line.
    assert len(events) == 1
    assert events[0]["event"] == "whitelist_add"
    assert events[0]["src_ip"] == "127.0.0.1"


def test_password_never_logged(client, audit_path):
    login(client, password="hunter2-secret")
    assert "hunter2-secret" not in audit_path.read_text()
