# Mini Project 5 - Chapter Cards

A family app. Kids read books, earn chapters as currency, and spend them on
physical Pokemon cards from their parents' inventory.

The course-root `CLAUDE.md` supplies environment, style and submission rules;
this file adds only what is specific to this project.

## The domain

Two sides to one economy.

**Earning.** A kid logs a chapter they read: the book title, which they type
themselves, and the chapter number. That earns one chapter of credit.

**Spending.** The parents inventory their physical cards into a *bank*. Each
card carries a tier, and the tier sets its price:

| Tier | Price |
|---|---|
| normal | 1 chapter |
| ex | 5 chapters |
| full_art | 10 chapters |

A kid browses the bank and spends chapters to buy a card, which then appears on
their own shelf.

## Rules the app must hold

These are requirements. How they are met is an implementation decision.

- A kid's balance is always exactly the chapters they have earned minus the
  chapters they have spent. It must never be able to disagree with the history
  behind it.
- A kid cannot spend chapters they do not have. Enforced in the request handler,
  not only in the page.
- A kid cannot log the same chapter of the same book twice.
- One row in the bank is one physical card, and a card is bought at most once.
  Duplicates are separate rows.
- A card flagged not-for-sale stays visible but cannot be bought. The parents'
  own collection lives there.

## Card images

Images are referenced by URL from the TCGdex API
(`https://api.tcgdex.net/v2/en`) and are never committed: the artwork is Pokemon
Company IP. Card names, set names, numbers and rarities are facts and are fine
to store.

The image field must be nullable and no part of the app may require it. The
inventory has to work with no network at all.

Use TCGdex, never pokemontcg.io. That service is deprecated, closed to new API
key registration, and its `/v2/sets` endpoint returns HTTP 500. TCGdex needs no
API key, so no credential belongs in this project.

## Running it

```fish
.venv/bin/flask --app chapters init-db
.venv/bin/flask --app chapters run --debug
```
