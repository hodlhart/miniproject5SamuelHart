-- INF601 - Advanced Programming in Python
-- Samuel Hart
-- Mini Project 5
--
-- SQLite has no "#" comment, so the usual project header is spelled with "--".

-- TIMESTAMPS ARE LOCAL TIME, NOT UTC
--
-- Every TEXT timestamp below defaults to datetime('now','localtime') rather than
-- to CURRENT_TIMESTAMP. CURRENT_TIMESTAMP is UTC, so in America/Chicago a chapter
-- logged at 19:00 was stored as 00:00 the next day, and the wallet statement
-- showed a kid tomorrow's date.
--
--   The parentheses around the default are required. SQLite only accepts a
--   non-constant default expression when it is parenthesized, so
--   DEFAULT datetime('now','localtime') without them is a syntax error.
--
--   Do not add datetime(x, 'localtime') anywhere on display either. Storing local
--   and converting on read are mutually exclusive: converting an already-local
--   value subtracts the offset a second time, shifting every timestamp by that
--   offset with no error at all. Fix the storage and leave the reads alone.
--
--   The offset is not a constant. datetime('now','localtime') follows daylight
--   saving, so it is five hours in CDT and six in CST. The figures above are the
--   CDT ones. The code is right either way; only the arithmetic in this comment
--   is seasonal.
--
-- Rows written before this change are UTC, so an existing database holds a mix of
-- the two conventions. Re-run init-db rather than reusing one.

-- Re-runnable: children are dropped before parents so no foreign key blocks a drop.
DROP TABLE IF EXISTS purchases;
DROP TABLE IF EXISTS chapters;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS sets;
DROP TABLE IF EXISTS cards;
DROP TABLE IF EXISTS users;

-- Both kids and parents sign in. Kids earn and spend chapters; parents stock
-- the shop and own the cards that are not for sale.
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    -- A parent signs in with a password. A kid has none at all and is picked
    -- from the reader list instead, so this is NULL on every kid row.
    password_hash TEXT,
    role TEXT NOT NULL CHECK (role IN ('kid', 'parent')),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    -- Said here rather than left to the routes, so no route can forget it: a
    -- parent must carry a password, a kid must not, and a row that breaks
    -- either half cannot be written at all.
    CHECK (
        (role = 'parent' AND password_hash IS NOT NULL)
        OR (role = 'kid' AND password_hash IS NULL)
    )
);

-- One row is one book a kid is reading. The title lives here and nowhere else,
-- so one book can never appear as two different strings.
CREATE TABLE books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    -- A kid cannot own the same title twice. COLLATE NOCASE folds ASCII case
    -- only, and it cannot see inside a string, so the route must still collapse
    -- runs of whitespace and trim ends before insert. 'Wings  of Fire' and
    -- ' Wings of Fire' would each slip past this constraint.
    UNIQUE (user_id, title COLLATE NOCASE)
);

-- One row is one reading session: how many chapters of one book a kid finished
-- in a sitting. This is the earning history, and it is the only record of what a
-- kid has earned. The row carries no owner of its own: a kid's chapters are
-- found by joining chapters to books on book_id, so a row cannot claim an owner
-- who does not own the book.
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- RESTRICT, not CASCADE: a book that still holds chapters cannot be
    -- deleted, so tidying up the book list cannot erase earned chapters.
    book_id INTEGER NOT NULL REFERENCES books (id) ON DELETE RESTRICT,
    -- How many chapters this entry is worth, not which chapter it was. There is
    -- no chapter number any more, so there is nothing left for a uniqueness
    -- constraint to compare: logging the same reading twice is accepted, and
    -- every chapter figure in the app is a SUM of this column rather than a
    -- count of rows or a literal one.
    chapter_count INTEGER NOT NULL CHECK (chapter_count > 0),
    logged_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- One row is one physical card in the shop. Two copies of the same card are two
-- rows, exactly as two physical cards are two objects.
CREATE TABLE cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- The catalogue's own identifier, for example base1-4. NOT NULL rather than
    -- merely UNIQUE, because SQLite treats NULLs as distinct in a UNIQUE index,
    -- so a nullable column would let any number of id-less rows duplicate each
    -- other while the real duplicate was correctly refused. Every card in this
    -- shop comes from the catalogue, so the schema says so.
    tcgdex_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    set_name TEXT,
    number TEXT,
    rarity TEXT,
    -- The parents set the price when they add the card, and this is that price.
    price_chapters INTEGER NOT NULL CHECK (price_chapters > 0),
    -- tier is a label only. Its values pre-fill the add-card form as a
    -- convenience, and no code may compute a price from the tier at read time.
    tier TEXT NOT NULL CHECK (tier IN ('normal', 'ex', 'full_art')),
    -- Artwork is a TCGdex URL and is never committed, so this stays nullable.
    -- No part of the app may require it.
    image_url TEXT,
    -- 0 keeps a card visible but unbuyable, which is where the parents' own
    -- collection lives. A CHECK cannot read another table, so the buy handler
    -- is what actually refuses the purchase.
    for_sale INTEGER NOT NULL DEFAULT 1 CHECK (for_sale IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- One row is one card bought, by one kid, at one moment. This is the spending
-- history.
CREATE TABLE purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    -- One shop row is one physical card, and a card is bought at most once.
    card_id INTEGER NOT NULL UNIQUE REFERENCES cards (id),
    -- The price is copied in at purchase time. If a card is later repriced,
    -- what the kid already spent must not change under them.
    -- The CHECK below only says a purchase cost something. It cannot say the
    -- kid could afford it: no static constraint can aggregate the other rows,
    -- so sufficiency of funds is the buy handler's job and nothing here
    -- substitutes for it.
    chapters_spent INTEGER NOT NULL CHECK (chapters_spent > 0),
    purchased_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- A balance reads every purchase for one kid, so that lookup gets an index.
-- The UNIQUE on card_id already indexes the other direction.
CREATE INDEX idx_purchases_user_id ON purchases (user_id);

-- Our own copy of the catalogue's set list, so the Add-a-card dropdown works
-- offline. It lives in this same file rather than a second database, because two
-- files would mean two connections that can drift apart.
--
-- catalog_order is the set's position in the catalogue's own response, which is
-- the ONLY sequencing the API offers: it returns sets oldest first and carries no
-- release date. Ordering the dropdown by this descending puts the newest sets on
-- top, so it is the catalogue's order and not a date.
CREATE TABLE sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    card_count INTEGER NOT NULL,
    catalog_order INTEGER NOT NULL,
    refreshed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- HOW TO READ A BALANCE
--
-- Sum chapter_count with SUM(c.chapter_count), and drive the query from users
-- rather than from books.
--
--   SUM skips the NULLs a LEFT JOIN introduces, so a kid with a book but no
--   chapters reads as 0. COUNT(*) would count the joined row instead and read
--   as 1: a wrong number, not an error, which is what makes it hard to see. Wrap
--   the SUM in COALESCE, because SUM over no rows is NULL and not 0.
--
--   Driven from books, a kid who owns no books matches nothing. Without a
--   GROUP BY that still returns 0, but with one it returns no row at all and
--   the reader gets None. The empty wallet is the first path a new kid hits.
--
--   SELECT u.id, u.username,
--          COALESCE(SUM(c.chapter_count), 0) AS chapters_earned,
--          COALESCE((SELECT SUM(p.chapters_spent) FROM purchases p
--                     WHERE p.user_id = u.id), 0) AS chapters_spent
--     FROM users u
--     LEFT JOIN books b    ON b.user_id = u.id
--     LEFT JOIN chapters c ON c.book_id = b.id
--    WHERE u.id = ?
--    GROUP BY u.id, u.username;
--
-- DELETION IS NARROW BY DESIGN
--
-- Deleting a kid cascades to their books, but books -> chapters is RESTRICT, so
-- the cascade stops there and the delete fails: a kid with reading history
-- cannot be removed. The same holds for a book that still holds chapters and
-- for a card that has already been bought. Earned and spent are a ledger, and
-- only rows nothing depends on can be deleted.
