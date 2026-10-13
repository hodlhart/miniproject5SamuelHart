# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""Application factory for the Chapter Cards app."""

import os

from flask import Flask


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

    return app
