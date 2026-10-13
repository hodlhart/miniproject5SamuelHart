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
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/register", methods=("GET", "POST"))
def register():
    """Create a kid account from the form, or render the form."""
    if request.method == "POST":
        # .get() rather than ["username"] so a hand-made POST missing a field
        # lands on the validation branch instead of raising KeyError.
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        db = get_db()
        error = None

        if not username:
            error = "Username is required."
        elif not password:
            error = "Password is required."
        else:
            # The friendly path: one cheap SELECT so the ordinary duplicate gets
            # a message instead of an exception. This alone cannot be trusted,
            # because two requests can pass it at the same instant.
            taken = db.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if taken is not None:
                error = f"User {username} is already registered."

        if error is None:
            try:
                db.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    # role is hardcoded, never read from the form. A posted
                    # role=parent would otherwise be trusted, and that hands the
                    # shop management page to any kid who edits the HTML.
                    (username, generate_password_hash(password), "kid"),
                )
                db.commit()
            except sqlite3.IntegrityError:
                # The race the SELECT above cannot cover: a second request
                # inserted this username between the check and this INSERT, so
                # the UNIQUE constraint rejected it. Reported as the same
                # message the check produces, not as a traceback.
                db.rollback()
                error = f"User {username} is already registered."
            else:
                return redirect(url_for("auth.login"))

        flash(error, "danger")

    return render_template("auth/register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    """Log a user in, or render the login form."""
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
        elif not check_password_hash(user["password_hash"], password):
            error = "Incorrect password."

        if error is None:
            # Cleared first so a session id cannot survive a login, which is
            # what stops a fixed session being reused after signing in.
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("wallet.index"))

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
