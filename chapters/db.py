# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""SQLite plumbing: one connection per request, plus the init-db command."""

import os
import sqlite3

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash


def get_db():
    """Return this request's SQLite connection, opening it on first use."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        # Rows behave like dicts, so a template can use row["title"].
        g.db.row_factory = sqlite3.Row
        # SQLite ships foreign keys switched off and the setting is per
        # connection, so the REFERENCES clauses need this or they do nothing.
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    """Close this request's connection if one was opened."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Drop and recreate every table by running the top-level schema.sql."""
    db = get_db()
    # schema.sql sits beside the chapters package rather than inside it, so the
    # path climbs one level out of the app's root_path.
    schema_path = os.path.join(current_app.root_path, os.pardir, "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        db.executescript(f.read())


@click.command("init-db")
def init_db_command():
    """Clear the existing data and create new tables."""
    init_db()
    click.echo("Initialized the database.")


@click.command("create-parent")
@click.argument("username")
def create_parent_command(username):
    """Create a parent account, which the web form deliberately cannot do."""
    db = get_db()
    # Hidden input so the password never lands in shell history or the process
    # list, the way it would if it were a command line argument.
    # Confirmed as well, because the prompt is hidden and there is no password
    # reset here: a typo nobody can see would otherwise create an account no one
    # can log into.
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)

    taken = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if taken is not None:
        # ClickException prints the message and exits non-zero, so no traceback.
        raise click.ClickException(f"User {username} is already registered.")

    # Hashed the same way register does, so a parent password and a kid password
    # are stored identically. Only the role differs.
    db.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
        (username, generate_password_hash(password), "parent"),
    )
    db.commit()
    click.echo(f"Created parent {username}.")


@click.command("refresh-sets")
def refresh_sets_command():
    """Cache the catalogue's set list so the Add-a-card dropdown works offline."""
    # Imported inside the command rather than at the top: shop.py imports get_db
    # from this module, so importing it back at module level would be a cycle.
    from .shop import ApiError, api_get

    db = get_db()
    try:
        catalogue = api_get("/sets")
    except ApiError as exc:
        raise click.ClickException(f"Could not reach the card catalogue: {exc}")

    if not isinstance(catalogue, list) or not catalogue:
        # Refused rather than allowed to prune: an empty answer would wipe the
        # cache and leave the dropdown with nothing but "Any set".
        raise click.ClickException("The catalogue did not return a set list.")

    rows = []
    for position, entry in enumerate(catalogue):
        set_id = entry.get("id")
        if not set_id:
            continue
        counts = entry.get("cardCount") or {}
        total = counts.get("total") if isinstance(counts, dict) else None
        rows.append((set_id, entry.get("name") or set_id, total or 0, position))

    # Upserted by id, so re-running updates rows in place instead of duplicating.
    db.executemany(
        """
        INSERT INTO sets (id, name, card_count, catalog_order) VALUES (?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            name = excluded.name,
            card_count = excluded.card_count,
            catalog_order = excluded.catalog_order,
            refreshed_at = datetime('now','localtime')
        """,
        rows,
    )
    # Anything the catalogue no longer lists is pruned, so the dropdown cannot
    # offer a ghost set that no longer resolves.
    placeholders = ", ".join("?" for _ in rows)
    pruned = db.execute(
        f"DELETE FROM sets WHERE id NOT IN ({placeholders})",
        [row[0] for row in rows],
    ).rowcount
    db.commit()

    click.echo(f"Cached {len(rows)} sets.")
    if pruned:
        click.echo(f"Removed {pruned} sets the catalogue no longer lists.")
    held = db.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
    click.echo(f"sets table now holds {held} rows.")


def init_app(app):
    """Register the teardown handler and the CLI commands on the app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_parent_command)
    app.cli.add_command(refresh_sets_command)
