"""World pages and actions, with Docker and RCON replaced by fakes (see conftest)."""

import json
import tarfile

import pytest

from conftest import post, read_audit


def create(client, name="survival"):
    return post(client, "/worlds", {"name": name})


def world_json(app, name="survival"):
    return app.extensions["worlds"].store.load(name)


def settings_form(world, **changes):
    form = {"type": world["type"], "version": world["version"],
            "memory": world["memory"], "port": str(world["port"])}
    for key, value in world["properties"].items():
        if isinstance(value, bool):
            if value:
                form[key] = "on"
        else:
            form[key] = str(value)
    form.update(changes)
    return form


def last_event(audit_path):
    return read_audit(audit_path)[-1]


# ---- Access control ----

@pytest.mark.parametrize("path", [
    "/worlds", "/worlds/survival/start", "/worlds/survival/stop", "/worlds/survival/settings",
    "/worlds/survival/whitelist/add", "/worlds/survival/backup",
])
def test_actions_need_login(client, docker_fake, path):
    resp = client.post(path, data={"name": "survival"})
    # Without a session, CSRF fails first (400) or the login redirect (302) kicks in;
    # either way nothing happens.
    assert resp.status_code in (302, 400)
    assert docker_fake.containers.created == []


def test_pages_need_login(client):
    assert client.get("/worlds/survival").status_code == 302


def test_actions_need_csrf(logged_in, app, docker_fake, audit_path):
    create(logged_in)
    resp = logged_in.post("/worlds/survival/start")
    assert resp.status_code == 400
    assert docker_fake.containers.created == []
    assert last_event(audit_path)["event"] == "csrf_failure"


# ---- Create / list ----

def test_create_world(logged_in, app, audit_path, tmp_path):
    resp = create(logged_in)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/worlds/survival"
    assert (tmp_path / "worlds" / "survival" / "data").is_dir()
    event = last_event(audit_path)
    assert event["event"] == "world_created"
    assert event["world"] == "survival"
    assert event["user"] == "admin"

    page = logged_in.get("/").get_data(as_text=True)
    assert "survival" in page and "not created" in page
    # The RCON password never reaches the browser.
    assert world_json(app)["rcon_password"] not in logged_in.get("/worlds/survival").get_data(as_text=True)


def test_create_bad_name(logged_in, app, audit_path):
    resp = create(logged_in, "../evil")
    assert resp.status_code == 302
    assert app.extensions["worlds"].store.names() == []
    assert all(e["event"] != "world_created" for e in read_audit(audit_path))


def test_unknown_world_404(logged_in):
    assert logged_in.get("/worlds/nope").status_code == 404
    assert post(logged_in, "/worlds/nope/start").status_code == 404
    assert post(logged_in, "/worlds/nope/explode").status_code == 404


# ---- Start / stop / restart ----

def test_start_creates_hardened_container(logged_in, app, docker_fake, audit_path):
    create(logged_in)
    resp = post(logged_in, "/worlds/survival/start")
    assert resp.status_code == 302

    [container] = docker_fake.containers.created
    kw = container.kwargs
    assert kw["name"] == "mc-survival"
    assert kw["labels"]["mc-siem-lab.world"] == "survival"
    assert len(kw["labels"]["mc-siem-lab.config"]) == 16
    assert kw["network"] == "mclab"
    assert kw["ports"] == {"25565/tcp": ("127.0.0.1", 25565)}
    assert kw["volumes"] == {"/host/worlds/survival/data": {"bind": "/data", "mode": "rw"}}
    assert "25575/tcp" not in kw["ports"]
    assert kw["environment"]["ONLINE_MODE"] == "TRUE"
    assert container.status == "running"

    event = last_event(audit_path)
    assert (event["event"], event["world"], event["user"]) == ("server_start", "survival", "admin")


def test_stop_and_restart(logged_in, docker_fake, audit_path):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    post(logged_in, "/worlds/survival/restart")
    post(logged_in, "/worlds/survival/stop")
    container = docker_fake.containers.by_name["mc-survival"]
    assert container.calls == ["start", "restart", "stop"]
    assert [e["event"] for e in read_audit(audit_path)][-3:] == [
        "server_start", "server_restart", "server_stop"]


def test_foreign_container_left_alone(logged_in, docker_fake, audit_path):
    create(logged_in)
    impostor = docker_fake.containers.create("someone/else", name="mc-survival", labels={})
    post(logged_in, "/worlds/survival/stop")
    assert impostor.calls == []
    assert last_event(audit_path)["event"] == "world_created"  # no server_stop logged


def test_docker_unreachable_shows_error(app, logged_in, audit_path):
    from docker.errors import DockerException

    def broken():
        raise DockerException("socket missing")

    app.extensions["worlds"].containers._client_factory = broken
    create(logged_in)
    resp = post(logged_in, "/worlds/survival/start")
    assert resp.status_code == 302
    page = logged_in.get("/worlds/survival").get_data(as_text=True)
    assert "Cannot reach Docker" in page
    assert last_event(audit_path)["event"] == "world_created"


# ---- Settings ----

def test_settings_change_recreates_running_container(logged_in, app, docker_fake, audit_path):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    old = docker_fake.containers.by_name["mc-survival"]

    form = settings_form(world_json(app), difficulty="hard", motd="Hard mode")
    assert post(logged_in, "/worlds/survival/settings", form).status_code == 302

    assert world_json(app)["properties"]["difficulty"] == "hard"
    assert old.calls == ["start", "stop", "remove"]
    new = docker_fake.containers.by_name["mc-survival"]
    assert new is not old and new.status == "running"
    assert new.kwargs["environment"]["DIFFICULTY"] == "hard"

    event = last_event(audit_path)
    assert event["event"] == "world_settings_changed"
    assert event["world"] == "survival"
    assert event["changed"] == ["difficulty", "motd"]


def test_settings_change_on_crash_looping_container(logged_in, app, docker_fake):
    # Docker refuses to remove a "restarting" container; it must be stopped first.
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    old = docker_fake.containers.by_name["mc-survival"]
    old.status = "restarting"
    post(logged_in, "/worlds/survival/settings", settings_form(world_json(app), memory="3G"))
    assert old.calls[-2:] == ["stop", "remove"]
    new = docker_fake.containers.by_name["mc-survival"]
    assert new.status == "running"
    assert new.kwargs["environment"]["MEMORY"] == "3G"


def test_failed_rebuild_keeps_settings_and_next_start_rebuilds(logged_in, app, docker_fake, audit_path):
    from docker.errors import APIError

    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    old = docker_fake.containers.by_name["mc-survival"]

    def refuse():
        raise APIError("conflict")
    old.remove = refuse

    post(logged_in, "/worlds/survival/settings", settings_form(world_json(app), difficulty="hard"))
    page = logged_in.get("/worlds/survival").get_data(as_text=True)
    assert "rebuilt with the new settings on the next start" in page
    assert world_json(app)["properties"]["difficulty"] == "hard"
    assert last_event(audit_path)["event"] == "world_settings_changed"

    # The container still carries the old settings, so start replaces it.
    old.remove = lambda: setattr(old, "removed", True)
    post(logged_in, "/worlds/survival/start")
    new = docker_fake.containers.by_name["mc-survival"]
    assert new is not old
    assert new.kwargs["environment"]["DIFFICULTY"] == "hard"


def test_start_reuses_up_to_date_container(logged_in, docker_fake):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    post(logged_in, "/worlds/survival/stop")
    post(logged_in, "/worlds/survival/start")
    assert len(docker_fake.containers.created) == 1


def test_settings_on_stopped_world_stay_stopped(logged_in, app, docker_fake):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    post(logged_in, "/worlds/survival/stop")
    post(logged_in, "/worlds/survival/settings", settings_form(world_json(app), memory="4G"))
    assert docker_fake.containers.by_name["mc-survival"].status == "created"


def test_settings_before_first_start_just_saves(logged_in, app, docker_fake):
    create(logged_in)
    post(logged_in, "/worlds/survival/settings", settings_form(world_json(app), memory="4G"))
    assert world_json(app)["memory"] == "4G"
    assert docker_fake.containers.created == []


def test_invalid_settings_change_nothing(logged_in, app, audit_path):
    create(logged_in)
    before = world_json(app)
    post(logged_in, "/worlds/survival/settings", settings_form(before, memory="999G"))
    assert world_json(app) == before
    assert last_event(audit_path)["event"] == "world_created"


def test_unchanged_settings_not_audited(logged_in, app, audit_path):
    create(logged_in)
    post(logged_in, "/worlds/survival/settings", settings_form(world_json(app)))
    assert last_event(audit_path)["event"] == "world_created"


def test_settings_cannot_touch_rcon_password(logged_in, app):
    create(logged_in)
    world = world_json(app)
    form = settings_form(world, rcon_password="hunter2", name="other")
    post(logged_in, "/worlds/survival/settings", form)
    after = world_json(app)
    assert after["rcon_password"] == world["rcon_password"]
    assert after["name"] == "survival"


# ---- Whitelist ----

def test_whitelist_add_on_running_server_uses_rcon(logged_in, app, rcon_fake, audit_path):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    rcon_fake.replies["whitelist add"] = "Added Steve to the whitelist"

    post(logged_in, "/worlds/survival/whitelist/add", {"player": "Steve"})

    assert rcon_fake.commands[-1] == "whitelist add Steve"
    host, port, password = rcon_fake.connections[-1]
    assert (host, port) == ("mc-survival", 25575)
    assert password == world_json(app)["rcon_password"]
    assert world_json(app)["whitelist"] == ["Steve"]
    event = last_event(audit_path)
    assert (event["event"], event["world"], event["target"]) == ("whitelist_add", "survival", "Steve")


def test_whitelist_add_unknown_player_refused(logged_in, app, rcon_fake, audit_path):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    rcon_fake.replies["whitelist add"] = "That player does not exist"
    post(logged_in, "/worlds/survival/whitelist/add", {"player": "NoSuchGuy"})
    assert world_json(app)["whitelist"] == []
    assert last_event(audit_path)["event"] == "server_start"


def test_whitelist_add_server_not_answering(logged_in, app, rcon_fake):
    from mcdash.rcon import RconError

    create(logged_in)
    post(logged_in, "/worlds/survival/start")

    def refuse(*a):
        raise RconError("connection refused")
    rcon_fake.connect = refuse
    app.extensions["worlds"].rcon_factory = refuse
    post(logged_in, "/worlds/survival/whitelist/add", {"player": "Steve"})
    assert "may still be starting" in logged_in.get("/worlds/survival").get_data(as_text=True)
    assert world_json(app)["whitelist"] == []


def test_whitelist_add_when_stopped_saves_for_next_start(logged_in, app, rcon_fake, docker_fake):
    create(logged_in)
    post(logged_in, "/worlds/survival/whitelist/add", {"player": "Alex"})
    assert rcon_fake.commands == []
    assert world_json(app)["whitelist"] == ["Alex"]
    post(logged_in, "/worlds/survival/start")
    env = docker_fake.containers.by_name["mc-survival"].kwargs["environment"]
    assert env["WHITELIST"] == "Alex"


@pytest.mark.parametrize("player", ["ab", "Steve; op Evil", "x" * 17, "Steve\nop Evil"])
def test_whitelist_rejects_bad_names(logged_in, app, rcon_fake, player):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    post(logged_in, "/worlds/survival/whitelist/add", {"player": player})
    assert rcon_fake.commands == []
    assert world_json(app)["whitelist"] == []


def test_whitelist_remove_running_kicks(logged_in, app, rcon_fake, audit_path):
    create(logged_in)
    post(logged_in, "/worlds/survival/whitelist/add", {"player": "Steve"})
    post(logged_in, "/worlds/survival/start")
    post(logged_in, "/worlds/survival/whitelist/remove", {"player": "steve"})
    assert rcon_fake.commands[-2:] == ["whitelist remove Steve", "kick Steve Removed from the whitelist"]
    assert world_json(app)["whitelist"] == []
    event = last_event(audit_path)
    assert (event["event"], event["target"]) == ("whitelist_remove", "Steve")


def test_whitelist_remove_stopped_edits_whitelist_file(logged_in, app, tmp_path):
    create(logged_in)
    post(logged_in, "/worlds/survival/whitelist/add", {"player": "Steve"})
    wl = tmp_path / "worlds" / "survival" / "data" / "whitelist.json"
    wl.write_text(json.dumps([{"uuid": "x", "name": "Steve"}, {"uuid": "y", "name": "Alex"}]))
    post(logged_in, "/worlds/survival/whitelist/remove", {"player": "Steve"})
    assert [e["name"] for e in json.loads(wl.read_text())] == ["Alex"]


# ---- Players, backups, log ----

def test_online_players_listed(logged_in, rcon_fake):
    create(logged_in)
    post(logged_in, "/worlds/survival/start")
    rcon_fake.replies["list"] = "There are 2 of a max of 10 players online: Steve, Alex"
    page = logged_in.get("/worlds/survival").get_data(as_text=True)
    assert "Online: Steve, Alex" in page


def test_backup_of_running_world_pauses_saving(logged_in, app, rcon_fake, audit_path, tmp_path):
    create(logged_in)
    (tmp_path / "worlds" / "survival" / "data" / "world").mkdir()
    (tmp_path / "worlds" / "survival" / "data" / "world" / "level.dat").write_text("x")
    post(logged_in, "/worlds/survival/start")

    post(logged_in, "/worlds/survival/backup")

    assert rcon_fake.commands == ["save-off", "save-all flush", "save-on"]
    event = last_event(audit_path)
    assert event["event"] == "backup_created" and event["world"] == "survival"
    path = tmp_path / "backups" / "survival" / event["target"]
    with tarfile.open(path) as tar:
        assert "survival/world/level.dat" in tar.getnames()
    assert event["target"] in logged_in.get("/worlds/survival").get_data(as_text=True)


def test_backup_failure_audited_and_cleaned_up(logged_in, app, audit_path, tmp_path, monkeypatch):
    create(logged_in)

    def boom(*a, **k):
        raise OSError("No space left on device")

    monkeypatch.setattr("tarfile.TarFile.add", boom)
    post(logged_in, "/worlds/survival/backup")
    event = last_event(audit_path)
    assert event["event"] == "backup_failed"
    assert "No space left" in event["reason"]
    assert list((tmp_path / "backups" / "survival").iterdir()) == []


def test_log_tail_is_escaped(logged_in, tmp_path):
    create(logged_in)
    logs = tmp_path / "worlds" / "survival" / "data" / "logs"
    logs.mkdir()
    logs.joinpath("latest.log").write_text(
        "".join(f"[12:00:{i:02d}] line {i}\n" for i in range(300)) + "<script>alert(1)</script>\n")
    page = logged_in.get("/worlds/survival").get_data(as_text=True)
    assert "line 299" in page and "line 50\n" not in page
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;" in page
