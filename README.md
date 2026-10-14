<!-- INF601 - Advanced Programming in Python -->
<!-- Samuel Hart -->
<!-- Mini Project 5 -->

# Pages for Pokemon

A family app for a home network. Kids read books, log how many chapters they
finished, and spend those chapters on physical Pokemon cards their parents own.

Two sides to one economy:

- **Earning.** A reader logs what they read: a book title and how many chapters,
  in one entry. Three chapters in a sitting is one entry worth three.
- **Spending.** A parent inventories the family's physical cards into the shop. A
  reader browses the shop and spends chapters on a card, which then appears on
  their own shelf.

## What a card costs

Every card carries a tier, and the tier suggests a price when the card is added:

| Tier | Suggested price |
| --- | --- |
| normal | 1 chapter |
| ex | 5 chapters |
| full art | 10 chapters |

The tier only pre-fills the price box. **The parent sets the price when they add the
card**, and the price stored on the card is what is charged, so a parent can price a
card at whatever they like. Repricing a card afterwards never changes what a reader
already paid for it.

## Install

Python 3.13, pinned in `.python-version`.

```fish
uv venv
source .venv/bin/activate.fish
uv pip install -r requirements.txt
```

`requirements.txt` is a real `pip freeze` taken inside the project's own virtual
environment, so it lists only what the app imports. On bash, the activation line is
`source .venv/bin/activate`.

## Set up the database

A fresh clone has no database, no cached card pictures and no cached set list. Three
commands, and they go in this order:

```fish
flask --app chapters init-db                  # 1. creates the tables
flask --app chapters refresh-sets             # 2. caches the set list
flask --app chapters create-parent <name>     # 3. the parent account
```

1. **`init-db`** drops and recreates the tables. It is safe to re-run, but it clears
   everything, so it is not a migration.
2. **`refresh-sets`** fetches the catalogue's own set list, all 220 sets, and caches
   it in the database so the Add-a-card dropdown keeps working offline. **Until it
   has run, that dropdown offers only "Any set"**, because a brand new database has
   nothing cached. Re-running is safe: sets are updated in place, and a set the
   catalogue no longer lists is removed.
3. **`create-parent <name>`** makes the one kind of account that has a password. It
   asks for the password twice, hidden. Readers have no password at all, and are
   added from the Readers page by a parent.

With no virtual environment active, the same three commands are
`.venv/bin/flask --app chapters ...`.

## Run it

```fish
flask --app chapters run --debug
```

`app.py` is also a direct entry point: `python app.py` starts the same server. It
exists so the app can be run without the Flask command line, and it builds the app
through `create_app()` exactly as the command line does.

## How it is used

**A reader.** Opens the app and lands on the front page, "Who is reading?", which
lists the readers by name. Tapping a name starts that reader's session, with no
password. The navbar then gives them My wallet, which is the balance together with
the statement of everything earned and spent, My books, which lists their books with
how many chapters are logged in each, Shop, where they spend chapters, and My cards,
the collection they have bought.

**A parent.** Logs in at `/auth/login` with a username and password. The navbar then
gives them Shop, the storefront, Manage, the stock with a control per card to take it
out of the shop or put it back, Add cards, which searches the TCGdex catalogue and
adds a card, and Readers, which lists the readers with a form to add one and a
control to take one off the list.

Taking a card out of the shop never deletes it. The row stays, because purchases
point at it and a card that somebody already owns must not vanish from under them.

## The trust model

Readers have no passwords, and anyone who can reach the app on the home network can
pick a reader's name and start spending their chapters. A reading can also be logged
more than once: there are no chapter numbers, so nothing compares one entry against
another.

That is deliberate. This is a home app used by one family on their own network, the
readers are children who should not have to type a password, and the ledger is a
shared family record rather than a defence against the people using it. The one
account with a password is the parent's, because that is the account that runs the
shop and manages the readers.

## AI Usage

_To be written by Sam and pasted in here._
