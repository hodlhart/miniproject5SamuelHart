# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""The kid's side: the wallet, their books, and logging a chapter."""

import sqlite3

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from .auth import login_required
from .db import get_db

# No url_prefix: this blueprint owns the site root, so the wallet is the home page.
bp = Blueprint("wallet", __name__)


def get_totals(db, user_id):
    """Return one kid's row of chapters earned and chapters spent."""
    # Shaped as the note at the end of schema.sql describes: driven from users,
    # counting c.id rather than *. COUNT(*) would count the joined rows, and a
    # kid with a book but no chapters would read as having earned one.
    return db.execute(
        """
        SELECT COUNT(c.id) AS earned,
               COALESCE((SELECT SUM(p.chapters_spent)
                           FROM purchases p
                          WHERE p.user_id = u.id), 0) AS spent
          FROM users u
          LEFT JOIN books b    ON b.user_id = u.id
          LEFT JOIN chapters c ON c.book_id = b.id
         WHERE u.id = ?
         GROUP BY u.id
        """,
        (user_id,),
    ).fetchone()


def get_statement(db, user_id):
    """Return the kid's earning and spending rows, newest first."""
    # One row per event, so earnings and purchases can stack in a single table.
    # Two details keep the running balance honest:
    #
    #   logged_at and purchased_at are local time with one-second
    #   resolution, so a kid logging quickly gets rows that tie. ORDER BY
    #   (happened_at, kind, source_id) is a total order even then, because
    #   source_id is that row's primary key, so the sequence cannot shuffle
    #   between two loads of this page.
    #
    #   The window accumulates in that ascending order, while the final ORDER BY
    #   is its exact reverse, which is what puts the newest row on top without
    #   reversing the arithmetic. ROWS UNBOUNDED PRECEDING gives each tied row
    #   its own running figure; the default RANGE frame would give tied rows the
    #   same figure and the column would stop adding up.
    return db.execute(
        """
        WITH events AS (
            SELECT ch.logged_at      AS happened_at,
                   'chapter'         AS kind,
                   ch.id             AS source_id,
                   b.title           AS label,
                   ch.chapter_number AS chapter_number,
                   1                 AS delta
              FROM chapters ch
              JOIN books b ON b.id = ch.book_id
             WHERE b.user_id = :user_id
            UNION ALL
            SELECT p.purchased_at,
                   'purchase',
                   p.id,
                   c.name,
                   NULL,
                   -p.chapters_spent
              FROM purchases p
              JOIN cards c ON c.id = p.card_id
             WHERE p.user_id = :user_id
        )
        SELECT happened_at, kind, label, chapter_number, delta,
               SUM(delta) OVER (ORDER BY happened_at, kind, source_id
                                ROWS UNBOUNDED PRECEDING) AS balance_after
          FROM events
         ORDER BY happened_at DESC, kind DESC, source_id DESC
        """,
        {"user_id": user_id},
    ).fetchall()


def get_books(db, user_id):
    """Return the kid's books with the number of chapters logged in each."""
    # LEFT JOIN so a book with nothing logged yet still appears, at zero.
    return db.execute(
        """
        SELECT b.id, b.title, COUNT(c.id) AS chapter_count
          FROM books b
          LEFT JOIN chapters c ON c.book_id = b.id
         WHERE b.user_id = ?
         GROUP BY b.id, b.title
         ORDER BY b.title COLLATE NOCASE
        """,
        (user_id,),
    ).fetchall()


@bp.route("/")
@login_required
def index():
    """Render the wallet: the balance, and the statement behind it."""
    db = get_db()
    totals = get_totals(db, g.user["id"])
    return render_template(
        "wallet.html",
        earned=totals["earned"],
        spent=totals["spent"],
        balance=totals["earned"] - totals["spent"],
        events=get_statement(db, g.user["id"]),
    )


@bp.route("/books")
@login_required
def books():
    """Render the kid's own books and what they have logged in each."""
    return render_template("books.html", books=get_books(get_db(), g.user["id"]))


@bp.route("/chapters/log", methods=("GET", "POST"))
@login_required
def log_chapter():
    """Log a chapter, creating the book first when a new title was typed."""
    db = get_db()
    kid_id = g.user["id"]

    if request.method == "POST":
        choice = request.form.get("book_id", "new")
        typed = request.form.get("title", "")
        raw_number = request.form.get("chapter_number", "").strip()
        error = None

        # isdigit() rejects empty, negative, decimal and non-numeric input in
        # one go, so a bad chapter number becomes a message and not the CHECK
        # constraint or an int() crash.
        if not raw_number.isdigit() or int(raw_number) < 1:
            error = "Chapter number must be a whole number of 1 or more."

        # Collapsed here because COLLATE NOCASE cannot see a double space or a
        # leading one, so the UNIQUE below would happily store 'Wings  of Fire'
        # as a second book.
        title = " ".join(typed.split())

        if error is None and choice == "new" and not title:
            error = "Type a title for the new book, or pick one you already have."

        book_id = None
        if error is None and choice != "new":
            # Looked up against this kid rather than trusted from the form, so a
            # posted id cannot log a chapter into another kid's book and quietly
            # inflate their balance.
            owned = None
            if choice.isdigit():
                owned = db.execute(
                    "SELECT id FROM books WHERE id = ? AND user_id = ?",
                    (choice, kid_id),
                ).fetchone()
            if owned is None:
                error = "Pick one of your books."
            else:
                book_id = owned["id"]

        if error is None:
            if choice == "new":
                try:
                    book_id = db.execute(
                        "INSERT INTO books (user_id, title) VALUES (?, ?)",
                        (kid_id, title),
                    ).lastrowid
                except sqlite3.IntegrityError:
                    # UNIQUE (user_id, title COLLATE NOCASE) means this kid
                    # already owns that title under some spelling. NOCASE is the
                    # schema's own definition of "the same book", so the chapter
                    # belongs on the existing row rather than being refused. The
                    # form opens on "A new book", which makes refusing the dead
                    # end a kid walks into by retyping a title they already have.
                    db.rollback()
                    existing = db.execute(
                        "SELECT id FROM books"
                        " WHERE user_id = ? AND title COLLATE NOCASE = ?",
                        (kid_id, title),
                    ).fetchone()
                    if existing is None:
                        # The constraint fired for some other reason, so there is
                        # nothing to attach to and picking a book would be a guess.
                        error = "That book could not be saved."
                    else:
                        book_id = existing["id"]

            if error is None:
                try:
                    db.execute(
                        "INSERT INTO chapters (book_id, chapter_number) VALUES (?, ?)",
                        (book_id, int(raw_number)),
                    )
                except sqlite3.IntegrityError:
                    # Both inserts share one transaction, so this also undoes the
                    # book when this request created one: a refused chapter never
                    # leaves a stray empty book on the shelf.
                    db.rollback()
                    error = f"Chapter {raw_number} of that book is already logged."
                else:
                    db.commit()
                    return redirect(url_for("wallet.index"))

        flash(error, "danger")

    return render_template(
        "log_chapter.html",
        books=db.execute(
            "SELECT id, title FROM books WHERE user_id = ? ORDER BY title COLLATE NOCASE",
            (kid_id,),
        ).fetchall(),
    )
