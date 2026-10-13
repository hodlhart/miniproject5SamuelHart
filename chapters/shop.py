# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""Parent side of the app, where the physical card shop lives."""

from flask import Blueprint

bp = Blueprint("shop", __name__, url_prefix="/shop")


@bp.route("/")
def index():
    """Return the placeholder page for the shop."""
    return "shop placeholder"
