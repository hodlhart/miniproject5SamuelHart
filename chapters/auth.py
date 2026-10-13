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


def login_required(view):
    """Wrap a view so a signed-out visitor is sent to the reader list."""

    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            # The picker, not the parent's password form. This one line is what
            # puts the reader list on every kid page for someone signed out: a
            # kid cannot use a username and password box, and the app should open
            # on the reader list rather than on a login they cannot fill in.
            return redirect(url_for("auth.picker"))
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
            # the URL is told why. The check runs before the view does, so the
            # stock pages and the reader pages are out of reach by GET and POST
            # alike, which is what stops a crafted form from skipping the page.
            # Said as "the app" rather than "the shop", because the readers page
            # and registration are parent-only too and neither is the shop.
            flash("That part of the app is for parents.", "danger")
            return redirect(url_for("shop.index"))
        return view(**kwargs)

    return wrapped_view



@bp.route("/")
def picker():
    """Render the reader list, where a kid starts reading without a password."""
    # Only readers who are still on the list. A removed one leaves the front door
    # at once, without anything being deleted.
    readers = get_db().execute(
        "SELECT id, username FROM users"
        " WHERE role = 'kid' AND removed_at IS NULL ORDER BY username COLLATE NOCASE"
    ).fetchall()
    return render_template("auth/picker.html", readers=readers)


@bp.route("/read-as/<int:user_id>", methods=("POST",))
def read_as(user_id):
    """Start a reader's session. No password, which is the point of the app."""
    # Scoped to role = 'kid' inside the query itself, so this route can never be
    # used to walk into a parent account and skip the password: the row is simply
    # not found. POST only, so a stray image tag on another page cannot sign
    # someone in as a kid either. removed_at IS NULL as well, or a reader a parent
    # had taken off the list could still be entered by posting their id.
    reader = get_db().execute(
        "SELECT id, username FROM users"
        " WHERE id = ? AND role = 'kid' AND removed_at IS NULL",
        (user_id,),
    ).fetchone()

    if reader is None:
        flash("That reader does not exist.", "danger")
        return redirect(url_for("auth.picker"))

    session.clear()
    session["user_id"] = reader["id"]
    flash(f"Reading as {reader['username']}.", "success")
    return redirect(url_for("wallet.index"))


@bp.route("/readers")
@parent_required
def readers():
    """Render the reader list a parent manages, active first then removed."""
    db = get_db()
    active = db.execute(
        "SELECT id, username FROM users"
        " WHERE role = 'kid' AND removed_at IS NULL ORDER BY username COLLATE NOCASE"
    ).fetchall()
    # The removed ones stay visible so a parent can undo a mistake.
    removed = db.execute(
        "SELECT id, username, removed_at FROM users"
        " WHERE role = 'kid' AND removed_at IS NOT NULL"
        " ORDER BY username COLLATE NOCASE"
    ).fetchall()
    return render_template("auth/readers.html", readers=active, removed=removed)


@bp.route("/readers/<int:user_id>/remove", methods=("POST",))
@parent_required
def remove_reader(user_id):
    """Take a reader off the list. Nothing is deleted, only hidden."""
    db = get_db()
    reader = db.execute(
        "SELECT id, username FROM users"
        " WHERE id = ? AND role = 'kid' AND removed_at IS NULL",
        (user_id,),
    ).fetchone()

    if reader is None:
        flash("That reader is not on the list.", "danger")
        return redirect(url_for("auth.readers"))

    # A flag, never a DELETE. Their books cascade and their chapters RESTRICT, so
    # a delete fails outright, and their purchases are what keeps the cards they
    # own off the shop. Hiding leaves the books, the chapters, the purchases and
    # the balance exactly where they are.
    db.execute("UPDATE users SET removed_at = datetime('now','localtime') WHERE id = ?",
               (user_id,))
    db.commit()
    flash(f"{reader['username']} is off the reading list. Nothing was deleted.",
          "success")
    return redirect(url_for("auth.readers"))


@bp.route("/readers/<int:user_id>/restore", methods=("POST",))
@parent_required
def restore_reader(user_id):
    """Put a hidden reader back on the list."""
    db = get_db()
    reader = db.execute(
        "SELECT id, username FROM users"
        " WHERE id = ? AND role = 'kid' AND removed_at IS NOT NULL",
        (user_id,),
    ).fetchone()

    if reader is None:
        flash("That reader is not on the removed list.", "danger")
        return redirect(url_for("auth.readers"))

    db.execute("UPDATE users SET removed_at = NULL WHERE id = ?", (user_id,))
    db.commit()
    flash(f"{reader['username']} is back on the reading list.", "success")
    return redirect(url_for("auth.readers"))


@bp.route("/register", methods=("GET", "POST"))
@parent_required
def register():
    """Add a reader, which is a parent's job: kids do not sign themselves up."""
    if request.method == "POST":
        # .get() rather than ["username"] so a hand-made POST missing a field
        # lands on the validation branch instead of raising KeyError.
        username = request.form.get("username", "")
        db = get_db()
        error = None
        existing = None

        if not username:
            error = "A name is required."
        else:
            # The friendly path: one cheap SELECT so the ordinary duplicate gets
            # a message instead of an exception. This alone cannot be trusted,
            # because two requests can pass it at the same instant.
            existing = db.execute(
                "SELECT id, removed_at FROM users WHERE username = ?", (username,)
            ).fetchone()
            if existing is not None and existing["removed_at"] is None:
                error = f"{username} is already a reader."

        if error is None and existing is not None:
            # The name belongs to a reader who was taken off the list. Restoring
            # that row rather than inserting is not a nicety: username is UNIQUE,
            # so a plain insert would raise, and restoring brings them back with
            # the books, the chapters and the balance they had.
            db.execute("UPDATE users SET removed_at = NULL WHERE id = ?",
                       (existing["id"],))
            db.commit()
            flash(f"{username} is back on the list, with everything they had.",
                  "success")
            return redirect(url_for("auth.readers"))

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
                flash(f"Added {username}. They can pick their name on the front page.",
                      "success")
                return redirect(url_for("auth.readers"))

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
