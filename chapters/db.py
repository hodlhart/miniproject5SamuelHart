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


# The demo seed, so a fresh clone has something to look at. Cards the catalogue
# really has and that really carry artwork, spread across the three tiers so every
# tier colour and stripe is visible. Sixteen of them, so that after the two demo
# purchases below the shop still fills two pages at the twelve-per-page size.
DEMO_CARDS = (
    ("base1-1", "normal", 1),
    ("base1-2", "normal", 1),
    ("base1-3", "normal", 2),
    ("base1-4", "normal", 2),
    ("base1-5", "normal", 1),
    ("base1-6", "normal", 2),
    ("base1-7", "normal", 1),
    ("base1-8", "ex", 5),
    ("base1-9", "ex", 5),
    ("base1-10", "ex", 5),
    ("base1-11", "ex", 5),
    ("base1-12", "ex", 6),
    ("base1-13", "ex", 5),
    ("base1-14", "full_art", 10),
    ("base1-15", "full_art", 10),
    ("base1-16", "full_art", 12),
)

# Reader name, the book they are reading, and how many chapters each reading was
# worth. The totals are 5, 7 and 10 chapters.
DEMO_READERS = (
    ("Ana", "Holes", (3, 2)),
    ("Ben", "The Hobbit", (4, 3)),
    ("Cleo", "Wings of Fire", (5, 2, 3)),
)

# Who buys which card. Both of Ana's fit inside the five chapters she has read, and
# that is deliberate: sufficiency of funds is the buy route's rule, and the seed
# does not go around it by inventing a purchase a reader could not afford.
DEMO_PURCHASES = (("Ana", "base1-1"), ("Ana", "base1-3"))


@click.command("seed-demo")
def seed_demo_command():
    """Add demo cards, readers and readings, so a fresh clone has something to see."""
    # Imported inside the command, like refresh-sets, because shop.py imports
    # get_db from this module and a module level import back would be a cycle.
    from .shop import ApiError, cache_card_image, lookup_card

    db = get_db()
    new_cards = known_cards = repaired = cached = no_art = unreachable = 0
    new_readers = known_readers = readings = bought = 0
    reader_ids = {}

    for tcgdex_id, tier, price in DEMO_CARDS:
        existing = db.execute(
            "SELECT id, image_url FROM cards WHERE tcgdex_id = ?", (tcgdex_id,)
        ).fetchone()

        if existing is not None and existing["image_url"] is not None:
            # Here already, with its picture. Left exactly as it is, and counted
            # rather than raising on the UNIQUE constraint, the same way the
            # readers page treats a name that is already there.
            known_cards += 1
            continue

        reached = True
        try:
            record = lookup_card(tcgdex_id)
        except ApiError:
            # No catalogue. The card is still made, so the shop and the tier
            # colours are all there, and its name falls back to the catalogue id
            # because that is genuinely all we know. Nothing needs special casing
            # for it: the pages already cope with a card that has no artwork and no
            # set name, showing "Unknown set" and the placeholder.
            reached = False
            unreachable += 1
            record = {"id": tcgdex_id, "name": tcgdex_id}

        card_set = record.get("set") or {}
        image = record.get("image")

        if existing is not None:
            # Made earlier with no catalogue, so this run fills it in rather than
            # leaving a card named after its own id for ever.
            db.execute(
                """
                UPDATE cards SET name = ?, set_name = ?, number = ?, rarity = ?,
                                 image_url = ?
                 WHERE id = ?
                """,
                (record["name"], card_set.get("name"), record.get("localId"),
                 record.get("rarity"), image, existing["id"]),
            )
            repaired += 1
        else:
            db.execute(
                """
                INSERT INTO cards (tcgdex_id, name, set_name, number, rarity, tier,
                                   price_chapters, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record["id"], record["name"], card_set.get("name"),
                 record.get("localId"), record.get("rarity"), tier, price, image),
            )
            new_cards += 1

        # The add route's own helper, not a second downloader of our own: two
        # copies would drift and one of them would end up wrong.
        if image and cache_card_image(record["id"], image):
            cached += 1
        elif not image and reached:
            # Counted only when the catalogue actually answered. A catalogue that
            # could not be reached is not a card with no artwork, and saying so
            # would be wrong in the one place it matters.
            no_art += 1
    db.commit()

    for name, book, counts in DEMO_READERS:
        row = db.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()
        if row is not None:
            known_readers += 1
            reader_ids[name] = row["id"]
            continue
        kid = db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, NULL, 'kid')",
            (name,),
        ).lastrowid
        reader_ids[name] = kid
        new_readers += 1
        book_id = db.execute(
            "INSERT INTO books (user_id, title) VALUES (?, ?)", (kid, book)
        ).lastrowid
        for count in counts:
            db.execute(
                "INSERT INTO chapters (book_id, chapter_count) VALUES (?, ?)",
                (book_id, count),
            )
            readings += 1
    db.commit()

    for name, tcgdex_id in DEMO_PURCHASES:
        kid = reader_ids.get(name)
        card = db.execute(
            "SELECT id, price_chapters FROM cards WHERE tcgdex_id = ?", (tcgdex_id,)
        ).fetchone()
        if kid is None or card is None:
            continue
        if db.execute(
            "SELECT 1 FROM purchases WHERE card_id = ?", (card["id"],)
        ).fetchone():
            continue
        db.execute(
            "INSERT INTO purchases (user_id, card_id, chapters_spent) VALUES (?, ?, ?)",
            (kid, card["id"], card["price_chapters"]),
        )
        bought += 1
    db.commit()

    click.echo("Demo data, for looking at the app. Nothing here is required by it.")
    click.echo(f"  cards     {new_cards} added, {known_cards} already here, "
               f"{repaired} filled in from the catalogue")
    click.echo(f"  pictures  {cached} cached locally, {no_art} with no artwork "
               f"in the catalogue")
    click.echo(f"  readers   {new_readers} added, {known_readers} already here, "
               f"{readings} readings logged")
    click.echo(f"  purchases {bought}")

    if unreachable:
        click.echo("")
        click.echo(f"The catalogue could not be reached for {unreachable} cards, so "
                   f"they went in without it:")
        click.echo("  their names are their catalogue ids, and their pictures fall "
                   "back the way any card's do.")
        click.echo("  Run this again with a connection and it will fill them in.")

    parent = db.execute(
        "SELECT username FROM users WHERE role = 'parent' ORDER BY id LIMIT 1"
    ).fetchone()
    click.echo("")
    if parent is None:
        # Deliberately not created here. A password written into the source would
        # be worse than having no demo data at all.
        click.echo("There is no parent account yet, so there is nobody to log in as.")
        click.echo("Make one, and the shop is ready to look at:")
        click.echo("  flask --app chapters create-parent <name>")
    else:
        click.echo(f"Log in as {parent['username']} to see the shop, or pick a "
                   f"reader's name on the front page.")


def init_app(app):
    """Register the teardown handler and the CLI commands on the app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_parent_command)
    app.cli.add_command(refresh_sets_command)
    app.cli.add_command(seed_demo_command)
