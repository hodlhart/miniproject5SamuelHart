# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""Registration, login and logout."""

import functools
import sqlite3

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from .db import get_db

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/")
def picker():
    """Render the reader list, where a kid starts reading without a password."""
    readers = get_db().execute(
        "SELECT id, username FROM users"
        " WHERE role = 'kid' ORDER BY username COLLATE NOCASE"
    ).fetchall()
    return render_template("auth/picker.html", readers=readers)


@bp.route("/read-as/<int:user_id>", methods=("POST",))
def read_as(user_id):
    """Start a reader's session. No password, which is the point of the app."""
    # Scoped to role = 'kid' inside the query itself, so this route can never be
    # used to walk into a parent account and skip the password: the row is simply
    # not found. POST only, so a stray image tag on another page cannot sign
    # someone in as a kid either.
    reader = get_db().execute(
        "SELECT id, username FROM users WHERE id = ? AND role = 'kid'", (user_id,)
    ).fetchone()

    if reader is None:
        flash("That reader does not exist.", "danger")
        return redirect(url_for("auth.picker"))

    session.clear()
    session["user_id"] = reader["id"]
    flash(f"Reading as {reader['username']}.", "success")
    return redirect(url_for("wallet.index"))


@bp.route("/register", methods=("GET", "POST"))
def register():
    """Add a reader account, which takes a name and no password at all."""
    if request.method == "POST":
        # .get() rather than ["username"] so a hand-made POST missing a field
        # lands on the validation branch instead of raising KeyError.
        username = request.form.get("username", "")
        db = get_db()
        error = None

        if not username:
            error = "A name is required."
        else:
            # The friendly path: one cheap SELECT so the ordinary duplicate gets
            # a message instead of an exception. This alone cannot be trusted,
            # because two requests can pass it at the same instant.
            taken = db.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if taken is not None:
                error = f"{username} is already a reader."

        if error is None:
            try:
                # Both the role and the absent password are hardcoded and never
                # read from the form: a posted role=parent would otherwise be
                # trusted, and that hands the shop to any kid who edits the HTML.
                # The schema's CHECK insists on exactly this pair.
                db.execute(
                    "INSERT INTO users (username, password_hash, role)"
                    " VALUES (?, NULL, 'kid')",
                    (username,),
                )
                db.commit()
            except sqlite3.IntegrityError:
                # The race the SELECT above cannot cover: a second request
                # inserted this name between the check and this INSERT, so the
                # UNIQUE constraint rejected it. Reported as the same message the
                # check produces, not as a traceback.
                db.rollback()
                error = f"{username} is already a reader."
            else:
                flash(f"Added {username}. Pick their name to start reading.", "success")
                return redirect(url_for("auth.picker"))

        flash(error, "danger")

    return render_template("auth/register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    """Sign the admin in with a username and password."""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        db = get_db()
        error = None

        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        # One message for both failures would be the usual habit, but this app
        # has a parent-facing side, so a bad password should not read as if the
        # username were unknown when it was not.
        if user is None:
            error = "Incorrect username."
        elif user["password_hash"] is None:
            # A reader row carries no password at all, so this form can never
            # sign one in. check_password_hash would raise on None rather than
            # answer no, so this branch has to come first.
            error = "That is a reader. Pick the name from the reader list."
        elif not check_password_hash(user["password_hash"], password):
            error = "Incorrect password."

        if error is None:
            # Cleared first so a session id cannot survive a login, which is
            # what stops a fixed session being reused after signing in.
            session.clear()
            session["user_id"] = user["id"]
            # Parents land on the shop, which is their side of the app; the
            # wallet belongs to the kids.
            return redirect(url_for("shop.index"))

        flash(error, "danger")

    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    """Clear the session and send the user back to the login page."""
    session.clear()
    return redirect(url_for("auth.login"))


@bp.before_app_request
def load_logged_in_user():
    """Put the signed-in user's row on g.user, or None when signed out."""
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def login_required(view):
    """Wrap a view so it redirects to the login page when g.user is None."""

    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(**kwargs)

    return wrapped_view


def parent_required(view):
    """Wrap a view so only a signed-in parent may reach it."""

    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        if g.user["role"] != "parent":
            # A message and a redirect rather than a bare 403, so a kid who types
            # the URL is told why. The check runs before the view does, so add,
            # manage and toggle are out of reach by GET and POST alike, which is
            # what stops a crafted form from skipping the page.
            flash("That part of the shop is for parents.", "danger")
            return redirect(url_for("shop.index"))
        return view(**kwargs)

    return wrapped_view
