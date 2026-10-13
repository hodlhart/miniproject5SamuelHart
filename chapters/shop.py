# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""Parent side of the app: the storefront, and stocking the card shop."""

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .auth import parent_required
from .db import get_db

bp = Blueprint("shop", __name__, url_prefix="/shop")

# TCGdex needs no API key, so no credential belongs in this project.
API_BASE = "https://api.tcgdex.net/v2/en"

# TCGdex returns a bare asset path such as
# https://assets.tcgdex.net/en/base/base1/4 with no file extension, so rendering
# it raw gives a broken image: the bare URL answers with an HTML error page.
# Measured against the live service, .png is 200 with image/png while .webp,
# .jpg and .jpeg are all 404, so .png is the one that loads.
IMAGE_SUFFIX = ".png"

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
                f"{image}{IMAGE_SUFFIX}" if image else None,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        # cards.tcgdex_id is UNIQUE, so this is the same card arriving twice.
        db.rollback()
        flash(f"{record['name']} is already in the shop.", "danger")
        return redirect(url_for("shop.add"))

    flash(f"Added {record['name']} to the shop.", "success")
    return redirect(url_for("shop.manage"))


@bp.route("/")
def index():
    """Render the storefront: every card that is currently for sale."""
    cards = get_db().execute(
        """
        SELECT id, name, set_name, number, tier, price_chapters, image_url
          FROM cards
         WHERE for_sale = 1
         ORDER BY name COLLATE NOCASE, set_name COLLATE NOCASE, number
        """
    ).fetchall()
    return render_template("shop/store.html", cards=cards)


@bp.route("/add", methods=("GET", "POST"))
@parent_required
def add():
    """Search the catalogue for cards, or add the posted one to the shop."""
    if request.method == "POST":
        return add_from_form()

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
            matches = found if isinstance(found, list) else []

    return render_template(
        "shop/add.html",
        matches=matches,
        searched=name,
        set_id=set_id,
        tier_prices=TIER_PRICES,
    )


@bp.route("/manage")
@parent_required
def manage():
    """Render the shop's stock with an on-sale control for each card."""
    cards = get_db().execute(
        """
        SELECT id, tcgdex_id, name, set_name, number, tier, price_chapters,
               image_url, for_sale
          FROM cards
         ORDER BY for_sale DESC, name COLLATE NOCASE, number
        """
    ).fetchall()
    return render_template("shop/manage.html", cards=cards)


@bp.route("/card/<int:card_id>/toggle", methods=("POST",))
@parent_required
def toggle_card(card_id):
    """Flip one card between for sale and off sale."""
    db = get_db()
    card = db.execute(
        "SELECT name, for_sale FROM cards WHERE id = ?", (card_id,)
    ).fetchone()

    if card is None:
        flash("That card is not in the shop.", "danger")
        return redirect(url_for("shop.manage"))

    now_for_sale = 0 if card["for_sale"] else 1
    db.execute("UPDATE cards SET for_sale = ? WHERE id = ?", (now_for_sale, card_id))
    db.commit()

    action = "is now for sale" if now_for_sale else "is now off sale"
    flash(f"{card['name']} {action}.", "success")
    return redirect(url_for("shop.manage"))
