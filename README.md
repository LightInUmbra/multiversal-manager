# Multiversal Manager

**Your Magic: The Gathering collection, its value, and the whole card market, in one place.**

Multiversal Manager is an independent, original collection manager and market tracker for Magic: The Gathering, created by Umbra Ortiz ([LightInUmbra](https://github.com/LightInUmbra)). It records exactly which printings and finishes you own, what they're worth today, and how their prices have moved. A separate Finance view follows prices across every paper printing ever made.

The desktop app comes first. Web and mobile versions are planned, and all three are meant to share a single collection (see [The Multiverse](#the-multiverse) below).

---

## What it does

### Your collection

- **Printing-exact entries.** Type a card name and suggestions appear as you go. Pick the exact printing and finish you own, and the set, collector number, rarity, artist and price fill in on their own.
- **Condition, language and notes.** Record each entry's condition (NM, LP, MP, HP, DMG) and language, and add notes like "signed" or "in the red binder". Copies of the same printing in a different condition or language get their own entry. Imports read these from other tools' CSV exports too.
- **Live value.** A running total of what your collection is worth, with card counts and each card's price movement over the last 24 hours, 7, 30 or 90 days, or all time.
- **Price history per card.** Select any card to chart its price over time. Movement counts market changes only; adding or removing cards never shows up as a gain or loss.
- **Trends** (Ctrl+T). Your collection's value over time, plus its biggest gainers and losers.
- **Import anything.** CSV exports from Moxfield, ManaBox, Deckbox and most other tools (columns are matched by header name), or plain text lists like `4 Lightning Bolt` or `1x Sol Ring (C21) 263 *F*`. Every entry goes through a review step before it's saved, and entries whose printing isn't certain are listed first, with a card preview to help you choose.
- **Export** your collection to CSV at any time.
- **Deck Builder** (Ctrl+L). Build decks for any format: Standard, Pioneer, Modern, Legacy, Vintage, Pauper, Commander, Oathbreaker, Brawl and the other formats Scryfall tracks, plus binders and wishlists. Three panels: the selected card's details (rules text, legality, how many you own, −1 / +1), the deck grouped by section, and a card list with *My Cards* (your collection) and *Explore* (every card in Magic) with search, type, color and "legal for this deck" filters. Every deck is checked against its format as you build: deck and sideboard size, copy limits (basic lands and "any number" cards aside), banned and restricted cards, and commander eligibility and color identity. Cards you don't own are marked, and each list shows what it's worth and what the missing cards would cost. Deck lists import from Arena, Moxfield and most other tools, and export as standard text. The card database (about 80 MB from Scryfall) downloads once and updates weekly.
- **Automatic backups.** Your collection is backed up once a day when the app starts, and the last 10 backups are kept. *File → Back Up Now* makes one on demand, and *File → Restore from Backup…* rolls back to any of them, saving your current collection first so a restore can be undone too. Backups are small (a few MB to tens of MB) because they leave out market price history that can be downloaded again.
- **Quick edits.** Right-click or double-click a card to change its printing, finish, quantity or price. Adding a printing you already own increases its quantity instead of creating a duplicate.

### Finance

A market view of Magic prices (Ctrl+Shift+F).

- **Spikes and drops.** The biggest movers over any period, for each printing and finish (non-foil, foil, etched), with a minimum-price filter to cut out penny-card noise.
- **Two ways to start.** *Track Every Card* follows all ~160,000 paper printings and finishes, and picks up new ones as they're released. *Start Empty* follows nothing until you choose. Both load the full card database, so switching later is instant.
- **Curate freely.** Add single printings, every printing of a card, or whole sets with *Track Cards…*. Remove a printing or an entire set with Delete or a right-click. Price history is kept either way.
- **History from day one.** The first launch downloads 90 days of price history for every card, so trends appear immediately. From then on the app records every daily price, and the history keeps growing.

> The first time Finance opens, it downloads about 140 MB (card data plus 90 days of price history) and the database grows to a few hundred MB. Prices update once a day, as often as the data sources publish them.

---

## The Multiverse

Multiversal Manager is planned as a set of connected apps built around one collection:

| Platform | Status |
|---|---|
| **Desktop** | In active development: this repository |
| **Web** | Planned |
| **Mobile** | Planned |

The goal is for the desktop, web and mobile versions to stay in sync, so a card added on your phone at a store shows up on your desktop at home. The desktop app keeps everything in a local SQLite database today, with the card and price logic kept separate from the interface so it can later be shared with a sync service.

### Coming next on desktop

- Card image grid view
- A standalone Windows installer

---

## Getting started

Multiversal Manager uses [Magic-Projects](https://github.com/LightInUmbra/Magic-Projects), a companion Scryfall toolkit by the same author, as a git submodule. Clone with submodules:

```
git clone --recurse-submodules https://github.com/LightInUmbra/multiversal-manager.git
cd multiversal-manager
```

(Already cloned without them? Run `git submodule update --init`.)

Create a virtual environment, install dependencies and launch:

```
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
python main.py
```

Your data stays on your machine. The collection and price history live in `collection.db` next to `main.py`, backups go in `backups/`, and card images are cached in `image_cache/`. All three are git-ignored.

### Tests

```
python -m pytest
```

---

## Under the hood

```
multiversal-manager/
    main.py                  # Main window: collection table, card details, totals
    finance.py               # Finance window: market tracking, spikes and drops, daily updates
    lists.py                 # Deck Builder: decks, binders and wishlists
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

Card data, images and daily prices come from [Scryfall](https://scryfall.com). Historical prices come from [MTGJSON](https://mtgjson.com). Thank you to both projects for making this data openly available. Card images are always shown whole, so the artist credit and copyright line stay visible. Prices are market estimates and aren't guaranteed to be accurate.

Multiversal Manager is unofficial Fan Content permitted under the [Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.
