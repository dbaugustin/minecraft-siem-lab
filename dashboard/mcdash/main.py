"""Dashboard pages. Server controls (start/stop, RCON, backups) land here later."""

from flask import Blueprint, render_template, session

from .auth import login_required

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def index():
    return render_template("index.html", user=session["user"])
