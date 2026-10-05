import os
import stat

import pytest

from mcdash.worlds import WorldError, WorldStore, container_env, parse_settings

DEFAULTS = {"type": "VANILLA", "version": "LATEST", "memory": "2G", "base_port": 25565}


@pytest.fixture
def store(tmp_path):
    return WorldStore(str(tmp_path))


def settings_form(world, **changes):
    form = {
        "type": world["type"], "version": world["version"], "memory": world["memory"],
        "port": str(world["port"]),
    }
    for key, value in world["properties"].items():
        if isinstance(value, bool):
            if value:
                form[key] = "on"
        else:
            form[key] = str(value)
    for key, value in changes.items():
        if value is None:
            form.pop(key, None)
        else:
            form[key] = value
    return form


def test_create_writes_world_json_and_data_dir(store, tmp_path):
    world = store.create("survival", DEFAULTS)
    assert (tmp_path / "survival" / "data").is_dir()
    assert store.load("survival") == world
    assert world["port"] == 25565
    assert len(world["rcon_password"]) >= 40
    mode = stat.S_IMODE(os.stat(tmp_path / "survival" / "world.json").st_mode)
    assert mode == 0o600


def test_each_world_gets_next_free_port_and_own_password(store):
    a = store.create("a", DEFAULTS)
    b = store.create("b", DEFAULTS)
    assert (a["port"], b["port"]) == (25565, 25566)
    assert a["rcon_password"] != b["rcon_password"]


@pytest.mark.parametrize("name", ["", "Survival", "../etc", "a/b", "-x", "a" * 33, "with space"])
def test_bad_names_rejected(store, name):
    with pytest.raises(WorldError):
        store.create(name, DEFAULTS)


def test_duplicate_name_rejected(store):
    store.create("survival", DEFAULTS)
    with pytest.raises(WorldError):
        store.create("survival", DEFAULTS)


def test_load_rejects_path_tricks(store):
    with pytest.raises(WorldError):
        store.load("../../etc")


def test_parse_settings_reports_changed_keys(store):
    world = store.create("survival", DEFAULTS)
    form = settings_form(world, difficulty="hard", motd="New MOTD", version="1.21.1")
    updated, changed = parse_settings(form, world, other_ports=set())
    assert changed == ["version", "difficulty", "motd"]
    assert updated["properties"]["difficulty"] == "hard"
    assert updated["rcon_password"] == world["rcon_password"]
    # The original dict is untouched.
    assert world["properties"]["difficulty"] == "normal"


def test_parse_settings_no_change(store):
    world = store.create("survival", DEFAULTS)
    assert parse_settings(settings_form(world), world, set())[1] == []


def test_unchecked_checkbox_turns_bool_off(store):
    world = store.create("survival", DEFAULTS)
    updated, changed = parse_settings(settings_form(world, pvp=None), world, set())
    assert updated["properties"]["pvp"] is False
    assert changed == ["pvp"]


@pytest.mark.parametrize("field,value", [
    ("type", "BUKKIT_BUT_NOT"),
    ("version", "1.21; rm -rf /"),
    ("memory", "64G"),
    ("memory", "lots"),
    ("port", "25575"),
    ("port", "80"),
    ("difficulty", "nightmare"),
    ("max-players", "1000"),
    ("view-distance", "abc"),
    ("motd", "line one\nline two"),
    ("motd", ""),
])
def test_parse_settings_rejects_bad_values(store, field, value):
    world = store.create("survival", DEFAULTS)
    with pytest.raises(WorldError):
        parse_settings(settings_form(world, **{field: value}), world, set())


def test_port_clash_with_other_world_rejected(store):
    world = store.create("survival", DEFAULTS)
    with pytest.raises(WorldError, match="already used"):
        parse_settings(settings_form(world, port="25570"), world, other_ports={25570})


def test_container_env_forces_hardening(store):
    world = store.create("survival", DEFAULTS)
    world["whitelist"] = ["Steve", "Alex"]
    env = container_env(world)
    assert env["ONLINE_MODE"] == "TRUE"
    assert env["ENFORCE_WHITELIST"] == "TRUE"
    assert env["ENABLE_RCON"] == "TRUE"
    assert env["RCON_PASSWORD"] == world["rcon_password"]
    assert env["WHITELIST"] == "Steve,Alex"
    assert env["EXISTING_WHITELIST_FILE"] == "SYNCHRONIZE"
    assert env["DIFFICULTY"] == "normal"
    assert env["PVP"] == "true"
    assert "OPS" not in env  # empty list is left out
