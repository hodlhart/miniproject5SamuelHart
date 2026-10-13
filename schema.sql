-- INF601 - Advanced Programming in Python
-- Samuel Hart
-- Mini Project 5
--
-- SQLite has no "#" comment, so the usual project header is spelled with "--".

-- Re-runnable: children are dropped before parents so no foreign key blocks a drop.
DROP TABLE IF EXISTS purchases;
DROP TABLE IF EXISTS chapters;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS cards;
DROP TABLE IF EXISTS users;

-- Both kids and parents sign in. Kids earn and spend chapters; parents stock
-- the shop and own the cards that are not for sale.
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('kid', 'parent')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One row is one book a kid is reading. The title lives here and nowhere else,
-- so one book can never appear as two different strings.
CREATE TABLE books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- A kid cannot own the same title twice. COLLATE NOCASE folds ASCII case
    -- only, and it cannot see inside a string, so the route must still collapse
    -- runs of whitespace and trim ends before insert. 'Wings  of Fire' and
    -- ' Wings of Fire' would each slip past this constraint.
    UNIQUE (user_id, title COLLATE NOCASE)
);

-- One row is one chapter a kid finished. This is the earning history, and it
-- is the only record of what a kid has earned. The chapter carries no owner of
-- its own: a kid's chapters are found by joining chapters to books on book_id,
-- so a row cannot claim an owner who does not own the book.
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- RESTRICT, not CASCADE: a book that still holds chapters cannot be
    -- deleted, so tidying up the book list cannot erase earned chapters.
    book_id INTEGER NOT NULL REFERENCES books (id) ON DELETE RESTRICT,
    chapter_number INTEGER NOT NULL CHECK (chapter_number > 0),
    logged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Exact, because book_id is an integer with no case to fold: the same
    -- chapter of the same book cannot be logged twice by one kid.
    UNIQUE (book_id, chapter_number)
);

-- One row is one physical card in the shop. Two copies of the same card are two
-- rows, exactly as two physical cards are two objects.
CREATE TABLE cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    purchased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A balance reads every purchase for one kid, so that lookup gets an index.
-- The UNIQUE on card_id already indexes the other direction.
CREATE INDEX idx_purchases_user_id ON purchases (user_id);

-- HOW TO READ A BALANCE
--
-- Count chapters with COUNT(c.id), and drive the query from users rather than
-- from books.
--
--   COUNT(c.id) skips the NULLs a LEFT JOIN introduces. COUNT(*) counts the
--   joined row instead, so a kid with one book and no chapters reads as having
--   earned 1. A wrong number, not an error, which is what makes it hard to see.
--
--   Driven from books, a kid who owns no books matches nothing. Without a
--   GROUP BY that still returns 0, but with one it returns no row at all and
--   the reader gets None. The empty wallet is the first path a new kid hits.
--
--   SELECT u.id, u.username,
--          COUNT(c.id) AS chapters_earned,
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
