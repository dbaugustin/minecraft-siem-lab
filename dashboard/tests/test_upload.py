"""World .zip upload: the safety checks in upload.py and the route."""

import io
import stat
import zipfile

import pytest

from conftest import csrf_token, read_audit
from mcdash.upload import UploadError, import_zip, plan


def make_zip(entries, symlinks=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        for name in symlinks:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    buf.seek(0)
    return buf


def planned(entries):
    with zipfile.ZipFile(make_zip(entries)) as zf:
        return plan(zf)


# ---- Finding the world ----

def test_plan_single_player_save():
    assert planned({"My World/level.dat": "x", "My World/region/r.0.0.mca": "x"}) == \
        [(("My World",), "world")]


def test_plan_level_dat_at_top():
    assert planned({"level.dat": "x", "region/r.0.0.mca": "x"}) == [((), "world")]


def test_plan_server_folder_with_nether_and_end():
    entries = {
        "srv/world/level.dat": "x", "srv/world_nether/level.dat": "x",
        "srv/world_the_end/level.dat": "x", "srv/server.properties": "x",
        "srv/world/DIM-1/level.dat": "nested, ignored",
    }
    assert planned(entries) == [
        (("srv", "world"), "world"),
        (("srv", "world_nether"), "world_nether"),
        (("srv", "world_the_end"), "world_the_end"),
    ]


def test_plan_ignores_macosx_metadata():
    assert planned({"w/level.dat": "x", "__MACOSX/w/level.dat": "x"}) == [(("w",), "world")]


@pytest.mark.parametrize("entries, message", [
    ({"readme.txt": "x"}, "No world found"),
    ({"a/level.dat": "x", "b/level.dat": "x"}, "more than one world"),
    ({"../evil/level.dat": "x"}, "outside its folder"),
    ({"w/level.dat": "x", "w/../../x": "x"}, "outside its folder"),
    ({"/etc/level.dat": "x"}, "absolute path"),
    ({"C:/level.dat": "x"}, "absolute path"),
    ({"w\\..\\..\\level.dat": "x"}, "outside its folder"),
])
def test_plan_rejects(entries, message):
    with pytest.raises(UploadError, match=message):
        planned(entries)


def test_plan_rejects_symlinks():
    with zipfile.ZipFile(make_zip({"w/level.dat": "x"}, symlinks=["w/link"])) as zf:
        with pytest.raises(UploadError, match="symlink"):
            plan(zf)


# ---- Extracting ----

def test_import_moves_old_world_aside(tmp_path):
    data = tmp_path / "survival" / "data"
    (data / "world").mkdir(parents=True)
    (data / "world" / "old.txt").write_text("old")
    (data / "world_nether").mkdir()
    trash = tmp_path / ".deleted"
    zf = make_zip({"save/level.dat": "new", "save/region/r.0.0.mca": "abc", "save/server.properties": "x"})
    size, moved = import_zip(zf, "survival", str(data), str(trash), "stamp", 10_000)
    assert (data / "world" / "level.dat").read_text() == "new"
    assert (data / "world" / "region" / "r.0.0.mca").read_text() == "abc"
    assert not (data / "world_nether").exists()
    assert sorted(moved) == ["survival-world-stamp", "survival-world_nether-stamp"]
    assert (trash / "survival-world-stamp" / "old.txt").read_text() == "old"
    assert size == len("new") + len("abc") + 1
    assert [p.name for p in data.iterdir() if p.name.startswith(".upload")] == []


def test_import_stops_zip_bombs_and_changes_nothing(tmp_path):
    data = tmp_path / "survival" / "data"
    (data / "world").mkdir(parents=True)
    (data / "world" / "level.dat").write_text("keep")
    zf = make_zip({"w/level.dat": "x", "w/big": "0" * 5000})
    with pytest.raises(UploadError, match="over the limit"):
        import_zip(zf, "survival", str(data), str(tmp_path / ".deleted"), "stamp", 1000)
    assert (data / "world" / "level.dat").read_text() == "keep"
    assert sorted(p.name for p in data.iterdir()) == ["world"]


def test_import_rejects_non_zip(tmp_path):
    with pytest.raises(UploadError, match="valid .zip"):
        import_zip(io.BytesIO(b"not a zip"), "s", str(tmp_path), str(tmp_path / "t"), "s", 1000)


# ---- Route ----

def upload(client, data, filename="world.zip", name="survival"):
    return client.post(f"/worlds/{name}/upload", data={
        "csrf_token": csrf_token(client, "/"),
        "world": (data, filename),
    }, content_type="multipart/form-data")


@pytest.fixture
def world(logged_in):
    logged_in.post("/worlds", data={"csrf_token": csrf_token(logged_in, "/"), "name": "survival"})
    return logged_in


def test_upload_route(world, tmp_path, audit_path):
    resp = upload(world, make_zip({"My World/level.dat": "x"}), "My World.zip")
    assert resp.status_code == 302
    assert (tmp_path / "worlds" / "survival" / "data" / "world" / "level.dat").exists()
    event = read_audit(audit_path)[-1]
    assert (event["event"], event["world"], event["target"], event["user"]) == \
        ("world_uploaded", "survival", "My World.zip", "admin")
    assert "Replace this world" in world.get("/worlds/survival").get_data(as_text=True)


def test_upload_rejected_is_audited(world, tmp_path, audit_path):
    upload(world, make_zip({"../x/level.dat": "x"}))
    event = read_audit(audit_path)[-1]
    assert event["event"] == "world_upload_rejected"
    assert "outside" in event["reason"]
    assert not (tmp_path / "worlds" / "survival" / "data" / "world").exists()


def test_upload_needs_zip_name(world, audit_path):
    upload(world, io.BytesIO(b"x"), "world.tar.gz")
    assert read_audit(audit_path)[-1]["reason"] == "not a .zip"


def test_upload_refused_while_running(world, tmp_path):
    world.post("/worlds/survival/start", data={"csrf_token": csrf_token(world, "/")})
    upload(world, make_zip({"w/level.dat": "x"}))
    assert not (tmp_path / "worlds" / "survival" / "data" / "world").exists()


def test_upload_too_large(logged_in, app, audit_path):
    app.config["MAX_CONTENT_LENGTH"] = 1000
    token = csrf_token(logged_in, "/")
    resp = logged_in.post("/worlds/survival/upload", data={
        "csrf_token": token, "world": (io.BytesIO(b"0" * 5000), "w.zip"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 413
    event = read_audit(audit_path)[-1]
    assert (event["event"], event["reason"]) == ("world_upload_rejected", "too_large")


def test_upload_needs_csrf(world, tmp_path):
    resp = world.post("/worlds/survival/upload", data={"world": (make_zip({"w/level.dat": "x"}), "w.zip")},
                      content_type="multipart/form-data")
    assert resp.status_code == 400
    assert not (tmp_path / "worlds" / "survival" / "data" / "world").exists()
