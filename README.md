# Multiversal Manager

A desktop app for tracking a Magic: The Gathering card collection: what you own, which printings, and what it's worth. Built with PySide6 and SQLite, with live card data and images from [Scryfall](https://scryfall.com).

## Features

- **Scryfall-powered Add Card**: start typing a name and suggestions appear as you type. Pick the exact printing you own (every paper printing is listed) and the set, finish and current price fill in automatically.
- **Card images**: see a full card preview while adding and when selecting a card in your collection. Images are cached locally after the first load.
- **Collection value**: a running total of your collection's value, plus total and unique card counts.
- **Price refresh**: prices older than 24 hours update automatically on startup, or on demand with *Refresh Prices*. Foil and non-foil copies are priced separately.
- **Quick editing**: double-click a quantity to change it. Adding a printing you already own increases its quantity instead of creating a duplicate row.
- **Filter and sort**: filter by name, set or artist, and sort by any column.
- **Export**: save your collection to CSV (File → Export to CSV…).
- **View on Scryfall**: open the selected printing's Scryfall page.

## Setup

This repo includes [Magic-Projects](https://github.com/LightInUmbra/Magic-Projects) as a git submodule, which supplies the `ScryFunctions` Scryfall wrapper. Clone with submodules:

```
git clone --recurse-submodules https://github.com/LightInUmbra/multiversal-manager.git
cd multiversal-manager
```

(If you've already cloned without submodules, run `git submodule update --init`.)

Then create a virtual environment and install dependencies:

```
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Mac/Linux
pip install -r requirements.txt
python main.py
```

Your collection is saved to `collection.db` next to `main.py`. Downloaded card images are cached in `image_cache/`. Both are git-ignored.

### Running tests

```
python -m pytest
```

## Project Structure

```
multiversal-manager/
    main.py               # Main window: collection table, details panel, totals
    add_card_dialog.py    # Add Card dialog with Scryfall autocomplete + printing picker
    card_image.py         # Card image widget (async loading, never crops the card)
    scryfall.py           # Adapter over ScryFunctions + autocomplete, prices, images
    background.py         # Runs network calls off the GUI thread
    database.py           # SQLite storage and schema migrations
    external/
        Magic-Projects/   # Submodule: ScryFunctions.py and the Card class
    tests/
```

## Built With

- Python 3
- PySide6 (Qt for Python)
- SQLite
- Scryfall API via `requests`

## Credits & Legal

Card data, prices and images are provided by [Scryfall](https://scryfall.com). Card images are always shown whole, so the artist credit and copyright line stay visible. They are scaled, never cropped. Prices are Scryfall's daily estimates and are not guaranteed to be accurate.

Multiversal Manager is unofficial Fan Content permitted under the [Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.
