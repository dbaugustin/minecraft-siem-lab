"""Login, logout, and the login_required decorator."""

import hmac
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, Length

from .audit import audit

bp = Blueprint("auth", __name__)

# argon2-cffi's defaults follow RFC 9106's recommended argon2id parameters.
_hasher = PasswordHasher()

# Verified against when the username is wrong, so a bad username costs the
# same argon2 work as a bad password and response timing doesn't reveal which
# one was wrong.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")

GENERIC_ERROR = "Invalid username or password."


class LoginForm(FlaskForm):
    # FlaskForm adds a hidden csrf_token field and validates it on submit.
    username = StringField("Username", validators=[DataRequired(), Length(max=64)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=256)])


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _check_credentials(username, password):
    """Return (ok, reason). Always runs one argon2 verify, whatever the input."""
    config = current_app.config
    username_ok = hmac.compare_digest(
        username.encode(), config["ADMIN_USERNAME"].encode()
    )
    stored = config["ADMIN_PASSWORD_HASH"] if username_ok else _DUMMY_HASH
    try:
        _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False, "bad_password" if username_ok else "unknown_user"
    if not username_ok:
        return False, "unknown_user"
    return True, None


def _safe_next(target):
    # Only follow relative paths on this site, never "//evil.example" or a
    # full URL, so the login page can't be used as an open redirect.
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.index")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        ip = request.remote_addr
        limiter = current_app.extensions["login_limiter"]

        remaining = limiter.seconds_locked(username, ip)
        if remaining:
            audit("login_blocked", user=username, reason="locked_out",
                  lockout_remaining_s=remaining)
            flash("Too many failed attempts. Try again later.", "error")
            return render_template("login.html", form=form), 429

        ok, reason = _check_credentials(username, form.password.data)
        if not ok:
            audit("login_failure", user=username, reason=reason)
            if limiter.record_failure(username, ip):
                audit("account_locked", user=username,
                      threshold=limiter.threshold,
                      lockout_duration_s=limiter.duration)
            flash(GENERIC_ERROR, "error")
            return render_template("login.html", form=form), 401

        limiter.record_success(username, ip)
        # Drop any pre-login session data (session fixation) and start fresh.
        session.clear()
        session.permanent = True
        session["user"] = username
        audit("login_success", user=username)
        return redirect(_safe_next(request.args.get("next")))

    if request.method == "POST":
        audit("login_invalid_form", errors=sorted(form.errors))
        return render_template("login.html", form=form), 400

    return render_template("login.html", form=form)


@bp.route("/logout", methods=["POST"])
def logout():
    # POST-only, and CSRFProtect checks the token, so another site can't log
    # you out with a link or hidden form.
    user = session.get("user")
    session.clear()
    if user:
        audit("logout", user=user)
    return redirect(url_for("auth.login"))
