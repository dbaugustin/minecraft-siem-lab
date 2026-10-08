"""Flask application factory for the Minecraft management dashboard."""

from flask import Flask, render_template, request, session
from flask_wtf.csrf import CSRFError, CSRFProtect

from .audit import audit
from .config import Config
from .containers import WorldContainers, default_client_factory
from .lockout import LoginLimiter
from .rcon import Rcon
from .scheduler import BackupScheduler
from .service import WorldService
from .worlds import WorldStore

csrf = CSRFProtect()


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    # Fail fast on missing secrets instead of running with an insecure default.
    missing = [k for k in ("SECRET_KEY", "ADMIN_PASSWORD_HASH") if not app.config.get(k)]
    if missing:
        raise RuntimeError(
            "Missing required config: "
            + ", ".join(missing)
            + ". Set FLASK_SECRET_KEY and DASHBOARD_ADMIN_PASSWORD_HASH in .env."
        )

    # .env.example ships placeholder values; refuse to sign sessions with one.
    if app.config["SECRET_KEY"] == "change-me" or len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError(
            "FLASK_SECRET_KEY is a placeholder or too short. Generate one with: "
            'python3 -c "import secrets; print(secrets.token_hex(32))"'
        )

    # Flask answers 413 to any request body bigger than this, before reading it.
    app.config["MAX_CONTENT_LENGTH"] = app.config["WORLD_UPLOAD_MAX_MB"] * 1024 * 1024

    # Every POST/PUT/PATCH/DELETE needs a valid CSRF token, including the
    # world-control routes, not just the login form.
    csrf.init_app(app)

    app.extensions["login_limiter"] = LoginLimiter(
        threshold=app.config["LOCKOUT_THRESHOLD"],
        window=app.config["LOCKOUT_WINDOW"],
        duration=app.config["LOCKOUT_DURATION"],
    )

    # Tests swap these for fakes through config_overrides.
    app.extensions["worlds"] = WorldService(
        store=WorldStore(app.config["WORLDS_DIR"]),
        containers=WorldContainers(
            client_factory=app.config.get("DOCKER_CLIENT_FACTORY", default_client_factory),
            image=app.config["MC_IMAGE"],
            network=app.config["MC_NETWORK"],
            host_worlds_dir=app.config["HOST_WORLDS_DIR"],
            game_bind_ip=app.config["MC_GAME_BIND_IP"],
        ),
        rcon_factory=app.config.get("RCON_FACTORY", Rcon),
        backup_dir=app.config["BACKUP_DIR"],
    )

    scheduler = BackupScheduler(
        app,
        interval_hours=app.config["BACKUP_INTERVAL_HOURS"],
        retention=app.config["BACKUP_RETENTION"],
    )
    app.extensions["backup_scheduler"] = scheduler
    # Tests drive the scheduler by calling run_once() themselves.
    if app.config["BACKUP_INTERVAL_HOURS"] > 0 and not app.testing:
        scheduler.start()

    from . import auth, main

    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)

    @app.errorhandler(413)
    def handle_too_large(e):
        world = (request.view_args or {}).get("name")
        audit("world_upload_rejected", user=session.get("user"), world=world, reason="too_large")
        return render_template(
            "error.html",
            message=f"That upload is over the {app.config['WORLD_UPLOAD_MAX_MB']} MB limit "
                    "(WORLD_UPLOAD_MAX_MB in .env).",
        ), 413

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        audit("csrf_failure", reason=e.description)
        return render_template("error.html", message="Your form expired. Go back and try again."), 400

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'"
        )
        return response

    return app
