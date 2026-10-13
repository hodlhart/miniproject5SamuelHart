# INF601 - Advanced Programming in Python
# Samuel Hart
# Mini Project 5

"""Development entry point. Run this file to start the Pages for Pokemon server."""

from chapters import create_app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
