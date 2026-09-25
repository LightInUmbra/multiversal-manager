"""
Condition and language of the copies in a collection entry, plus reading them from
the many spellings other tools export ("Near Mint", "near_mint", "NM", "JP", …).
"""

# TCGplayer-style grades, best first: code -> name
CONDITIONS = {
    "NM": "Near Mint",
    "LP": "Lightly Played",
    "MP": "Moderately Played",
    "HP": "Heavily Played",
    "DMG": "Damaged",
}
DEFAULT_CONDITION = "NM"

# Scryfall's language codes -> name
LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
    "ru": "Russian",
    "zhs": "Chinese (Simplified)",
    "zht": "Chinese (Traditional)",
    "he": "Hebrew",
    "la": "Latin",
    "grc": "Ancient Greek",
    "ar": "Arabic",
    "sa": "Sanskrit",
    "ph": "Phyrexian",
}
DEFAULT_LANGUAGE = "en"


def _key(text):
    return "".join(c for c in (text or "").lower() if c.isalnum())


# Other tools' spellings (after _key) -> condition code. Cardmarket's grades are
# mapped to their closest TCGplayer equivalent.
_CONDITION_ALIASES = {
    **{_key(code): code for code in CONDITIONS},
    **{_key(name): code for code, name in CONDITIONS.items()},
    "m": "NM", "mint": "NM", "mt": "NM", "nearmintmint": "NM",
    "ex": "LP", "excellent": "LP", "sp": "LP", "slightlyplayed": "LP", "goodlightlyplayed": "LP",
    "gd": "MP", "good": "MP", "played": "MP", "pl": "HP",
    "damage": "DMG", "dm": "DMG", "d": "DMG", "po": "DMG", "poor": "DMG",
}

_LANGUAGE_ALIASES = {
    **{_key(code): code for code in LANGUAGES},
    **{_key(name): code for code, name in LANGUAGES.items()},
    "jp": "ja", "kr": "ko", "cn": "zhs", "zh": "zhs", "zhcn": "zhs", "zhhans": "zhs", "chinese": "zhs",
    "simplifiedchinese": "zhs", "chinesesimplified": "zhs", "tw": "zht", "zhtw": "zht", "zhhant": "zht",
    "traditionalchinese": "zht", "chinesetraditional": "zht",
    "ptbr": "pt", "portuguesebrazil": "pt", "brazilianportuguese": "pt", "sp": "es",
}


def parse_condition(text):
    # Condition code for an exported value; blank or unrecognized counts as Near Mint
    return _CONDITION_ALIASES.get(_key(text), DEFAULT_CONDITION)


def parse_language(text):
    # Language code for an exported value; blank or unrecognized counts as English
    return _LANGUAGE_ALIASES.get(_key(text), DEFAULT_LANGUAGE)


def language_label(code):
    return LANGUAGES.get(code, code)
