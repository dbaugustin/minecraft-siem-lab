"""Configuration, read from environment variables.

Nothing secret lives in code. Locally these come from a `.env` file that is
excluded from git (see the repo-level .env.example).
"""

import os
from datetime import timedelta


class Config:
    # Signs the session cookie and CSRF tokens. Required: the app refuses to
    # start without it rather than falling back to a guessable default.
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")

    # Single admin account. The password is stored only as an argon2 hash,
    # generated with `python scripts/hash_password.py`.
    ADMIN_USERNAME = os.environ.get("DASHBOARD_ADMIN_USER", "admin")
    ADMIN_PASSWORD_HASH = os.environ.get("DASHBOARD_ADMIN_PASSWORD_HASH")

    # JSON-lines audit log that the Wazuh agent tails via a <localfile> entry.
    AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "logs/audit.jsonl")

    # Lockout: after LOCKOUT_THRESHOLD failures inside LOCKOUT_WINDOW seconds,
    # the username/IP pair is refused for LOCKOUT_DURATION seconds.
    LOCKOUT_THRESHOLD = int(os.environ.get("DASHBOARD_LOCKOUT_THRESHOLD", "5"))
    LOCKOUT_WINDOW = int(os.environ.get("DASHBOARD_LOCKOUT_WINDOW", "900"))
    LOCKOUT_DURATION = int(os.environ.get("DASHBOARD_LOCKOUT_DURATION", "900"))

    # Session cookie hardening. Secure is off because the dashboard is served
    # over plain HTTP on localhost only; a Secure cookie would never be sent.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Strict"
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Flask-WTF CSRF tokens expire with the session rather than after 1 hour.
    WTF_CSRF_TIME_LIMIT = None
