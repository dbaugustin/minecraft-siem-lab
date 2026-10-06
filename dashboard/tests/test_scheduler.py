"""Scheduled backups and retention, with Docker and RCON faked (see conftest)."""

import os
import time

from conftest import post, read_audit


def scheduler(app):
    return app.extensions["backup_scheduler"]


def make_world(logged_in, name="survival", start=True):
    post(logged_in, "/worlds", {"name": name})
    if start:
        post(logged_in, f"/worlds/{name}/start")


def backups(tmp_path, name="survival"):
    directory = tmp_path / "backups" / name
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


def fake_backups(tmp_path, count, name="survival", age_hours=0):
    """Write `count` backup files with increasing timestamps in their names."""
    directory = tmp_path / "backups" / name
    directory.mkdir(parents=True, exist_ok=True)
    mtime = time.time() - age_hours * 3600
    for i in range(count):
        path = directory / f"{name}-2026-01-{i + 1:02d}T00-00-00.tar.gz"
        path.write_bytes(b"old")
        os.utime(path, (mtime, mtime))


def test_not_started_in_tests(app):
    assert scheduler(app)._thread is None


def test_running_world_without_backups_is_backed_up(logged_in, app, tmp_path, audit_path):
    make_world(logged_in)
    assert scheduler(app).run_once() == {"survival": "created"}
    assert len(backups(tmp_path)) == 1
    event = read_audit(audit_path)[-1]
    assert (event["event"], event["user"], event["world"]) == ("backup_created", "scheduler", "survival")
    assert event["src_ip"] is None


def test_stopped_world_skipped(logged_in, app, tmp_path):
    make_world(logged_in, start=False)
    assert scheduler(app).run_once() == {}
    assert backups(tmp_path) == []


def test_recent_backup_means_not_due(logged_in, app, tmp_path):
    make_world(logged_in)
    fake_backups(tmp_path, 1, age_hours=23)  # interval is 24h by default
    assert scheduler(app).run_once() == {}
    assert scheduler(app).run_once(now=time.time() + 3600) == {"survival": "created"}


def test_retention_prunes_oldest(logged_in, app, tmp_path, audit_path):
    app.config["BACKUP_RETENTION"] = 3
    scheduler(app).retention = 3
    make_world(logged_in)
    fake_backups(tmp_path, 4, age_hours=48)
    scheduler(app).run_once()
    kept = backups(tmp_path)
    assert len(kept) == 3
    assert "survival-2026-01-01T00-00-00.tar.gz" not in kept
    assert "survival-2026-01-02T00-00-00.tar.gz" not in kept
    pruned = [e["target"] for e in read_audit(audit_path) if e["event"] == "backup_pruned"]
    assert pruned == ["survival-2026-01-02T00-00-00.tar.gz", "survival-2026-01-01T00-00-00.tar.gz"]


def test_manual_backup_also_prunes(logged_in, app, tmp_path, audit_path):
    app.config["BACKUP_RETENTION"] = 2
    make_world(logged_in, start=False)
    fake_backups(tmp_path, 3)
    resp = post(logged_in, "/worlds/survival/backup")
    assert len(backups(tmp_path)) == 2
    assert [e["user"] for e in read_audit(audit_path) if e["event"] == "backup_pruned"] == ["admin"] * 2
    page = logged_in.get(resp.headers["Location"]).get_data(as_text=True)
    assert "Deleted 2 older backup(s)" in page


def test_retention_zero_keeps_everything(logged_in, app, tmp_path):
    app.config["BACKUP_RETENTION"] = 0
    make_world(logged_in, start=False)
    fake_backups(tmp_path, 12)
    post(logged_in, "/worlds/survival/backup")
    assert len(backups(tmp_path)) == 13


def test_failure_audited_once_then_backs_off(logged_in, app, tmp_path, audit_path, monkeypatch):
    make_world(logged_in)

    def boom(*a, **k):
        raise OSError("No space left on device")

    monkeypatch.setattr("tarfile.TarFile.add", boom)
    now = time.time()
    assert scheduler(app).run_once(now) == {"survival": "failed"}
    assert scheduler(app).run_once(now + 300) == {}  # no retry yet, no repeat alert
    failures = [e for e in read_audit(audit_path) if e["event"] == "backup_failed"]
    assert len(failures) == 1 and failures[0]["user"] == "scheduler"
    monkeypatch.undo()
    assert scheduler(app).run_once(now + 3600) == {"survival": "created"}


def test_busy_world_retried_without_alert(logged_in, app, audit_path, monkeypatch):
    from mcdash.service import WorldBusyError

    make_world(logged_in)
    svc = app.extensions["worlds"]

    def busy(name):
        raise WorldBusyError("busy")

    monkeypatch.setattr(svc, "backup", busy)
    now = time.time()
    assert scheduler(app).run_once(now) == {"survival": "busy"}
    assert not any(e["event"] == "backup_failed" for e in read_audit(audit_path))
    monkeypatch.undo()
    assert scheduler(app).run_once(now + 300) == {"survival": "created"}  # no back-off


def test_each_world_on_its_own(logged_in, app, tmp_path):
    make_world(logged_in, "survival")
    make_world(logged_in, "creative", start=False)
    make_world(logged_in, "skyblock")
    assert scheduler(app).run_once() == {"skyblock": "created", "survival": "created"}
