import synergy


def _card(name, type_line, text, rank=None, price=1.0, owned=0, identity=""):
    return {"name": name, "type_line": type_line, "oracle_text": text, "text": f"{type_line}\n{text}",
            "edhrec_rank": rank, "price": price, "owned": owned, "color_identity": identity}


def test_themes_follow_what_the_commander_cares_about():
    talrand = _card("Talrand, Sky Summoner", "Legendary Creature — Merfolk Wizard",
                    "Whenever you cast an instant or sorcery spell, create a 2/2 blue Drake creature token with flying.")
    # Triggers count double; a type it only makes tokens of isn't tribal
    assert synergy.suggest_themes([talrand], ["Drake", "Merfolk"])[:2] == ["spells", "tokens"]
    edgar = _card("Edgar Markov", "Legendary Creature — Vampire Knight",
                  "Eminence — Whenever you cast another Vampire spell, create a 1/1 black Vampire creature token.")
    assert synergy.suggest_themes([edgar], ["Vampire", "Knight"])[0] == "tribal:Vampire"
    atraxa = _card("Atraxa", "Legendary Creature — Phyrexian Angel Horror",
                   "Flying, vigilance, deathtouch, lifelink\nAt the beginning of your end step, proliferate.")
    assert "lifegain" not in synergy.suggest_themes([atraxa])       # a keyword line isn't a theme
    # Types on 3+ type lines, not joke one-offs ("and/or", "Time Lord") or plurals of others ("Elves")
    lines = ["Creature — Elf Warrior", "Creature — Elf Druid", "Creature — Elf Warrior Druid",
             "Creature — Human Warrior Druid", "Creature — Elves", "Creature — Elves", "Creature — Elves",
             "Creature — Time Lord and/or Gnome"]
    assert synergy.known_types(lines) == ["Druid", "Elf", "Warrior"]
    # A commander's own name isn't a creature type
    windgrace = _card("Lord Windgrace", "Legendary Planeswalker — Windgrace",
                      "−3: Return up to two target land cards from your graveyard to the battlefield.")
    assert not any(k.startswith("tribal:") for k in synergy.suggest_themes([windgrace], ["Lord"]))
    assert "lands" in synergy.suggest_themes([windgrace])


def test_recommendations_rank_fit_then_popularity_and_apply_filters():
    commander = _card("Ghave", "Legendary Creature — Fungus Shaman", "Put a +1/+1 counter on target creature.")
    cards = [
        commander,
        _card("Hardened Scales", "Enchantment", "If one or more +1/+1 counters would be put on a creature…", rank=300),
        _card("Doubling Season", "Enchantment", "…twice that many +1/+1 counters…", rank=100, price=60, owned=1),
        _card("Path to Exile", "Instant", "Exile target creature. Its controller may search their library "
              "for a basic land card.", rank=15),
        _card("Sol Ring", "Artifact", "{T}: Add {C}{C}.", rank=1),
        _card("Forest", "Basic Land — Forest", "({T}: Add {G}.)", rank=2),
        _card("Command Tower", "Land", "{T}: Add one mana of any color in your commander's color identity.", rank=3),
    ]
    tags = {"counters-matter": {"Hardened Scales", "Doubling Season"}, "ramp": {"Path to Exile"}}
    pool = synergy.score(cards, ["counters"], tags)

    def sections(**filters):
        return {title: [r["name"] for r in rows] for title, rows, _ in synergy.recommend([commander], pool, **filters)}

    shown = sections()
    assert shown["High Synergy Cards"] == ["Doubling Season", "Hardened Scales"]   # same fit, more played first
    assert shown["Ramp"] == ["Sol Ring"]
    assert shown["Removal"] == ["Path to Exile"]      # its rules text wins over being tagged ramp
    assert shown["Lands"] == ["Command Tower"]        # basics and the commander never show up
    assert sum(shown.values(), []).count("Sol Ring") == 1
    assert sections(owned_only=True) == {"High Synergy Cards": ["Doubling Season"]}
    assert "Doubling Season" not in sections(max_price=20)["High Synergy Cards"]
    assert "Hardened Scales" not in sections(in_deck={"hardened scales"})["High Synergy Cards"]
    assert "Ramp" not in sections(staples=False)


def test_imotekh_style_commanders_get_artifacts_graveyard_and_their_precon():
    imotekh = _card("Imotekh the Stormlord", "Legendary Artifact Creature — Necron",
                    "Phaeron — Whenever one or more artifact cards leave your graveyard, create two 2/2 black "
                    "Necron Warrior artifact creature tokens.")
    assert {"artifacts", "graveyard"} <= set(synergy.suggest_themes([imotekh])[:3])

    cards = [_card("Mycosynth Lattice", "Artifact", "All permanents are artifacts in addition to their other types.",
                   rank=2000),
             _card("Shatter", "Instant", "Destroy target artifact.", rank=500),
             _card("Blood Artist", "Creature — Vampire", "Whenever Blood Artist or another creature dies, "
                   "target player loses 1 life.", rank=141),
             _card("Necron Overlord", "Artifact Creature — Necron", "Relentless March.", rank=15000)]
    pool = {r["name"]: r for r in synergy.score(cards, ["artifacts", "sacrifice"], {"precon": {"Necron Overlord"}})}
    assert pool["Mycosynth Lattice"]["score"] >= 3 and pool["Blood Artist"]["score"] >= 3
    assert pool["Shatter"]["score"] == 0                   # removal aimed at artifacts isn't artifact synergy

    sections = {title: (rows, hidden) for title, rows, hidden in
                synergy.recommend([imotekh], list(pool.values()), precon_title="From Necron Dynasties")}
    assert [r["name"] for r in sections["From Necron Dynasties"][0]] == ["Necron Overlord"]


def test_show_more_adds_cards_to_a_section():
    cards = [_card(f"Relic {n}", "Artifact", "Artifacts you control have hexproof.", rank=n) for n in range(1, 121)]
    pool = synergy.score(cards, ["artifacts"], {})

    def artifacts(**more):
        return next((len(rows), hidden) for title, rows, hidden in synergy.recommend([], pool, staples=False, **more)
                    if title == "Artifacts")

    # 120 cards: 20 in High Synergy, 30 in Top Cards, then Artifacts
    assert artifacts() == (30, 40)
    assert artifacts(more={"Artifacts": synergy.SHOW_MORE}) == (60, 10)


def test_lands_leave_out_fetchlands_for_other_colors():
    commander = _card("Light-Paws", "Legendary Creature — Fox Advisor", "Whenever an Aura you control enters, "
                      "you may search your library for an Aura card.", identity="W")
    cards = [_card("Polluted Delta", "Land", "Search your library for an Island or Swamp card.", rank=1),
             _card("Windswept Heath", "Land", "Search your library for a Forest or Plains card.", rank=2),
             _card("Command Tower", "Land", "{T}: Add one mana of any color.", rank=3)]
    sections = {title: [r["name"] for r in rows]
                for title, rows, _ in synergy.recommend([commander], synergy.score(cards, [], {}, [commander]))}
    assert sections["Lands"] == ["Windswept Heath", "Command Tower"]


def test_theme_detection_edge_cases_from_the_150_commander_benchmark():
    def themes(text, type_line="Legendary Creature — Human"):
        return synergy.suggest_themes([_card("Commander", type_line, text)], ["Human", "Elf"])

    # A god's devotion clause is about being a creature; reminder text isn't the card's ability
    assert "devotion" not in themes("As long as your devotion to white and red is less than seven, "
                                    "Iroas isn't a creature.\nCreatures you control have menace.")
    assert "superfriends" not in themes("Trample (This creature can deal excess combat damage to the player "
                                        "or planeswalker it's attacking.)\nThis spell costs {X} less to cast, "
                                        "where X is the total power of creatures you control.")
    assert "xspells" not in themes("This spell costs {X} less to cast, where X is the total power of creatures.")
    # Removal on a commander doesn't make it an artifact or enchantment commander
    removal = themes("When Loran enters, destroy up to one target artifact or enchantment.")
    assert "artifacts" not in removal and "enchantments" not in removal
    # Directions that used to have no theme at all
    assert themes("Spells your opponents cast cost {1} more to cast.")[0] == "taxes"
    assert themes("If a permanent entering causes a triggered ability of a permanent you control to trigger, "
                  "that ability triggers an additional time.")[0] == "etb"
    assert themes("If a source would deal damage to an opponent, that source deals double that damage "
                  "to that player instead.")[0] == "damage"
    assert themes("As Morophon enters, choose a creature type. Spells of the chosen type you cast cost less.")[0] \
        == "chosen"
    # Cascade is a keyword worth building around, unlike lifelink
    assert themes("Creatures you control have haste.\nCascade, cascade (When you cast this spell, exile cards "
                  "from the top of your library until you exile a nonland card that costs less.)")[0] == "cascade"
    # Non-creature subtypes on odd creatures aren't tribes
    assert synergy.creature_types({"type_line": "Enchantment Creature — Saga Wizard"}) == ["Wizard"]
