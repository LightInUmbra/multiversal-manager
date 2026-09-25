# Multiversal Manager

**Your Magic: The Gathering collection, what it's worth, and the whole card market, all in one place.**

Hi! I'm Umbra ([LightInUmbra](https://github.com/LightInUmbra)), and this is the collection manager I always wanted and could never quite find. It keeps track of exactly which printings and finishes you own, what they're worth today, and how their prices have moved over time. There's also a Finance view for when you want to see what the whole market is doing, not just your binder.

Right now it's a desktop app. Web and mobile versions are on the way, and the plan is for all three to share one collection (more on that in [The Multiverse](#the-multiverse)).

---

## What it does

### Your collection

- **Exact printings, not just card names.** Start typing a card and suggestions pop up. Pick the printing and finish you actually own, and the set, collector number, rarity, artist and price get filled in for you.
- **Condition, language and notes.** Mark each entry NM, LP, MP, HP or DMG, set its language, and jot down things like "signed" or "in the red binder". If you have the same printing in two conditions or languages, each gets its own entry. Imports pick these up from other tools' CSV files too.
- **Live value.** A running total of what your collection is worth, plus card counts and how each card's price has moved over the last 24 hours, 7, 30 or 90 days, or all time.
- **Price history for every card.** Click a card to see its price chart. Only real market changes count as movement, so adding or removing cards never looks like a gain or a loss.
- **Trends** (Ctrl+T). How your collection's value has changed over time, along with your biggest winners and losers.
- **Bring your collection with you.** Import CSV exports from Moxfield, ManaBox, Deckbox and most other tools (columns are matched by their headers), or paste a plain list like `4 Lightning Bolt` or `1x Sol Ring (C21) 263 *F*`. You get to review everything before it's saved, and any card where the printing is a guess shows up first, with a picture to help you pick the right one.
- **Export** to CSV whenever you like.
- **Quick edits.** Right-click or double-click a card to change its printing, finish, quantity or price. Adding a printing you already own just bumps the quantity instead of making a duplicate.
- **Automatic backups.** The app backs up your collection once a day when it starts and keeps the last 10. Want one right now? *File → Back Up Now*. Need to go back? *File → Restore from Backup…* rolls you back, and saves your current collection first so you can undo the restore too. Backups stay small (a few MB up to tens of MB) because they skip price history that can just be downloaded again.

### Deck Builder

Open it with Ctrl+L. It works for Standard, Pioneer, Modern, Legacy, Vintage, Pauper, Commander, Oathbreaker, Brawl and every other format Scryfall tracks, and you can make binders and wishlists there too.

- **Three panels.** The selected card's details (rules text, legality, how many you own, and −1 / +1 buttons), your deck grouped by section, and a grid of card images to build from, each showing how many copies you own.
- **Build from what you have, or from everything.** *My Cards* shows your collection, *Explore* shows every card in Magic. Search, filter by type, color, or "legal for this deck", and sort however you like.
- **Pick your printing.** Choosing a different printing opens a picker with every version of the card: its image, set, rarity, and the price of each finish, plus how many you own.
- **Legality checks as you go.** Deck and sideboard size, copy limits (with exceptions for basic lands and "any number" cards), banned and restricted cards, and commander eligibility and color identity are all checked while you build.
- **Know what's missing.** Cards you don't own are marked, and every list shows what it's worth and what the missing cards would cost you.
- **Import and export.** Deck lists from Arena, Moxfield and most other tools import fine, and export as standard text.
- **Lightweight mode.** On a slower computer or connection? *View → Lightweight* swaps the images for a plain table that doesn't download any pictures.

The card database (about 80 MB from Scryfall) downloads once and then refreshes weekly.

### Finance

Your window into the wider Magic market (Ctrl+Shift+F).

- **Spikes and drops.** The biggest movers over any time period, for every printing and finish (non-foil, foil, etched). A minimum-price filter keeps penny cards from cluttering things up.
- **Two ways to start.** *Track Every Card* follows all ~160,000 paper printings and finishes and picks up new ones as they come out. *Start Empty* tracks nothing until you tell it to. Either way the full card database gets loaded, so switching later is instant.
- **Track what you care about.** Add a single printing, every printing of a card, or entire sets with *Track Cards…*. Remove a printing or a whole set with Delete or a right-click. Price history sticks around either way.
- **History from day one.** The first launch grabs 90 days of price history for every card, so you get trends right away. After that the app saves each day's prices and the history just keeps growing.

> Heads up: the first time you open Finance it downloads about 140 MB (card data plus 90 days of prices), and the database grows to a few hundred MB. Prices update once a day, as often as the data sources publish them.

---

## The Multiverse

The bigger idea is a set of connected apps that all share the same collection:

| Platform | Status |
|---|---|
| **Desktop** | In active development (you're looking at it) |
| **Web** | Planned |
| **Mobile** | Planned |

The goal: add a card on your phone while you're at the store, and it's already there on your desktop when you get home. For now the desktop app keeps everything in a local SQLite database, with the card and price logic kept separate from the interface so it can be plugged into a sync service later.

### Coming next on desktop

- Card image grid view
- A standalone Windows installer

---

## Getting started

Multiversal Manager uses [Magic-Projects](https://github.com/LightInUmbra/Magic-Projects), a Scryfall toolkit I also wrote, as a git submodule. So clone it with submodules:

```
git clone --recurse-submodules https://github.com/LightInUmbra/multiversal-manager.git
cd multiversal-manager
```

(Already cloned without them? No problem, just run `git submodule update --init`.)

Then set up a virtual environment, install the dependencies, and launch:

```
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
python main.py
```

Your data never leaves your machine. Your collection and price history live in `collection.db` next to `main.py`, backups go in `backups/`, and card images are cached in `image_cache/`. All three are git-ignored.

### Running the tests

```
python -m pytest
```

---

## Under the hood

For the curious, here's how things are laid out:

```
multiversal-manager/
    main.py                  # Main window: collection table, card details, totals
    finance.py               # Finance window: market tracking, spikes and drops, daily updates
    lists.py                 # Deck Builder: decks, binders and wishlists
    card_browser.py          # Card image grid / lightweight table, and the printing picker
    formats.py               # Formats and deck legality rules
    trends.py                # Price change math and the Trends window
    database.py              # SQLite storage, price history and schema upgrades
    backup.py                # Daily backups, Back Up Now and Restore
    importer.py              # CSV / text list parsing and printing matching
    copy_details.py          # Conditions and languages, and reading them from other tools
    import_review_dialog.py  # Review step for imports
    add_card_dialog.py       # Add / Edit Card with live name suggestions
    printing_picker.py       # Printing, finish and price picker with card preview
    card_image.py            # Card images, loaded in the background and never cropped
    charts.py                # Price and value history charts
    scryfall.py              # Card data, prices, images and bulk downloads
    mtgjson.py               # 90-day price history backfill
    background.py            # Keeps network work off the interface thread
    external/
        Magic-Projects/      # Submodule: the ScryFunctions toolkit and Card class
    tests/
```

**Built with** Python 3, PySide6 (Qt for Python), QtCharts and SQLite.

---

## Credits and legal

Card data, images and daily prices come from [Scryfall](https://scryfall.com), and historical prices come from [MTGJSON](https://mtgjson.com). A huge thank you to both for making this data freely available; this app wouldn't exist without them. Card images are always shown in full so the artist credit and copyright line stay visible. Prices are market estimates, so please don't treat them as gospel.

Multiversal Manager is unofficial Fan Content permitted under the [Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.
