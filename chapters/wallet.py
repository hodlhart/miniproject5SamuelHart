# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""Kid side of the app, where chapters are earned and balances shown."""

from flask import Blueprint, render_template

# No url_prefix: this blueprint owns the site root, so the wallet is the home page.
bp = Blueprint("wallet", __name__)


@bp.route("/")
def index():
    """Render the wallet home page."""
    return render_template("wallet.html")
