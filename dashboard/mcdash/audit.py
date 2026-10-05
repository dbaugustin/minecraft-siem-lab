"""Auth/audit log written as JSON lines for Wazuh.

Every line is one self-contained JSON object, for example:

    {"timestamp": "2026-10-05T14:50:01.123456+00:00", "app": "mc-dashboard",
     "event": "login_failure", "user": "admin", "src_ip": "127.0.0.1",
     "reason": "bad_password"}

Wazuh's built-in JSON decoder parses each line into fields, so custom rules
can match on `event`, `user`, `src_ip` and so on. The fixed "app" field gives
those rules something to anchor on so they only fire for this dashboard.
"""

import json
import os
import threading
from datetime import datetime, timezone

from flask import current_app, request

APP_NAME = "mc-dashboard"

# Flask's dev server handles requests in threads; the lock keeps two writes
# from interleaving into one corrupted line.
_write_lock = threading.Lock()


def _client_ip():
    # No reverse proxy sits in front of the dashboard, so remote_addr is the
    # real client. X-Forwarded-For is deliberately ignored: it is client
    # controlled and would let anyone forge the IP recorded here.
    return request.remote_addr if request else None


def audit(event, user=None, **details):
    """Append one audit event. `details` become extra top-level fields."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app": APP_NAME,
        "event": event,
        "user": user,
        "src_ip": _client_ip(),
    }
    record.update(details)
    line = json.dumps(record, separators=(", ", ": "))

    path = current_app.config["AUDIT_LOG_PATH"]
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with _write_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
