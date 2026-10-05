"""Dashboard pages.

Server controls (start/stop, RCON, backups, world settings) land here later.
The dashboard manages several worlds, each its own server container, so those
routes will be keyed by world name: /worlds/<world>/start, and so on.
"""

from flask import Blueprint, render_template, session

from .auth import login_required

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def index():
    return render_template("index.html", user=session["user"])
