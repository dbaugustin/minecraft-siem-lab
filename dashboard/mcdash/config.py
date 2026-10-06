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

    # --- Worlds (see the README's "Worlds" section) ---
    # Paths as the dashboard sees them, and the worlds directory as the Docker
    # host sees it (bind mounts for world containers need host paths).
    WORLDS_DIR = os.environ.get("WORLDS_DIR", "worlds")
    HOST_WORLDS_DIR = os.environ.get("HOST_WORLDS_DIR") or os.path.abspath(WORLDS_DIR)
    BACKUP_DIR = os.environ.get("BACKUP_DIR", "backups")
    # Keep only the newest N backups per world (0 keeps all). Applies to
    # manual and scheduled backups alike.
    BACKUP_RETENTION = int(os.environ.get("BACKUP_RETENTION", "10"))
    # Running worlds are backed up automatically this often (0 turns it off).
    BACKUP_INTERVAL_HOURS = float(os.environ.get("BACKUP_INTERVAL_HOURS", "24"))
    MC_NETWORK = os.environ.get("MC_NETWORK", "mclab")
    MC_IMAGE = os.environ.get("MC_IMAGE", "itzg/minecraft-server:latest")
    # Host address each world's game port is published on. 127.0.0.1 keeps it
    # reachable only through the playit.gg agent running on the same box. Set
    # 0.0.0.0 only if friends should also join directly over the LAN.
    MC_GAME_BIND_IP = os.environ.get("MC_GAME_BIND_IP", "127.0.0.1")

    # Defaults for new worlds; each world can change them afterwards.
    MC_DEFAULT_TYPE = os.environ.get("MC_DEFAULT_TYPE", "SPIGOT")
    MC_DEFAULT_VERSION = os.environ.get("MC_DEFAULT_VERSION", "LATEST")
    MC_DEFAULT_MEMORY = os.environ.get("MC_DEFAULT_MEMORY", "2G")
    MC_BASE_PORT = int(os.environ.get("MC_BASE_PORT", "25565"))
