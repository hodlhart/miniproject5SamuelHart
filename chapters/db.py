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


def init_app(app):
    """Register the teardown handler and the CLI commands on the app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_parent_command)
