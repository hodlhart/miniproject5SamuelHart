# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""The card shop, and stocking it: storefront, collection, and the catalogue."""

import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from .auth import login_required, parent_required
from .db import get_db
# The wallet's own helper, not a second copy of the arithmetic, so a balance
# shown in the buy modal can never disagree with the one on the wallet page.
from .wallet import get_totals

bp = Blueprint("shop", __name__, url_prefix="/shop")

# TCGdex needs no API key, so no credential belongs in this project.
API_BASE = "https://api.tcgdex.net/v2/en"

# One page of the storefront and of the manage page. Named rather than buried in
# a LIMIT so the two pages cannot drift apart, and twelve fills three Bootstrap
# rows of four on a wide screen.
PAGE_SIZE = 12

# Pictures. The catalogue's image field is a bare path with no file extension,
# such as https://assets.tcgdex.net/en/base/base1/4, and the real file is that
# path plus /{quality}.{extension}. Measured for base1/4: 838 KB at .png, 360 KB
# at /high.png, 67 KB at /low.png, 20 KB at /low.webp, 23 KB at /low.jpg.
#
# The path itself is never built here. For base1 the URL's middle segment is
# "base" while the set id is "base1", so it cannot be derived, and every guessed
# path for a set like mfb is a 404. Only the quality and extension are appended to
# whatever the catalogue returned.
LOCAL_QUALITY = "low"
LOCAL_EXTENSION = "webp"
LOCAL_PICTURE = f"{LOCAL_QUALITY}.{LOCAL_EXTENSION}"
# Only used when nothing is cached locally, because the bare path renders nothing.
REMOTE_PICTURE = "high.png"
CARD_IMAGE_FOLDER = "card_images"

# A card the catalogue has no artwork for, or one whose picture could not be
# fetched, still renders an image rather than a broken icon. A data URI needs no
# file and no network, so this works on a machine with no internet at all.
PLACEHOLDER_IMAGE = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='240' height='336'>"
    "<rect width='100%' height='100%' fill='%23e9ecef'/>"
    "<text x='50%' y='58%' font-family='sans-serif' font-size='18'"
    " fill='%236c757d' text-anchor='middle'>No picture</text></svg>"
)

CARD_COLUMNS = (
    "id, tcgdex_id, name, set_name, number, rarity, tier,"
    " price_chapters, image_url, for_sale"
)

TIMEOUT_SECONDS = 10

# The tier is a label. These figures pre-fill the price box as a convenience and
# do nothing else: cards.price_chapters is what is stored and charged, and no
# code may read a price back out of the tier.
TIER_PRICES = {"normal": 1, "ex": 5, "full_art": 10}


class ApiError(Exception):
    """Raised when the TCGdex catalogue cannot be reached or read."""


def api_get(path, params=None):
    """Return decoded JSON from one TCGdex path, raising ApiError on failure."""
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Caught before URLError, which it subclasses. A 404 is a different thing
        # to tell a parent than a dead network, so the two do not share a message.
        reason = ("the catalogue has no card with that id" if exc.code == 404
                  else f"the catalogue answered with error {exc.code}")
        current_app.logger.warning("TCGdex HTTP %s for %s", exc.code, url)
        raise ApiError(reason) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # The raw errno goes to the log rather than the page: "Connection refused"
        # is not something a parent can act on, "check the network" is.
        current_app.logger.warning("TCGdex unreachable for %s: %s", url, exc)
        raise ApiError(
            "the network is unreachable, so check the connection and try again"
        ) from exc
    except json.JSONDecodeError as exc:
        current_app.logger.warning("TCGdex unreadable answer for %s: %s", url, exc)
        raise ApiError("the catalogue answered with something unreadable") from exc


def lookup_card(tcgdex_id):
    """Return the catalogue's own record for one card id, raising ApiError."""
    record = api_get(f"/cards/{urllib.parse.quote(tcgdex_id)}")
    if not isinstance(record, dict) or not record.get("name"):
        # A reachable catalogue that answers with something unusable is the same
        # problem from the parent's side as an unreachable one.
        raise ApiError("the catalogue returned an unexpected record")
    return record


def remote_picture(image_base, quality):
    """Return a remote picture URL built from the catalogue's image field."""
    # None in, None out: a card with no artwork in the catalogue has no image
    # field at all, and mfb-9 is one of those.
    if not image_base:
        return None
    return f"{image_base}/{quality}"


def card_image_dir():
    """Return the folder of cached card pictures, creating it if needed."""
    path = os.path.join(current_app.instance_path, CARD_IMAGE_FOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def card_image_filename(tcgdex_id):
    """Return the file name a card's cached picture is stored under."""
    # Catalogue ids look like base1-4 and sm7.5-3, so only characters that cannot
    # mean a path are kept. The serving route also passes its name through
    # send_from_directory, which refuses anything that leaves the folder.
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", tcgdex_id)
    return f"{safe}.{LOCAL_EXTENSION}"


def cached_image_name(tcgdex_id):
    """Return the cached picture's file name, or None when nothing is cached."""
    name = card_image_filename(tcgdex_id)
    if os.path.exists(os.path.join(card_image_dir(), name)):
        return name
    return None


def image_source(card):
    """Return what to render for a card: the cached file, then remote, then none."""
    cached = cached_image_name(card["tcgdex_id"])
    if cached:
        return url_for("shop.card_image", name=cached)
    remote = remote_picture(card["image_url"], REMOTE_PICTURE)
    if remote:
        return remote
    return PLACEHOLDER_IMAGE


def with_images(rows):
    """Return card rows as dicts, each carrying the picture source resolved."""
    return [dict(row, image_src=image_source(row)) for row in rows]


def cache_card_image(tcgdex_id, image_base):
    """Fetch the small local copy of one card's picture, returning True on success."""
    url = remote_picture(image_base, LOCAL_PICTURE)
    if not url:
        return False
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Logged, and reported to the parent as a warning. The card itself is
        # still added: a picture that cannot be fetched must not cost the row.
        current_app.logger.warning("Card picture not cached for %s: %s", tcgdex_id, exc)
        return False
    with open(os.path.join(card_image_dir(), card_image_filename(tcgdex_id)), "wb") as handle:
        handle.write(payload)
    return True


def clamp_page(raw, total, page_size):
    """Return (page, last_page), with page forced into the real range."""
    # page comes off the query string, so it can be absent, "abc", "0", "-3" or
    # "999999". "0" and "999999" are digits and get clamped into range; the rest
    # are not digits and fall back to the first page. Either way the value that
    # reaches OFFSET is one the rows query can actually satisfy, so Previous and
    # Next are never both live on a page that does not exist.
    last_page = max(1, -(-total // page_size))
    page = int(raw) if raw.isdigit() else 1
    return min(max(page, 1), last_page), last_page


def card_filter(term, only_offered):
    """Return (where_sql, params) for a card search over the shop or the stock."""
    conditions = []
    params = {}
    if only_offered:
        # What the shop is offering: for sale, and not already bought. This has
        # to be in the count as well as the rows, or the page count is wrong the
        # moment anything sells.
        conditions.append("for_sale = 1")
        conditions.append("id NOT IN (SELECT card_id FROM purchases)")
    if term:
        conditions.append("(name LIKE :like OR set_name LIKE :like OR number LIKE :like)")
        params["like"] = f"%{term}%"
    if not conditions:
        return "", params
    return " WHERE " + " AND ".join(conditions), params


def page_of_cards(db, where_sql, params, order_sql):
    """Return (rows, page, last_page, total) for one page of filtered cards."""
    # The count runs the SAME where clause as the rows, for the reason above: a
    # count built from a different filter advertises a Next link that leads
    # nowhere, and the total shown to the parent would not match what they see.
    total = db.execute(f"SELECT COUNT(*) FROM cards {where_sql}", params).fetchone()[0]
    page, last_page = clamp_page(request.args.get("page", "").strip(), total, PAGE_SIZE)
    rows = db.execute(
        f"SELECT {CARD_COLUMNS} FROM cards {where_sql} {order_sql}"
        " LIMIT :limit OFFSET :offset",
        # OFFSET comes from the clamped page, never from the raw query string.
        dict(params, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE),
    ).fetchall()
    return rows, page, last_page, total


def add_from_form():
    """Store the card the parent posted, returning a response either way."""
    db = get_db()
    tcgdex_id = request.form.get("tcgdex_id", "").strip()
    tier = request.form.get("tier", "")
    raw_price = request.form.get("price_chapters", "").strip()

    error = None
    if not tcgdex_id:
        error = "Pick a card from the search results first."
    elif tier not in TIER_PRICES:
        error = "Pick one of the three tiers."
    elif not raw_price.isdigit() or int(raw_price) < 1:
        error = "Price must be a whole number of 1 or more."

    if error is not None:
        flash(error, "danger")
        return redirect(url_for("shop.add"))

    # Only tcgdex_id, tier and price come off the form. Name, set, number and
    # image are re-fetched here by id and stored from that response, because the
    # form's copies are display values and a posted name could say anything. This
    # is the only thing between a parent's form and the database.
    try:
        record = lookup_card(tcgdex_id)
    except ApiError as exc:
        flash(f"Could not add that card: {exc}", "danger")
        return redirect(url_for("shop.add"))

    image = record.get("image")
    card_set = record.get("set") or {}

    try:
        db.execute(
            """
            INSERT INTO cards (tcgdex_id, name, set_name, number, rarity, tier,
                               price_chapters, image_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                # The id is taken from the record too, so what is stored is the
                # catalogue's own spelling of it and not the posted string.
                record["id"],
                record["name"],
                card_set.get("name"),
                record.get("localId"),
                record.get("rarity"),
                tier,
                int(raw_price),
                # The catalogue's image field exactly as it came, extension and
                # all absent: this is the source the local copy is fetched from
                # and the fallback when there is no local copy. Nothing renders
                # this value directly, because the bare path shows a broken image.
                image,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        # cards.tcgdex_id is UNIQUE, so this is the same card arriving twice.
        db.rollback()
        flash(f"{record['name']} is already in the shop.", "danger")
        return redirect(url_for("shop.add"))

    # Fetched once, here, and served from the app afterwards: 20 KB rather than
    # 838 KB per card, and the shop still shows pictures with no internet.
    if image and not cache_card_image(record["id"], image):
        flash(
            f"{record['name']} was added, but its picture could not be downloaded, "
            "so it shows the catalogue's own image.",
            "warning",
        )
    elif not image:
        # Said now rather than discovered later: mfb-9 has no artwork at all.
        flash(
            f"The catalogue has no picture for {record['name']}, so it shows a "
            "placeholder.",
            "warning",
        )

    flash(f"Added {record['name']} to the shop.", "success")
    return redirect(url_for("shop.manage"))


@bp.route("/")
@login_required
def index():
    """Render one page of for-sale cards, with a search box and a Buy control."""
    db = get_db()
    term = request.args.get("q", "").strip()
    where_sql, params = card_filter(term, only_offered=True)
    rows, page, last_page, total = page_of_cards(
        db, where_sql, params,
        "ORDER BY name COLLATE NOCASE, set_name COLLATE NOCASE, number",
    )
    # The modal states the balance, so it is read here. None for a parent, who
    # owns the stock and gets no Buy control at all.
    balance = None
    if g.user["role"] == "kid":
        totals = get_totals(db, g.user["id"])
        balance = totals["earned"] - totals["spent"]
    return render_template(
        "shop/store.html",
        cards=with_images(rows),
        balance=balance,
        term=term,
        page=page,
        last_page=last_page,
        total=total,
    )


@bp.route("/my-cards")
@login_required
def my_cards():
    """Render the cards this kid owns, newest first, as a collection."""
    if g.user["role"] != "kid":
        # A parent owns the stock and buys nothing, so this page is not theirs.
        # Sent to the shop, the same as a parent landing on the wallet.
        return redirect(url_for("shop.index"))
    rows = get_db().execute(
        """
        SELECT c.id, c.tcgdex_id, c.name, c.set_name, c.number, c.tier,
               c.image_url, p.chapters_spent, p.purchased_at
          FROM purchases p
          JOIN cards c ON c.id = p.card_id
         WHERE p.user_id = ?
         ORDER BY p.purchased_at DESC, p.id DESC
        """,
        (g.user["id"],),
    ).fetchall()
    return render_template("shop/my_cards.html", cards=with_images(rows))


@bp.route("/card-image/<path:name>")
def card_image(name):
    """Serve a cached card picture out of the instance folder."""
    # send_from_directory builds the path itself and refuses anything that
    # resolves outside the folder, which is why the name is not joined by hand.
    # The converter allows a slash on purpose, so a crafted name reaches that
    # check instead of being turned away early by a stricter route.
    return send_from_directory(card_image_dir(), name)


@bp.route("/buy/<int:card_id>", methods=("POST",))
@login_required
def buy(card_id):
    """Buy one card for the signed-in kid, at the price it carries right now."""
    db = get_db()

    # A parent owns the stock, so they are refused here explicitly rather than
    # being left to fail on a balance that happens to be zero.
    if g.user["role"] != "kid":
        flash("Only kids can buy cards. A parent owns the shop stock.", "danger")
        return redirect(url_for("shop.index"))

    card = db.execute(
        "SELECT id, name, price_chapters, for_sale FROM cards WHERE id = ?", (card_id,)
    ).fetchone()
    if card is None:
        flash("That card is not in the shop.", "danger")
        return redirect(url_for("shop.index"))
    if not card["for_sale"]:
        flash(f"{card['name']} is not for sale.", "danger")
        return redirect(url_for("shop.index"))

    # The funds check is part of the write, so no window exists between the two
    # for a second request to slip through. The subqueries define the balance
    # exactly as the wallet does: chapters counted through books, minus what has
    # been spent. If the WHERE matches nothing then no row is inserted, and that
    # absence is the refusal.
    try:
        cursor = db.execute(
            """
            INSERT INTO purchases (user_id, card_id, chapters_spent)
            SELECT ?, ?, ?
             WHERE (SELECT COALESCE(SUM(c.chapter_count), 0)
                      FROM chapters c JOIN books b ON b.id = c.book_id
                     WHERE b.user_id = ?)
                 - (SELECT COALESCE(SUM(chapters_spent), 0) FROM purchases
                     WHERE user_id = ?) >= ?
            """,
            (
                g.user["id"],
                card["id"],
                # Copied in as the price stands now, so re-pricing the card
                # tomorrow cannot rewrite what this kid already paid.
                card["price_chapters"],
                g.user["id"],
                g.user["id"],
                card["price_chapters"],
            ),
        )
    except sqlite3.IntegrityError:
        # purchases.card_id is UNIQUE, so this card was already bought. Reported
        # as a message rather than letting the constraint raise a 500.
        db.rollback()
        flash(f"{card['name']} has already been bought.", "danger")
        return redirect(url_for("shop.index"))

    if cursor.rowcount == 0:
        # No row went in, so the WHERE refused it for want of funds. The balance
        # is read here only to word the message, since the insert was the
        # guarantee and this is advice.
        totals = get_totals(db, g.user["id"])
        balance = totals["earned"] - totals["spent"]
        db.rollback()
        flash(
            f"{card['name']} costs {card['price_chapters']} chapters and you have "
            f"{balance}. Log another chapter first.",
            "danger",
        )
        return redirect(url_for("shop.index"))

    db.commit()
    flash(f"You bought {card['name']} for {card['price_chapters']} chapters.", "success")
    return redirect(url_for("shop.my_cards"))


@bp.route("/add", methods=("GET", "POST"))
@parent_required
def add():
    """Search the catalogue for cards, or add the posted one to the shop."""
    if request.method == "POST":
        return add_from_form()

    db = get_db()
    name = request.args.get("name", "").strip()
    set_id = request.args.get("set", "").strip()
    matches = None

    if name:
        params = {"name": name}
        if set_id:
            params["set"] = set_id
        try:
            found = api_get("/cards", params)
        except ApiError as exc:
            flash(f"Could not search the card catalogue: {exc}", "danger")
        else:
            found = found if isinstance(found, list) else []
            # A hit carries its bare image path when the catalogue has artwork for
            # that printing, and no image key at all when it does not, so the
            # parent can see which one they are picking before adding it.
            matches = [
                dict(hit, thumb=remote_picture(hit.get("image"), LOCAL_PICTURE))
                for hit in found
            ]

    return render_template(
        "shop/add.html",
        matches=matches,
        searched=name,
        set_id=set_id,
        # Ordered by the catalogue's own sequence, newest first, so a fresh
        # database with nothing cached simply shows "Any set".
        sets=db.execute(
            "SELECT id, name FROM sets ORDER BY catalog_order DESC"
        ).fetchall(),
        tier_prices=TIER_PRICES,
    )


@bp.route("/manage")
@parent_required
def manage():
    """Render one page of the shop's stock, with a search box."""
    db = get_db()
    term = request.args.get("q", "").strip()
    # Every card the shop owns, bought or not, so the filter is the search alone.
    where_sql, params = card_filter(term, only_offered=False)
    rows, page, last_page, total = page_of_cards(
        db, where_sql, params, "ORDER BY for_sale DESC, name COLLATE NOCASE, number"
    )
    return render_template(
        "shop/manage.html",
        cards=with_images(rows),
        term=term,
        page=page,
        last_page=last_page,
        total=total,
    )


@bp.route("/card/<int:card_id>/toggle", methods=("POST",))
@parent_required
def toggle_card(card_id):
    """Move one card out of the shop, or back into it."""
    db = get_db()
    card = db.execute(
        "SELECT name, for_sale FROM cards WHERE id = ?", (card_id,)
    ).fetchone()

    if card is None:
        flash("That card is not in the shop.", "danger")
        return redirect(url_for("shop.manage"))

    now_for_sale = 0 if card["for_sale"] else 1
    # Removing only clears the flag. The row stays, because purchases point at it
    # and a card someone already bought cannot be deleted at all.
    db.execute("UPDATE cards SET for_sale = ? WHERE id = ?", (now_for_sale, card_id))
    db.commit()

    action = "is back in the shop" if now_for_sale else "has been removed"
    flash(f"{card['name']} {action}.", "success")
    return redirect(url_for("shop.manage"))
