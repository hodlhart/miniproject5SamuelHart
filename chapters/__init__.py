# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""Application factory for the Pages for Pokemon app."""

import os

from flask import Flask, send_from_directory, url_for

# An optional local background picture, looked for in the instance folder under
# any of these names. It is not committed and nothing depends on it: the app is
# complete and correct without one, which is why a fresh clone looks right rather
# than broken. Only a name is looked for, and nothing is ever read out of it.
BACKGROUND_NAMES = ("background.jpg", "background.jpeg", "background.png")


def create_app(test_config=None):
    """Build and configure the Flask app, then return it."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY="dev",
        # The database lives in the instance folder, which is gitignored, so a
        # checkout never carries a stale database into a run.
        DATABASE=os.path.join(app.instance_path, "chapters.sqlite"),
    )

    # A config.py in the instance folder overrides the defaults above, but the
    # file is optional so a fresh checkout runs without one.
    if test_config is None:
        app.config.from_pyfile("config.py", silent=True)
    else:
        app.config.from_mapping(test_config)

    # The instance folder is gitignored, so it may not exist on a fresh clone.
    # Creating it here keeps the SQLite file and any secrets out of version control.
    os.makedirs(app.instance_path, exist_ok=True)

    from . import auth, db, shop, wallet

    # Wires up the teardown handler and the init-db command in one call.
    db.init_app(app)

    app.register_blueprint(auth.bp)
    app.register_blueprint(wallet.bp)
    app.register_blueprint(shop.bp)

    register_background(app)

    return app


def background_name(app):
    """Return the file name of the local background picture, or None."""
    for name in BACKGROUND_NAMES:
        if os.path.isfile(os.path.join(app.instance_path, name)):
            return name
    return None


def register_background(app):
    """Add the optional background route and its template variable to the app."""

    @app.route("/background")
    def background():
        """Serve the optional local background, or 404 when there is none."""
        name = background_name(app)
        if name is None:
            # Nothing to serve. The pages do not reference this route unless the
            # file is there, so a 404 here is only ever a hand-typed URL.
            return app.response_class(status=404)
        # send_from_directory builds the path itself and refuses anything that
        # resolves outside the folder, the same as the cached card pictures.
        return send_from_directory(app.instance_path, name)

    @app.context_processor
    def inject_background():
        """Offer the background URL to every template, or None when absent."""
        if background_name(app) is None:
            return {"background_url": None}
        return {"background_url": url_for("background")}
