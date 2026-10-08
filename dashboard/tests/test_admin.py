"""Operators and the server console, with Docker and RCON faked (see conftest)."""

import json

from conftest import post, read_audit


def create(client, name="survival"):
    return post(client, "/worlds", {"name": name})


def world_json(app, name="survival"):
    return app.extensions["worlds"].store.load(name)


def whitelist(client, player, name="survival"):
    return post(client, f"/worlds/{name}/whitelist/add", {"player": player})


def last_event(audit_path):
    return read_audit(audit_path)[-1]


# ---- Operators ----

def test_op_while_stopped_saves_world_json(logged_in, app, rcon_fake, audit_path):
    create(logged_in)
    whitelist(logged_in, "Steve")
    resp = post(logged_in, "/worlds/survival/ops/add", {"player": "steve"})
    assert resp.status_code == 302
    assert world_json(app)["ops"] == ["Steve"]  # whitelist spelling wins
    assert rcon_fake.commands == []
    event = last_event(audit_path)
    assert (event["event"], event["world"], event["target"], event["user"]) == \
        ("op_granted", "survival", "Steve", "admin")
    page = logged_in.get("/worlds/survival").get_data(as_text=True)
    assert "Remove op" in page


def test_op_while_running_uses_rcon(logged_in, app, rcon_fake):
    create(logged_in)
    whitelist(logged_in, "Steve")
    post(logged_in, "/worlds/survival/start")
    post(logged_in, "/worlds/survival/ops/add", {"player": "Steve"})
    assert "op Steve" in rcon_fake.commands
    assert world_json(app)["ops"] == ["Steve"]


def test_op_needs_whitelist(logged_in, app, audit_path):
    create(logged_in)
    post(logged_in, "/worlds/survival/ops/add", {"player": "Steve"})
    assert world_json(app)["ops"] == []
    assert last_event(audit_path)["event"] == "world_created"


def test_deop_running_and_stopped(logged_in, app, rcon_fake, audit_path, tmp_path):
    create(logged_in)
    whitelist(logged_in, "Steve")
    post(logged_in, "/worlds/survival/ops/add", {"player": "Steve"})
    # Stopped: ops.json is edited directly, like whitelist.json.
    data = tmp_path / "worlds" / "survival" / "data"
    (data / "ops.json").write_text(json.dumps([{"name": "Steve", "uuid": "x", "level": 4}]))
    post(logged_in, "/worlds/survival/ops/remove", {"player": "Steve"})
    assert world_json(app)["ops"] == []
    assert json.loads((data / "ops.json").read_text()) == []
    assert last_event(audit_path)["event"] == "op_revoked"

    post(logged_in, "/worlds/survival/ops/add", {"player": "Steve"})
    post(logged_in, "/worlds/survival/start")
    post(logged_in, "/worlds/survival/ops/remove", {"player": "Steve"})
    assert "deop Steve" in rcon_fake.commands
    assert world_json(app)["ops"] == []


def test_removing_from_whitelist_also_deops(logged_in, app):
    create(logged_in)
    whitelist(logged_in, "Steve")
    post(logged_in, "/worlds/survival/ops/add", {"player": "Steve"})
    post(logged_in, "/worlds/survival/whitelist/remove", {"player": "Steve"})
    assert world_json(app)["ops"] == []
    assert world_json(app)["whitelist"] == []


def test_ops_need_login(client, app):
    assert client.post("/worlds/survival/ops/add", data={"player": "Steve"}).status_code in (302, 400)


# ---- Console ----

def test_console_runs_command_and_shows_output(logged_in, rcon_fake, audit_path):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    rcon_fake.replies["list"] = "\u00a76There are 0 of a max of 10 players online:"
    resp = post(logged_in, "/worlds/survival/console", {"command": "/list"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/worlds/survival#console")
    assert rcon_fake.commands[-1] == "list"
    event = last_event(audit_path)
    assert (event["event"], event["world"], event["target"]) == ("console_command", "survival", "list")
    page = logged_in.get("/worlds/survival").get_data(as_text=True)
    # Formatting codes are stripped.
    assert "There are 0 of a max of 10 players online:" in page
    assert "\u00a7" not in page


def test_console_output_is_escaped(logged_in, rcon_fake):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    rcon_fake.replies["say"] = "<script>alert(1)</script>"
    post(logged_in, "/worlds/survival/console", {"command": "say hi"})
    page = logged_in.get("/worlds/survival").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_console_needs_running_server(logged_in, rcon_fake, audit_path):
    create(logged_in)
    post(logged_in, "/worlds/survival/console", {"command": "list"})
    assert rcon_fake.commands == []
    assert last_event(audit_path)["event"] == "world_created"


def test_console_rejects_multiline_and_empty(logged_in, rcon_fake):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    before = list(rcon_fake.commands)
    post(logged_in, "/worlds/survival/console", {"command": "say a\nop Mallory"})
    post(logged_in, "/worlds/survival/console", {"command": "   "})
    assert rcon_fake.commands == before


def test_console_needs_csrf(logged_in, rcon_fake):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    resp = logged_in.post("/worlds/survival/console", data={"command": "stop"})
    assert resp.status_code == 400
    assert "stop" not in rcon_fake.commands


def test_wazuh_link_in_nav(logged_in, app):
    page = logged_in.get("/").get_data(as_text=True)
    assert 'href="https://localhost"' in page
    app.config["WAZUH_URL"] = ""
    assert "Wazuh" not in logged_in.get("/").get_data(as_text=True)
