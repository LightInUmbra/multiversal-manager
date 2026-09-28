"""
Ask a Rules Question, shared by the desktop's Rules window and the phone app: gathers
everything for a question and decides which answer leads. All offline once the rules are
downloaded. No AI: an answer is a verified ruling (rules_library.json), one worked out from
the rules (judge.py), or the official text.
"""

# Imports
from dataclasses import dataclass

import database as db
import judge
import rules

# How closely a verified ruling has to match a question to be given as its answer; a looser
# match is offered as "the closest verified ruling"
CONFIDENT_MATCH = 0.45
# Shared words can't tell situations apart ("+2/+2 until end of turn" then damage, or then
# flickered), so an answer worked out from the question's own details beats any verified
# ruling that isn't nearly the same question
NEAR_EXACT_MATCH = 0.8


@dataclass
class Findings:
    question: str
    matches: list      # [(score, verified ruling)] from the library, best first
    worked: object     # judge's answer worked out from the rules, or None
    verified: bool     # whether the best match is close enough to lead
    guides: list       # Game Concepts guides for the systems it touches
    cards: list        # [(name, oracle text, [ruling comments])] for the cards it names
    passages: list     # the Comprehensive Rules and glossary entries that govern it

    @property
    def kind(self):
        # Which answer leads: "verified", "worked", "closest" (a looser match) or "none"
        return ("verified" if self.verified else "worked" if self.worked
                else "closest" if self.matches else "none")


def look_up(question, cr, library, card_names, fetch_cards=None):
    """Findings for a question. card_names are every card name to recognize in it. The
    phone app has only some cards' data, so it passes fetch_cards(names), which looks up
    the named cards it doesn't have yet (and stores them) before they're read."""
    terms = [term for term, _ in cr.glossary] + list(cr.keywords())
    mentioned = rules.mentioned_cards(question, card_names, terms)
    if fetch_cards:
        missing = [name for name in mentioned if db.card_info(name) is None]
        if missing:
            fetch_cards(missing)
    named = {name: info for name in mentioned if (info := db.card_info(name)) is not None}
    cards = [(name, info["oracle_text"], [r["comment"] for r in db.card_rulings(name)])
             for name, info in named.items()]
    matches = rules.similar_interactions(question, library)
    creatures = {name: judge.creature_from_card(name, info, cr.keywords()) for name, info in named.items()
                 if "Creature" in (info["type_line"] or "")}
    worked = (judge.answer_brackets(question, named) or judge.answer_tokens(question, named)
              or judge.answer_combat(question, creatures)
              or judge.answer_timing(question, named) or judge.answer_state(question, named))
    guides = rules.guides_for(question + "\n" + "\n".join(text or "" for _, text, _ in cards), library)
    passages = [p for p in rules.find_rules(question, cr, cards, budget=24000) if p.kind in ("rule", "glossary")]
    verified = bool(matches) and matches[0][0] >= (NEAR_EXACT_MATCH if worked else CONFIDENT_MATCH)
    return Findings(question, matches, worked, verified, guides, cards, passages)
