"""Dashboard pages: the world list and each world's controls.

Every route needs a login, and every POST also needs a valid CSRF token
(CSRFProtect is applied app-wide in __init__.py). Every successful change
writes one audit line with the world's name, using the event names the Wazuh
rules in wazuh/rules/mc_dashboard_rules.xml match on.
"""

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .audit import audit
from .auth import login_required
from .rcon import RconError
from .service import ACTION_ERRORS, SettingsSavedError
from .worlds import (
    DIFFICULTIES,
    GAMEMODES,
    SERVER_TYPES,
    WorldError,
)

bp = Blueprint("main", __name__)


def service():
    return current_app.extensions["worlds"]


def load_or_404(name):
    try:
        return service().store.load(name)
    except WorldError:
        abort(404)


def error_message(e):
    if isinstance(e, RconError):
        return f"The server didn't answer on RCON, it may still be starting ({e})."
    return str(e)


def back_to(name):
    return redirect(url_for("main.world", name=name))


@bp.route("/")
@login_required
def index():
    svc = service()
    worlds = [dict(w, status=svc.containers.status(w["name"])) for w in svc.store.all()]
    return render_template("index.html", worlds=worlds)


@bp.route("/worlds", methods=["POST"])
@login_required
def create_world():
    name = request.form.get("name", "").strip().lower()
    config = current_app.config
    try:
        world = service().store.create(name, {
            "type": config["MC_DEFAULT_TYPE"],
            "version": config["MC_DEFAULT_VERSION"],
            "memory": config["MC_DEFAULT_MEMORY"],
            "base_port": config["MC_BASE_PORT"],
        })
    except ACTION_ERRORS as e:
        flash(str(e), "error")
        return redirect(url_for("main.index"))
    audit("world_created", user=session["user"], world=name, port=world["port"])
    flash(f"Created world {name} on port {world['port']}. Start it when you're ready.", "info")
    return back_to(name)


@bp.route("/worlds/<name>")
@login_required
def world(name):
    world = load_or_404(name)
    svc = service()
    return render_template(
        "world.html",
        world=world,
        status=svc.containers.status(name),
        players=svc.online_players(world),
        backups=svc.list_backups(name),
        log_lines=svc.log_tail(name),
        server_types=SERVER_TYPES,
        difficulties=DIFFICULTIES,
        gamemodes=GAMEMODES,
    )


# Button name -> (service method, audit event, past tense for the message)
LIFECYCLE = {
    "start": ("start", "server_start", "started"),
    "stop": ("stop", "server_stop", "stopped"),
    "restart": ("restart", "server_restart", "restarted"),
}


@bp.route("/worlds/<name>/<action>", methods=["POST"])
@login_required
def lifecycle(name, action):
    if action not in LIFECYCLE:
        abort(404)
    load_or_404(name)
    method, event, done = LIFECYCLE[action]
    try:
        getattr(service(), method)(name)
    except ACTION_ERRORS as e:
        flash(f"Could not {action} {name}: {e}", "error")
        return back_to(name)
    audit(event, user=session["user"], world=name)
    flash(f"{name} {done}.", "info")
    return back_to(name)


@bp.route("/worlds/<name>/settings", methods=["POST"])
@login_required
def settings(name):
    load_or_404(name)
    try:
        changed = service().update_settings(name, request.form)
    except SettingsSavedError as e:
        audit("world_settings_changed", user=session["user"], world=name, changed=e.changed)
        flash(f"Settings saved, but the server container couldn't be rebuilt ({e}). "
              "It will be rebuilt with the new settings on the next start.", "error")
        return back_to(name)
    except ACTION_ERRORS as e:
        flash(str(e), "error")
        return back_to(name)
    if not changed:
        flash("Nothing changed.", "info")
        return back_to(name)
    audit("world_settings_changed", user=session["user"], world=name, changed=changed)
    flash("Saved: " + ", ".join(changed) + ". The server container was rebuilt with the new settings.", "info")
    return back_to(name)


@bp.route("/worlds/<name>/whitelist/add", methods=["POST"])
@login_required
def whitelist_add(name):
    load_or_404(name)
    player = request.form.get("player", "").strip()
    try:
        service().whitelist_add(name, player)
    except ACTION_ERRORS as e:
        flash(error_message(e), "error")
        return back_to(name)
    audit("whitelist_add", user=session["user"], world=name, target=player)
    flash(f"Added {player} to the whitelist.", "info")
    return back_to(name)


@bp.route("/worlds/<name>/whitelist/remove", methods=["POST"])
@login_required
def whitelist_remove(name):
    load_or_404(name)
    player = request.form.get("player", "").strip()
    try:
        removed = service().whitelist_remove(name, player)
    except ACTION_ERRORS as e:
        flash(error_message(e), "error")
        return back_to(name)
    audit("whitelist_remove", user=session["user"], world=name, target=removed)
    flash(f"Removed {removed} from the whitelist.", "info")
    return back_to(name)


@bp.route("/worlds/<name>/backup", methods=["POST"])
@login_required
def backup(name):
    load_or_404(name)
    try:
        filename = service().backup(name)
    except ACTION_ERRORS as e:
        audit("backup_failed", user=session["user"], world=name, reason=str(e))
        flash(f"Backup failed: {error_message(e)}", "error")
        return back_to(name)
    audit("backup_created", user=session["user"], world=name, target=filename)
    flash(f"Backup saved as {filename}.", "info")
    return back_to(name)
