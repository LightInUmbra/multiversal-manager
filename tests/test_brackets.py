import brackets
import judge
import synergy


def _card(name, text="", game_changer=0, section="Main"):
    return {"name": name, "oracle_text": text, "game_changer": game_changer, "section": section}


def test_reading_cards_offline():
    assert brackets.is_extra_turn(_card("Time Warp", "Target player takes an extra turn after this one."))
    assert not brackets.is_extra_turn(_card("Ugin's Nexus", "If a player would begin an extra turn, that player "
                                                             "skips that turn instead."))
    for text in ("Destroy all lands.", "Destroy all artifacts, creatures, and lands.",
                 "Each player sacrifices four lands.", "Nonbasic lands are Mountains.",
                 "Players can't untap more than one land during their untap steps."):
        assert brackets.is_mass_land_denial(_card("X", text)), text
    assert not brackets.is_mass_land_denial(_card("Splendid Reclamation", "Return all land cards from your "
                                                                           "graveyard to the battlefield tapped."))


def test_minimum_bracket_and_what_breaks_a_target():
    deck = [_card("Kenrith", section="Commander"), _card("Sol Ring"), _card("Maybe", game_changer=1,
                                                                            section="Maybeboard")]
    report = brackets.check(deck)
    assert report.minimum() == 1 and report.broken(1) == []   # Maybeboard doesn't count

    deck += [_card(n, game_changer=1) for n in ("Rhystic Study", "Cyclonic Rift", "Smothering Tithe")]
    report = brackets.check(deck)
    assert report.minimum() == 3 and report.broken(3) == []
    assert report.broken(2) == [("Bracket 2 has no Game Changers (3 here)",
                                 ["Cyclonic Rift", "Rhystic Study", "Smothering Tithe"])]

    report = brackets.check(deck + [_card("Mana Vault", game_changer=1), _card("Armageddon", "Destroy all lands.")])
    assert report.minimum() == 4
    assert [why for why, _ in report.broken(3)] == ["Bracket 3 allows up to three Game Changers (4 here)",
                                                    "Bracket 3 has no mass land denial"]


def test_combos_from_commander_spellbook():
    data = {"cards": [{"card": {"name": "Armageddon"}, "massLandDenial": True, "gameChanger": False,
                       "extraTurn": False}],
            "combos": [
                {"arguablyTwoCard": True, "combo": {"bracketTag": "S", "uses": [{"card": {"name": "Sanguine Bond"}},
                                                    {"card": {"name": "Exquisite Blood"}}],
                                                    "produces": [{"feature": {"name": "Infinite lifeloss"}}]}},
                {"arguablyTwoCard": True, "combo": {"bracketTag": "R", "uses": [{"card": {"name": "Kiki-Jiki"}},
                                                    {"card": {"name": "Zealous Conscripts"}}],
                                                    "produces": [{"feature": {"name": "Infinite haste"}}]}},
                {"arguablyTwoCard": False, "combo": {"bracketTag": "S", "uses": [], "produces": []}}]}
    found = brackets.read_spellbook(data)
    assert found["mass_land_denial"] == ["Armageddon"] and len(found["combos"]) == 2
    report = brackets.check([], {**found, "mass_land_denial": []})
    # The late lifeloss combo is fine in Bracket 3; the early Kiki-Jiki one isn't
    assert report.minimum() == 4 and report.combos_checked
    assert [names for _, names in report.broken(3)] == [["Kiki-Jiki", "Zealous Conscripts"]]
    assert len(report.broken(2)) == 2


def test_recommendations_leave_out_what_the_bracket_doesnt_allow():
    assert not brackets.card_allowed(_card("Rhystic Study", game_changer=1), 2, 3)
    assert brackets.card_allowed(_card("Rhystic Study", game_changer=1), 3, 1)
    assert not brackets.card_allowed(_card("Rhystic Study", game_changer=1), 3, 0)
    assert not brackets.card_allowed(_card("Armageddon", "Destroy all lands."), 3, 3)
    assert not brackets.card_allowed(_card("Time Warp", "Take an extra turn after this one."), 1, 3)
    assert brackets.card_allowed(_card("Armageddon", "Destroy all lands."), None, 0)

    def row(name, **fields):
        return {"name": name, "type_line": "Enchantment", "oracle_text": "", "owned": 0, "price": 1.0,
                "score": 5, "synergy": 90, "efficiency": 1.0, "edhrec_rank": 1, "staple": None, "type": "Enchantment",
                "precon": False, "color_identity": "U", "game_changer": 0, **fields}
    pool = [row("Rhystic Study", game_changer=1), row("Mystic Remora")]

    def shown(**kwargs):
        return [r["name"] for _, rows, _ in synergy.recommend([], pool, **kwargs) for r in rows]
    assert "Rhystic Study" in shown() and "Rhystic Study" not in shown(bracket=2)
    assert any("Game Changer" in r["note"] for _, rows, _ in synergy.recommend([], pool) for r in rows)


def test_judge_answers_bracket_questions():
    cards = {"Rhystic Study": _card("Rhystic Study", game_changer=1)}
    assert judge.answer_brackets("Is Rhystic Study a game changer?", cards).verdict == "Yes"
    assert judge.answer_brackets("What bracket can I play Rhystic Study in?", cards).verdict == "Bracket 3 and up"
    assert judge.answer_brackets("Is Sol Ring a game changer?", {"Sol Ring": _card("Sol Ring")}).verdict == "No"
    assert judge.answer_brackets("Does Rhystic Study trigger on free spells?", cards) is None
