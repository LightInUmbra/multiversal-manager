import judge


def _card(text, power, toughness, colors="", type_line="Creature"):
    return {"oracle_text": text, "power": power, "toughness": toughness, "colors": colors, "type_line": type_line}


CARDS = {name: judge.creature_from_card(name, card, ["ward", "dash"]) for name, card in {
    "Serra Angel": _card("Flying, vigilance", "4", "4", "W"),
    "Grizzly Bears": _card("", "2", "2", "G"),
    "Giant Spider": _card("Reach", "2", "4", "G"),
    "Typhoid Rats": _card("Deathtouch", "1", "1", "B"),
    "Colossal Dreadmaw": _card("Trample", "6", "6", "G"),
    "Boros Swiftblade": _card("Double strike", "1", "2", "RW"),
    "White Knight": _card("First strike\nProtection from black", "2", "2", "W"),
    "Phantom Warrior": _card("This creature can't be blocked.", "2", "2", "U"),
    "Goblin Heelcutter": _card("Dash {2}{R}\nWhenever this creature attacks, target creature can't block this turn.",
                               "3", "2", "R"),
}.items()}


def ask(question):
    return judge.answer_combat(question, CARDS)


def test_reads_a_cards_own_abilities():
    assert CARDS["Serra Angel"].keywords == {"flying", "vigilance"}
    assert CARDS["White Knight"].protection == {"black"}
    assert CARDS["Phantom Warrior"].unblockable
    # Dash is a keyword; "target creature can't block" is about another creature
    assert not CARDS["Goblin Heelcutter"].keywords and not CARDS["Goblin Heelcutter"].cant_block
    lord = judge.creature_from_card("Lord", _card("Other creatures you control have flying.", "2", "2"))
    assert not lord.keywords


def test_who_can_block():
    assert ask("Can Grizzly Bears block Serra Angel?").verdict == "No"
    assert ask("Can Giant Spider block Serra Angel?").verdict == "Yes"
    assert ask("Serra Angel attacks. Can Grizzly Bears block it?").verdict == "No"
    assert ask("Can Phantom Warrior be blocked by Giant Spider?").verdict == "No"
    assert ask("Can a creature with reach block a creature with flying?").verdict == "Yes"
    worked = ask("Can a 2/2 block a 3/3 with menace?")
    assert worked.verdict == "No" and "702.111b" in worked.rules
    worked = ask("If Typhoid Rats blocks White Knight, does White Knight die?")
    assert worked.verdict.startswith("No") and worked.rules == ["702.16f"]


def test_combat_damage():
    worked = ask("My Colossal Dreadmaw attacks and my opponent blocks with Typhoid Rats. What happens?")
    # Trample assigns only 1 to the 1/1 and the rest to the player; deathtouch kills the Dreadmaw
    assert worked.verdict == "Colossal Dreadmaw dies; Typhoid Rats dies; the defending player takes 5 damage"
    assert {"702.19b", "704.5h"} <= set(worked.rules)
    # Double strike: 1 in the first-strike step, then the Bears strike back at the same time as the second hit
    assert ask("Boros Swiftblade is blocked by Grizzly Bears.").verdict == "Boros Swiftblade dies; Grizzly Bears dies"
    assert ask("A 2/2 with first strike attacks and my 3/3 blocks it.").verdict == "The 2/2 dies; the 3/3 survives"
    assert ask("A 5/5 trampler attacks me and I block with a 1/1 and a 2/2.").verdict.endswith("you take 2 damage")
    # The blocker died to first-strike damage, so double strike + trample hits the player for all of it
    worked = ask("I attack with a 3/3 with double strike and trample, and they block with a 2/2.")
    assert worked.verdict.endswith("takes 4 damage") and "702.19d" in worked.rules
    assert ask("My 4/4 with lifelink is unblocked. What happens?").verdict.endswith("gains 4 life")
    # Infect damage is -1/-1 counters: the 3/3 lives as a 1/1
    assert ask("a 2/2 with infect attacks and is blocked by a 3/3").verdict == "The 2/2 dies; the 3/3 survives"
    assert ask("A 3/3 with indestructible attacks and is blocked by a 4/4.").verdict.startswith("The 3/3 survives")


def test_leaves_other_questions_alone():
    assert ask("What happens when you attack with a creature with first strike and you have a creature in hand "
               "with ninjutsu?") is None
    assert ask("When Serra Angel attacks, does it untap?") is None


ROWS = {
    "Wrath of God": _card("Destroy all creatures. They can't be regenerated.", None, None, "W", "Sorcery"),
    "Counterspell": _card("Counter target spell.", None, None, "U", "Instant"),
    "Llanowar Elves": _card("{T}: Add {G}.", "1", "1", "G", "Creature — Elf Druid"),
    "Brazen Borrower // Petty Theft": _card("Flash\nFlying\nThis creature can block only creatures with flying.\n\n"
                                            "Return target nonland permanent an opponent controls to its owner's "
                                            "hand.", "3", "1", "U",
                                            "Creature — Faerie Rogue // Instant — Adventure"),
    "Goblin Guide": _card("Haste\nWhenever this creature attacks, defending player reveals the top card of their "
                          "library.", "2", "2", "R", "Creature — Goblin Scout"),
    "Liliana of the Veil": _card("+1: Each player discards a card.\n−2: Target player sacrifices a creature.", None,
                                 None, "B", "Legendary Planeswalker — Liliana"),
    "Mother of Runes": _card("{T}: Target creature you control gains protection from the color of your choice until "
                             "end of turn.", "1", "1", "W", "Creature — Human Cleric"),
    "Krosan Grip": _card("Split second\nDestroy target artifact or enchantment.", None, None, "G", "Instant"),
    "Lightning Bolt": _card("Lightning Bolt deals 3 damage to any target.", None, None, "R", "Instant"),
    "Vedalken Orrery": _card("You may cast spells as though they had flash.", None, None, "", "Artifact"),
    "Grizzly Bears": _card("", "2", "2", "G", "Creature — Bear"),
}


def when(question):
    named = {name: row for name, row in ROWS.items() if name.split(" // ")[0].lower() in question.lower()}
    return judge.answer_timing(question, named)


def test_casting_timing():
    worked = when("Can I cast Wrath of God during my opponent's turn?")
    assert worked.verdict == "No" and "307.1" in worked.rules
    assert when("Can I cast Counterspell during my opponent's end step?").verdict == "Yes"
    assert when("Can I cast Llanowar Elves in response to a spell?").verdict == "No"
    assert when("Can I cast Llanowar Elves during my second main phase?").verdict == "Yes, if the stack is empty"
    # Flash on the creature face, not the adventure's instant type
    worked = when("Can I cast Brazen Borrower during my opponent's turn?")
    assert worked.verdict == "Yes" and "702.8a" in worked.rules
    assert when("Can I cast Grizzly Bears during my opponent's turn if I control Vedalken Orrery?").verdict == "Yes"
    assert when("Can I cast a sorcery in response to a spell?").verdict == "No"
    assert when("Can I cast Wrath of God at instant speed?").verdict == "No"
    assert when("Can I cast Lightning Bolt while Krosan Grip is on the stack?").verdict == "No"
    assert when("Can I cast Lightning Bolt during the untap step?").verdict == "No"
    worked = when("Can my opponent cast Wrath of God during my turn?")
    assert worked.verdict == "No" and "their turn" in worked.steps[0]
    assert when("Can I play a land during my opponent's turn?").verdict == "No"


def test_abilities_and_summoning_sickness():
    worked = when("Can I activate Liliana of the Veil's ability during my opponent's turn?")
    assert worked.verdict == "No" and "606.3" in worked.rules
    assert when("Can I activate Mother of Runes during my opponent's turn?").verdict == "Yes"
    assert when("Can I equip a creature during combat?").verdict == "No"
    assert when("Can I tap Llanowar Elves for mana the turn it comes out?").verdict == "No"
    assert when("Can I attack with Goblin Guide the turn it enters?").verdict == "Yes"
    assert when("Can I attack with Grizzly Bears the turn I cast it?").verdict == "No"
    assert when("Can my opponent respond to me playing a land?").verdict == "No"
    assert when("Can my opponent respond to me turning a manifested creature face up?").verdict == "No"


def test_timing_leaves_other_questions_alone():
    # Not about when: no situation in the question
    assert when("Can I cast Counterspell targeting a creature spell?") is None
    assert when("Can I cast Lightning Bolt from my graveyard during my turn?") is None


STATE_ROWS = {
    "Grizzly Bears": _card("", "2", "2", "G", "Creature — Bear"),
    "Darksteel Colossus": _card("Trample, indestructible", "11", "11", "", "Artifact Creature — Golem"),
    "Thalia, Guardian of Thraben": _card("First strike", "2", "1", "W", "Legendary Creature — Human Soldier"),
    "Yuriko, the Tiger's Shadow": _card("", "1", "3", "UB", "Legendary Creature — Human Ninja"),
    "Liliana of the Veil": dict(_card("+1: Each player discards a card.", None, None, "B",
                                      "Legendary Planeswalker — Liliana"), loyalty="3"),
}


def state(question):
    named = {name: row for name, row in STATE_ROWS.items() if name.lower() in question.lower()}
    return judge.answer_state(question, named)


def test_creatures_dying():
    assert state("A 3/3 has 2 damage marked on it and then gets -1/-1. Does it die?").verdict == "Yes, it dies"
    # 0 toughness isn't destruction, so indestructible doesn't help
    worked = state("If my indestructible creature gets -3/-3 and is a 3/3, does it die?")
    assert worked.verdict == "Yes, it dies" and "704.5f" in worked.rules
    assert state("Does Darksteel Colossus die if it's dealt 20 damage?").verdict == "No, Darksteel Colossus survives"
    # Damage and "until end of turn" effects wear off at the same time
    worked = state("My 2/2 got +2/+2 until end of turn and was dealt 3 damage. Does it die at end of turn?")
    assert worked.verdict == "No, it survives" and "514.2" in worked.rules
    assert state("A 2/2 is dealt 1 damage by a creature with deathtouch. Does it die?").verdict == "Yes, it dies"
    assert state("A 3/3 is dealt 2 damage by a creature with infect. Does it survive?").verdict == "Yes, it survives"
    assert state("If a creature has three +1/+1 counters and two -1/-1 counters, what's left?").verdict == \
        "1 +1/+1 counter"
    assert state("Grizzly Bears has two +1/+1 counters and gets 3 -1/-1 counters. Does it die?").verdict == \
        "No, Grizzly Bears survives"


def test_players_losing():
    worked = state("If I'm at 0 life, can I gain life in response before I lose?")
    assert worked.verdict.startswith("Yes") and "117.5" in worked.rules
    assert state("My opponent has 9 poison counters and 20 life. Do they lose?").verdict == "No"
    assert state("I took 21 commander damage from two commanders combined. Do I lose?").verdict == "No"
    assert state("Do I lose if I take 21 combat damage from Yuriko, the Tiger's Shadow?").verdict.startswith("Yes")
    assert state("If I mill my last card, do I lose?").verdict.startswith("No")
    assert state("If I have to draw from an empty library, do I lose?").verdict.startswith("Yes")


def test_legend_rule_and_planeswalkers():
    assert "graveyard" in state("If I control two Thalia, Guardian of Thraben, what happens?").verdict
    assert state("If my opponent and I each control Thalia, Guardian of Thraben, does the legend rule "
                 "apply?").verdict == "No"
    assert state("If I control two Grizzly Bears, does the legend rule apply?").verdict == "No"
    worked = state("Liliana of the Veil has 3 loyalty and takes 3 damage. What happens?")
    assert "graveyard" in worked.verdict and "704.5i" in worked.rules
    assert state("Does Blood Artist trigger when my opponent's creatures die?") is None


def test_cases_found_by_checking_against_the_verified_rulings():
    # A land doesn't use the stack, so there's no moment to respond to it
    assert when("Can I cast an instant in response to my opponent playing a land?").verdict == "No"
    # Cascade casts during resolution, ignoring timing
    assert when("Can I cast a sorcery from cascade during my opponent's turn?").verdict == "Yes"
    # Lifelink and combat damage happen at the same time: 2 + 3 - 5 = 0
    assert state("I'm at 2 life. In combat, my creature with lifelink deals 3 damage while I'm dealt 5 combat "
                 "damage at the same time. Do I lose the game?").verdict.startswith("Yes")
    angel = {"Platinum Angel": _card("Flying\nYou can't lose the game and your opponents can't win the game.", "4",
                                     "4", "", "Artifact Creature — Angel")}
    worked = judge.answer_state("Platinum Angel is on the battlefield under my control and my life total is -3. Do I "
                                "lose the game?", angel)
    assert worked.verdict.startswith("No") and "101.2" in worked.rules
    assert judge.answer_state("Does Platinum Angel die if it's dealt 3 damage?", angel).verdict.startswith("No")
    # Not a question about dying
    assert state("Humility is out. A creature has three +1/+1 counters. What are its power and toughness?") is None


TOKEN_ROWS = {
    "Army of the Damned": _card("Create thirteen tapped 2/2 black Zombie creature tokens.\nFlashback {7}{B}{B}{B}",
                                None, None, "B", "Sorcery"),
    "Doubling Season": _card("If an effect would create one or more tokens under your control, it creates twice that "
                             "many of those tokens instead.", None, None, "G", "Enchantment"),
    "Chatterfang, Squirrel General": _card("If one or more tokens would be created under your control, those tokens "
                                           "plus that many 1/1 green Squirrel creature tokens are created instead.",
                                           "3", "3", "G", "Legendary Creature — Squirrel Warrior"),
    "Ojer Taq, Deepest Foundation // Temple of Civilization": _card(
        "Vigilance\nIf one or more creature tokens would be created under your control, three times that many of "
        "those tokens are created instead.\n\n{T}: Add {W}.", "6", "6", "W", "Legendary Creature — God // Land"),
    "Kaya, Geist Hunter": _card("−2: Until end of turn, if one or more tokens would be created under your control, "
                                "twice that many of those tokens are created instead.", None, None, "WB",
                                "Legendary Planeswalker — Kaya"),
    "Elspeth, Storm Slayer": _card("If one or more tokens would be created under your control, twice that many of "
                                   "those tokens are created instead.\n+1: Create a 1/1 white Soldier creature token.",
                                   None, None, "W", "Legendary Planeswalker — Elspeth"),
    "Big Score": _card("As an additional cost, discard a card. Draw two cards and create two Treasure tokens.", None,
                       None, "R", "Instant"),
}


def tokens(question):
    named = {name: row for name, row in TOKEN_ROWS.items() if judge._name_at(question.lower(), name) >= 0}
    return judge.answer_tokens(question, named)


def test_token_replacement_effects():
    worked = tokens("With doubling season, chatterfang squirrel general and ojer taq deepest foundation out, I "
                    "cast army of the damned. How many tokens do I end up with?")
    # 13 Zombies, plus 13 Squirrels, then x2 and x3 (all creature tokens): 78 of each
    assert worked.verdict == ("156 tokens: 78 tapped 2/2 black Zombie creature tokens and 78 1/1 green Squirrel "
                              "creature tokens") and "616.1" in worked.rules
    # Kaya's -2 only counts once it's been used
    assert tokens("Kaya, Geist Hunter is out and I cast Army of the Damned. How many tokens?").verdict.startswith("13 ")
    assert tokens("I used Kaya, Geist Hunter's -2, then cast Army of the Damned. How many tokens?").verdict \
        .startswith("26 ")
    # Elspeth doubles her own +1
    assert tokens("I use Elspeth, Storm Slayer's +1 with Doubling Season out. How many tokens?").verdict \
        .startswith("4 ")
    # Order matters: Squirrels added before Ojer Taq get tripled; Treasures never do
    worked = tokens("Chatterfang, Squirrel General and Ojer Taq, Deepest Foundation are out. I cast Big Score. How "
                    "many tokens do I get?")
    assert worked.verdict == "8 tokens: 2 Treasure tokens and 6 1/1 green Squirrel creature tokens"
    assert "would give 4" in worked.steps[-1]
    assert tokens("How many tokens does Doubling Season make?") is None


def test_definitions():
    import rules
    from test_rules import CR
    # The glossary gets entries its fixture doesn't have (its last "Credits" ends the glossary)
    cr = rules.parse_cr(CR.replace("\nCredits\n\nLead", """
Active Player, Nonactive Player Order
A system that determines the order by which players make choices at the same time. See rule 101.4.

APNAP Order
See Active Player, Nonactive Player Order.

Summoning Sickness Rule
Informal term for a player's inability to attack with a creature they haven't controlled since their turn began.

Credits

Lead""", 1))
    worked = judge.answer_definition("How does cascade work?", cr)
    assert worked.verdict == "A keyword ability" and worked.rules == ["702.85"] and worked.heading == "DEFINITION"
    assert worked.short  # all its rules go in the answer card
    assert worked.steps == ["702.85a Cascade is a triggered ability that functions only while the spell with cascade is on "
                            "the stack."]
    assert judge.answer_definition("what is absorb", cr).verdict == "A keyword ability that prevents damage"
    assert judge.answer_definition("What does flying do?", cr).rules == ["702.9"]  # no glossary entry, but a keyword
    assert judge.answer_definition("Can Grizzly Bears block a creature with flying?", cr) is None
    assert judge.answer_definition("What is Lightning Bolt?", cr) is None
    # The one glossary entry it starts, and "See …" followed
    assert judge.answer_definition("What is summoning sickness?", cr).verdict.startswith("Informal term")
    assert judge.answer_definition("What is APNAP?", cr).verdict.startswith("A system that determines")
    both = judge.answer_definition("What's the difference between absorb and cascade?", cr)
    assert both.verdict == "Absorb vs. Cascade" and both.heading == "DEFINITIONS"
    assert both.steps[0] == "Absorb: A keyword ability that prevents damage."
