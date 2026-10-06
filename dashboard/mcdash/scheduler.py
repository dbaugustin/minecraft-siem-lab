"""Scheduled backups: every running world is backed up every BACKUP_INTERVAL_HOURS.

A daemon thread wakes every few minutes and backs up each running world whose
newest backup (manual or scheduled) is older than the interval, then deletes
all but its newest BACKUP_RETENTION backups. Because "due" is worked out from
the backup files themselves, a dashboard restart doesn't reset the schedule.

Stopped worlds are skipped: their data can't change, so another copy would
only push an older, different backup out of the retention window.

gunicorn runs one worker (see the Dockerfile), so there is exactly one
scheduler. Each run writes the same audit events as the manual button, with
user "scheduler".
"""

import logging
import threading
import time

from .audit import audit
from .service import ACTION_ERRORS, WorldBusyError

log = logging.getLogger(__name__)

USER = "scheduler"
# How often the thread checks whether anything is due.
CHECK_EVERY = 300
# After a failed scheduled backup, wait this long before trying that world
# again, so a full disk raises one alert an hour rather than one every check.
RETRY_AFTER = 3600


class BackupScheduler:
    def __init__(self, app, interval_hours, retention):
        self.app = app
        self.interval = interval_hours * 3600
        self.retention = retention
        self._last_failure = {}
        self._stop = threading.Event()
        self._thread = None

    @property
    def service(self):
        return self.app.extensions["worlds"]

    def due(self, name, now):
        failed = self._last_failure.get(name)
        if failed is not None and now - failed < RETRY_AFTER:
            return False
        newest = self.service.newest_backup_time(name)
        return newest is None or now - newest >= self.interval

    def run_once(self, now=None):
        """Back up every running world that is due. Returns {world: outcome}."""
        now = time.time() if now is None else now
        svc = self.service
        outcomes = {}
        with self.app.app_context():
            for name in svc.store.names():
                if not svc.is_running(name) or not self.due(name, now):
                    continue
                outcomes[name] = self._backup(name, now)
        return outcomes

    def _backup(self, name, now):
        svc = self.service
        try:
            filename = svc.backup(name)
        except WorldBusyError:
            return "busy"  # someone is using the world; try on the next check
        except ACTION_ERRORS as e:
            self._last_failure[name] = now
            audit("backup_failed", user=USER, world=name, reason=str(e))
            return "failed"
        self._last_failure.pop(name, None)
        audit("backup_created", user=USER, world=name, target=filename)
        for old in svc.prune_backups(name, self.retention):
            audit("backup_pruned", user=USER, world=name, target=old)
        return "created"

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="backup-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(CHECK_EVERY):
            try:
                self.run_once()
            except Exception:
                # Never let one bad run kill the thread for good.
                log.exception("Scheduled backup run failed")
