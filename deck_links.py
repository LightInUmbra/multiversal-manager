"""
Deck lists from a link, as text importer.parse_text reads: Archidekt (exact printings, from
its API) and MTGGoldfish (its text download). Moxfield, TappedOut and AetherHub turn automated
requests away, so their links get a message to copy the list and paste it instead.

The desktop and phone apps fetch the sites directly. A web page may only read sites that allow
it, and these don't, so the website asks the deck-link Supabase Edge Function
(supabase/functions/deck-link) to fetch them.
"""

# Imports
import re

import requests

HEADERS = {"User-Agent": "MultiversalManager/1.0 (github.com/LightInUmbra/multiversal-manager)"}
TIMEOUT = 20
RELAY = "https://aepdyzawmgpwcmxytocu.supabase.co/functions/v1/deck-link"  # the website's go-between
BLOCKED = {"moxfield.com": "Moxfield", "tappedout.net": "TappedOut", "aetherhub.com": "AetherHub"}
_ARCHIDEKT = re.compile(r"archidekt\.com/(?:api/)?decks/(\d+)")
_GOLDFISH = re.compile(r"mtggoldfish\.com/deck/(?:download/|visual/)?(\d+)")
_URL = re.compile(r"^\s*https?://\S+\s*$")
# Archidekt's categories that are deck sections of their own; anything else is the main deck
_ARCHIDEKT_SECTIONS = {"Commander": "Commander", "Sideboard": "Sideboard", "Maybeboard": "Maybeboard",
                       "Companion": "Companion"}
_FINISH = {"Foil": " *F*", "Etched": " *E*"}


class LinkError(Exception):
    """A link that can't be read, with a sentence saying why (shown as is)."""


def is_link(text):
    return bool(_URL.match(text or ""))


def source(url):
    """(site, the address that returns the list) for a deck link, or LinkError."""
    for host, site in BLOCKED.items():
        if host in url:
            raise LinkError(f"{site} doesn't let apps read its decks. On {site}, use Export to copy the list, "
                            "then paste it here.")
    if match := _ARCHIDEKT.search(url):
        return "archidekt", f"https://archidekt.com/api/decks/{match.group(1)}/"
    if match := _GOLDFISH.search(url):
        return "goldfish", f"https://www.mtggoldfish.com/deck/download/{match.group(1)}"
    raise LinkError("Links from Archidekt and MTGGoldfish can be imported. For other sites, copy the deck list "
                    "and paste it here.")


def archidekt_text(data):
    """(deck name, text) from Archidekt's deck JSON: each card with its set, number and finish,
    under its section; cards in categories left out of the deck go to the Maybeboard."""
    left_out = {c["name"] for c in data.get("categories") or [] if not c.get("includedInDeck", True)}
    sections = {}
    for entry in data.get("cards") or []:
        card = entry["card"]
        categories = entry.get("categories") or []
        section = next((_ARCHIDEKT_SECTIONS[c] for c in categories if c in _ARCHIDEKT_SECTIONS), None)
        if section is None:
            section = "Maybeboard" if categories and categories[0] in left_out else "Main"
        edition = (card.get("edition") or {}).get("editioncode", "")
        line = f"{entry['quantity']} {card['oracleCard']['name']}"
        if edition and card.get("collectorNumber"):
            line += f" ({edition.upper()}) {card['collectorNumber']}"
        sections.setdefault(section, []).append(line + _FINISH.get(entry.get("modifier"), ""))
    order = ["Commander", "Companion", "Main", "Sideboard", "Maybeboard"]
    blocks = ["\n".join(["Deck" if s == "Main" else s] + sections[s]) for s in order if s in sections]
    return data.get("name"), "\n\n".join(blocks) + "\n"


def goldfish_text(body):
    """(None, text) from MTGGoldfish's download: the main deck, a blank line, the sideboard."""
    main, _, side = body.replace("\r\n", "\n").strip().partition("\n\n")
    return None, "Deck\n" + main + ("\n\nSideboard\n" + side if side.strip() else "") + "\n"


def fetch(url, relay=False, key=None):
    """(deck name or None, deck list text) for a deck link. relay: go through the website's
    Edge Function (key: the Supabase key it needs). Raises LinkError or requests errors."""
    site, target = source(url)
    if relay:
        response = requests.get(RELAY, params={"url": target}, timeout=TIMEOUT,
                                headers={"apikey": key or "", "Authorization": f"Bearer {key or ''}"})
    else:
        response = requests.get(target, headers=HEADERS, timeout=TIMEOUT)
    if response.status_code == 404:
        raise LinkError("That deck wasn't found. Is it private, or was it deleted?")
    response.raise_for_status()
    return archidekt_text(response.json()) if site == "archidekt" else goldfish_text(response.text)
