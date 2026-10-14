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

### Optional: demo data

```fish
flask --app chapters seed-demo
```

This adds sixteen cards, three readers with some reading logged, and a couple of
purchases, so a fresh clone has something to look at without adding a card by hand
first. It exists only for that, and the app does not need it.

It is safe to run twice: a card or a reader that is already there is reported and left
alone. It never creates a parent account, and no password is written into the source,
so if there is no parent yet it says so and points at `create-parent`. With no
connection it still adds the cards and readers, and says that the pictures were not
cached.

With no virtual environment active, the same commands are
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

### What the AI wrote

Claude Code wrote the application code. I gave it the assignment requirements and a
`CLAUDE.md` in the project describing the rules the app has to hold, and it produced
the application factory, the four blueprints, the templates, the schema and the
routes.

Specifically from the AI:

- The application factory in `chapters/__init__.py` and the blueprint layout.
- `schema.sql` and the connection handling in `chapters/db.py`, including the teardown
  close and the `init-db` command.
- Registration, login, logout, and the `login_required` and `parent_required` wrappers.
- The wallet statement query.
- The shop, the TCGdex lookup, and the caching of card pictures.

### What I decided about the app's rules

This app is a real one for my family rather than a demonstration, and that shaped most
of these.

- **The currency is chapters.** My kids read books and earn one chapter per chapter
  they finish. My wife and I own the physical Pokemon cards, and the kids spend
  chapters on them at 1, 5 or 10 depending on the card.
- **A parent sets the price when adding a card.** The tier only fills in the price box
  as a suggestion. I did not want the price derived from the tier, because repricing a
  card would then rewrite what a kid had already paid.
- **The wallet is a statement, not a number.** A kid sees every reading and every
  purchase, not just a total.
- **Readers have no passwords.** The app runs on our home network. Kids pick their name
  from a list, and only the parent account has a username and password.
- **We log how many chapters were read, not which chapter.** Three chapters in one
  sitting is one entry worth three.
- **Removing a reader hides them rather than deleting them.** Their reading history, and
  the cards they already own, have to survive.

### What I decided about the interface and the flow

The look and the navigation are mine as well. I asked for each of these and had them
implemented, and in several cases I was correcting something that had already been
built.

- **The app opens on the reader list.** It used to open on the parent's login form, so
  the first thing a child saw was a password box they could not use. I had every
  signed-out page send them to the list of names instead, and a parent now clicks once
  to reach their login.
- **The tabs.** A reader gets My wallet, My books, Shop and My cards. A parent gets
  Shop, Manage, Add cards and Readers. Before that every page worked and the navbar
  linked to none of them, so the shop could only be reached by typing its address.
- **Nothing is linked twice.** I had every button removed that repeated a tab already in
  the navbar. That is where "My books" beside "Log reading" came from, and the same for
  "Back to my wallet" on the books page.
- **The words.** "Remove" and "Put back" instead of "Take off sale", with the status
  badge worded to agree with them. The reader list tells a child to ask a grown-up
  rather than linking to a parent login, because a child is the one reading that page.
- **The look.** I chose the colours from the back of a Pokemon card, the deep blue with a
  gold line, and then from a comic poster for the brighter tones. Thick black outlines
  and hard offset shadows, and the three card tiers each get their own colour so a kid
  can tell at a glance what a card costs.
- **Paging and search.** The shop listed every card in one long page. I had a page size
  with forward and back, and a search box, on both the shop and the parents' stock.
- **A set dropdown.** Adding a card asked for the set as typed text, but a set id is not
  guessable: Base Set is `base1`, and the thirtieth anniversary sets are `30th` and
  `30th-c`. I had it changed to a dropdown of the catalogue's own set list.
- **Pictures while searching, and cached afterwards.** A search showed a card's name and
  number with no picture, so a parent could not tell which printing they were picking.
  The results now show a picture, and say so when a card has none. And because those
  pictures were being loaded from the internet on every page view, I had them downloaded
  once when a card is added and served by the app afterwards, so the shop works with no
  internet at all.
- **One total, not a running balance.** The wallet repeated a balance on every row. I
  had that replaced with the change for each entry and a single total at the bottom.
- **Parents manage the readers.** Children used to be able to add themselves. I had that
  moved behind the parent account, with the reader list inviting a child to ask a
  grown-up.
- **The name.** I chose Pages for Pokemon.

### What I checked by running the app

I checked the behaviour by running it rather than by reading the code.

- Every page returns 200 for the role that should reach it, and paths that should not
  exist return 404.
- The wallet's total always equals what the statement adds up to.
- A reader cannot add a reading to another reader's book, tested by posting someone
  else's book id.
- A reader cannot reach the parent pages, by clicking or by posting a crafted form.
- A parent cannot buy a card, and a signed-out visitor cannot reach the shop.
- The card pictures are served by the app from its own folder, and none of them are
  committed to the repository.

### What I changed in the AI-generated code

Four things the AI shipped that I had fixed. Each came out of testing the app rather
than reading it.

**1. A chapter could be logged more than once.** The uniqueness rule on a book title
compared case-sensitively. In practice `Wings of Fire`, `wings of fire` and
`Wings  of Fire` were three different books, and one chapter could be logged six times
under six spellings. I had `COLLATE NOCASE` added to the constraint, and the title
trimmed before it is stored.

**2. Timestamps were stored in UTC.** SQLite's `CURRENT_TIMESTAMP` is UTC. A chapter my
kid logged at 7pm was stamped with the next day's date on the wallet page. I had the
schema defaults changed to write local time. I also chose to fix this at storage rather
than when displaying, because a display-time fix has to be remembered on every page
that shows a time, and the next page to forget it becomes a bug nobody notices.

**3. Two purchases at the same moment could overdraw a balance.** The buy route read the
balance and then inserted the purchase. Those are two separate statements, so two quick
clicks could both pass the same check and spend chapters twice. I had the check moved
inside the insert so the database evaluates both at once.

**4. The shop said "1 chapters".** It also printed the raw database value `full_art` on a
card badge, underscore and all. I had both fixed, and the count words put in one place
so the singular and plural cannot disagree between pages.

### What the AI did not write

The `CLAUDE.md` in this repository is mine, though Claude Code helped with its wording.
It states what has to be true about the app rather than how to build it.
