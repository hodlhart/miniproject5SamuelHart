# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""Auth area. Placeholder only, no login logic yet."""

from flask import Blueprint

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/")
def index():
    """Return the placeholder page for the auth area."""
    return "auth placeholder"
