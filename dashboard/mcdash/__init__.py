"""Flask application factory for the Minecraft management dashboard."""

from flask import Flask, render_template
from flask_wtf.csrf import CSRFError, CSRFProtect

from .audit import audit
from .config import Config
from .lockout import LoginLimiter

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

    # Every POST/PUT/PATCH/DELETE needs a valid CSRF token, including the
    # server-control routes added later, not just the login form.
    csrf.init_app(app)

    app.extensions["login_limiter"] = LoginLimiter(
        threshold=app.config["LOCKOUT_THRESHOLD"],
        window=app.config["LOCKOUT_WINDOW"],
        duration=app.config["LOCKOUT_DURATION"],
    )

    from . import auth, main

    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)

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
