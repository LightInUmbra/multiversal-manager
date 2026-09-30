"""
Recognizing a card from the text read off a photo of it (the phone app's scanner reads the
text on the phone, see mobile/card_reader): the name is the title at the top of the card,
matched against every card name, allowing for misread letters; modern cards also print their
set code and collector number in the bottom corner ("0263 R" over "C21 • EN"), which picks
the exact printing.
"""

# Imports
import difflib
import re

# How alike a misread title has to be to a real card name to count as it (0-1)
NAME_CUTOFF = 0.8
TITLE_LINES = 5  # the lines nearest the top that could be the title
LANGUAGES = "EN|DE|FR|IT|ES|SP|PT|JA|JP|KO|RU|CS|CT|PH"
_SET_LINE = re.compile(rf"\b([A-Z0-9]{{3,5}})\s*[•·*.\-]?\s*(?:{LANGUAGES})\b")
_NUMBER = re.compile(r"^\s*0*(\d{1,4})(?:\s*/\s*\d{1,4})?(?:\s+[CURMSLTP])?\s*$")


def _clean(text, strip_cost=True):
    # A title as read: curly apostrophes straightened, stray symbols and a trailing mana
    # cost read as digits ("Sol Ring 1") dropped; strip_cost=False keeps the numbers, for
    # names that end in one ("Pip-Boy 3000")
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[^A-Za-z0-9',\- ]", " ", text)
    if strip_cost:
        text = re.sub(r"(\s+[0-9XWUBRGC]{1,6})+\s*$", "", text)  # mana symbols are capitals; names' words aren't
    return re.sub(r"\s+", " ", text).strip()


class Names:
    """Every card name, for matching titles read off photos. Two-faced cards ("Delver of
    Secrets // Insectile Aberration") are found by either face."""

    def __init__(self, names):
        # A card's own name comes first: "Swords to Plowshares" is that card, not the face
        # of "Emeritus of Truce // Swords to Plowshares"
        self.full = {name.lower(): name for name in names}
        for name in names:
            for face in name.split(" // "):
                self.full.setdefault(face.lower(), name)
        self.by_length = {}
        for key in self.full:
            self.by_length.setdefault(len(key), []).append(key)

    def match(self, title):
        """The card name a title read off a photo stands for, or None"""
        # Without the mana cost first, then as read, in case the name itself ends in a number
        keys = [k for k in dict.fromkeys([_clean(title).lower(), _clean(title, strip_cost=False).lower()])
                if len(k) >= 3]
        exact = next((self.full[k] for k in keys if k in self.full), None)
        if exact:
            return exact
        for key in keys:
            # Only names of about the same length can be close, which keeps this quick
            nearby = [k for n in range(len(key) - 3, len(key) + 4) for k in self.by_length.get(n, ())]
            close = difflib.get_close_matches(key, nearby, n=1, cutoff=NAME_CUTOFF)
            if close:
                return self.full[close[0]]
        return None


def identify(lines, names):
    """(card name or None, set code or None, collector number or None) for the text lines
    read off a photo of a card: dicts with "text" and "top" (pixels from the top)"""
    lines = sorted(lines, key=lambda l: l["top"])
    titles = [l["text"] for l in lines if len(re.findall(r"[A-Za-z]", l["text"])) >= 3][:TITLE_LINES]
    name = next((found for title in titles if (found := names.match(title))), None)
    set_code = number = None
    if lines:
        # The bottom corner: the lower part of the text that was read
        bottom = lines[0]["top"] + (lines[-1]["top"] - lines[0]["top"]) * 0.6
        corner = [l["text"] for l in lines if l["top"] >= bottom]
        set_code = next((m.group(1) for t in corner if (m := _SET_LINE.search(t))), None)
        number = next((m.group(1) for t in corner if (m := _NUMBER.match(t))), None)
    return name, set_code, number
