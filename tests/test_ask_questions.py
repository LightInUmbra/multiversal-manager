"""
Ask a Rules Question against the real Comprehensive Rules and rules library: questions asked
the way players type them, and the answer each should lead with. Skipped until the rules are
downloaded (the desktop's Rules window does that), since they aren't in the repository.
"""
from pathlib import Path

import pytest

import ask
import judge
import rules

CR_PATH = Path(__file__).resolve().parent.parent / "rules" / "cr.txt"
pytestmark = pytest.mark.skipif(not CR_PATH.exists(), reason="the Comprehensive Rules aren't downloaded")

# (question, what should lead): "yes"/"no" is an answer starting that way, other text one
# containing it, from a verified ruling or worked out from the rules; "worked: …" must be
# worked out; "define: …" a definition starting that way; "not verified" means anything but
# a verified answer (none fits, so none may be claimed)
QUESTIONS = [
    # Definitions
    ("How does haste work?", "define: A keyword ability that lets a creature ignore"),
    ("how does trample work", "define: A keyword ability that modifies how a creature assigns combat damage"),
    ("What is ward?", "define: A triggered ability that can counter"),
    ("what does deathtouch do?", "define: A keyword ability that causes damage"),
    ("What's menace?", "define: An evasion ability"),
    ("Explain cascade", "define: A keyword ability that may let a player cast a random extra spell"),
    ("define scry", "define: To manipulate some of the cards on top of your library"),
    ("What is summoning sickness?", "define: Informal term"),
    ("What's a state-based action?", "define: Game actions that happen automatically"),
    ("What is APNAP?", "define: A system that determines the order"),
    ("What are tokens?", "define: A marker used to represent"),
    ("What is the stack?", "define: A zone"),
    ("What is mana value?", "define: The total amount of mana"),
    ("What does indestructible mean?", "define: A keyword ability that precludes a permanent from being destroyed"),
    ("How does convoke work?", "define: A keyword ability that lets you tap creatures"),
    ("What's the difference between destroy and sacrifice?", "define: Destroy vs. Sacrifice"),
    ("What is the difference between scry and surveil?", "define: Scry vs. Surveil"),
    ("what is the difference between hexproof and shroud", "define: Hexproof vs. Shroud"),

    # Summoning sickness
    ("Can a creature with summoning sickness block?", "yes"),
    ("can summoning sick creatures block", "yes"),
    ("Can I block with a creature I just cast?", "yes"),
    ("Can I tap a land for mana the turn I play it?", "yes"),
    ("can i use a treasure the turn i make it", "yes"),
    ("Can a creature attack the turn it comes into play?", "worked: No"),
    ("If I animate a land I played this turn, can I tap it for mana?", "no"),
    ("Does haste let a creature use tap abilities right away?", "yes"),

    # Dying, destroying, sacrificing
    ("Is sacrificing a creature the same as it dying?", "yes"),
    ("does exile count as dying", "no"),
    ("Does sacrifice count as destroy?", "no"),
    ("Does indestructible stop sacrifice?", "no"),
    ("Does indestructible stop exile?", "no"),
    ("Does an indestructible creature die from lethal damage?", "no"),
    ("If a creature is bounced to its owner's hand, did it die?", "no"),
    ("Does a creature die if it's discarded?", "no"),

    # Tokens and counters
    ("Do tokens trigger dies abilities?", "yes"),
    ("When a token dies does it go to the graveyard?", "yes"),
    ("Can I cast a token that was returned to my hand?", "no"),
    ("If I flicker a token does it come back?", "no"),
    ("Does a creature keep its +1/+1 counters if it's exiled and comes back?", "no"),
    ("What happens to +1/+1 and -1/-1 counters on the same creature?", "One +1/+1 counter"),
    ("What does a shield counter do?", "It stops the next destruction or damage"),
    ("what do stun counters do", "It stops the next untap"),

    # Combat
    ("Can a tapped creature block?", "no"),
    ("Can I block with a tapped creature?", "no"),
    ("Can a creature with vigilance block after it attacked?", "yes"),
    ("Does a blocker that gets tapped still deal damage?", "yes"),
    ("Does a creature with 0 power deal combat damage?", "no"),
    ("Can I attack my own planeswalker?", "no"),
    ("Can I attack a planeswalker?", "yes"),
    ("Can one creature block two attackers?", "no"),
    ("Can two creatures block one attacker?", "yes"),
    ("Can a creature with reach block a flier?", "yes"),
    ("Can a creature with flying block a creature without flying?", "yes"),
    ("Can a single creature block a creature with menace?", "no"),
    ("Does vigilance tap when attacking?", "no"),
    ("Does a first strike deathtouch creature kill its blocker before it takes damage?", "no"),
    ("Can a deathtouch attacker kill all of its blockers?", "yes"),
    ("If the blocker is removed, does my creature without trample deal damage to the player?", "no"),
    ("If a trample creature's blockers are all removed, does it deal all its damage to the player?", "yes"),
    ("Does double strike and trample deal all regular damage to the player after the blocker dies?",
     "All of it to the player"),
    ("Does double strike trigger combat damage abilities twice?", "yes"),

    # Keywords
    ("Does lifelink work with noncombat damage?", "yes"),
    ("When my lifelink creature deals damage do I gain life?", "yes"),
    ("Do two instances of lifelink double the life I gain?", "no"),
    ("Can I target my own hexproof creature?", "yes"),
    ("Can I target my own creature with shroud?", "no"),
    ("Does ward trigger on my own spells?", "no"),
    ("Does ward stop Wrath of God?", "no"),
    ("Can a red creature block a creature with protection from red?", "no"),
    ("Does protection from white stop Wrath of God?", "no"),
    ("If my creature gets protection from the equipment's color does the equipment fall off?", "yes"),
    ("Does infect damage to creatures wear off?", "no"),
    ("Does infect damage make a player lose life?", "no"),
    ("Can regeneration save a creature with 0 toughness?", "no"),
    ("Can a creature with defender attack?", "no"),
    ("Can a creature with defender block?", "yes"),
    ("Can cascade hit a land?", "no"),
    ("Does kicker increase mana value?", "no"),
    ("Does prowess trigger on creature spells?", "no"),
    ("Does storm count my opponents' spells?", "yes"),
    ("Is a flashback spell exiled afterwards?", "yes"),
    ("Can delve pay for colored mana?", "no"),
    ("Does exalted trigger with two attackers?", "no"),
    ("Does undying bring back a creature with a +1/+1 counter?", "no"),
    ("Does persist bring back a creature with a +1/+1 counter?", "yes"),

    # Targets and resolving
    ("What happens if the target of my spell is gone when it resolves?", "It doesn't resolve"),
    ("Can I cast a spell with no legal targets?", "no"),
    ("Can an aura that's put onto the battlefield enchant a hexproof creature?", "yes"),
    ("Can I choose new targets when I copy a spell?", "Only if the effect says so"),
    ("If a creature gains hexproof in response to my removal, is it still destroyed?", "no"),

    # The stack and priority
    ("Does the last spell cast resolve first?", "The last"),
    ("Can I respond to my own spell?", "yes"),
    ("Can my opponent respond to a sacrifice cost?", "no"),
    ("Can I counter a land?", "no"),
    ("Can I respond to a land being played?", "worked: No"),
    ("Can I cast a sorcery on my opponent's turn?", "worked: No"),
    ("Can I cast an instant during combat?", "worked: Yes"),
    ("Can I cast a sorcery during combat?", "no"),
    ("Can my opponent respond to a mana ability?", "no"),
    ("Can a counterspell counter an activated ability?", "no"),
    ("Does a creature's trigger still resolve if I destroy it in response?", "yes"),
    ("If my spell gets countered do its cast triggers still happen?", "yes"),

    # Turns and mana
    ("Does mana carry over between phases?", "no"),
    ("Does putting a land onto the battlefield use my land drop?", "no"),
    ("Can I play two lands in one turn?", "no"),
    ("Can I play a land on my opponent's turn?", "no"),
    ("How does the London mulligan work?", "Draw seven"),
    ("how does mulligan work", "Draw seven"),
    ("What is a mulligan?", "define: To take a mulligan"),
    ("Can I concede at any time?", "yes"),
    ("Can I pay more life than I have?", "no"),
    ("What are the phases of a turn?", "Beginning, precombat main"),
    ("How many cards can I have in my hand?", "Any number"),
    ("Does the player who goes first draw a card?", "no"),
    ("Do I lose unspent mana at the end of a step?", "no"),

    # Mana value
    ("What is the mana value of an X spell in my hand?", "X counts as 0"),
    ("What is the mana value of a split card?", "Both halves added together"),
    ("What's the mana value of the back face of a transformed card?", "The same as its front face"),
    ("What is the mana value of a token?", "0"),

    # State-based actions and winning
    ("If both players go to 0 life at the same time, who wins?", "The game is a draw"),
    ("Does a player with 10 poison counters lose?", "yes"),
    ("Do I lose if I mill my last card?", "no"),
    ("Does a planeswalker with 0 loyalty die?", "yes"),
    ("Does damage wear off at the end of turn?", "yes"),
    ("Does the legend rule apply to two players' legends with the same name?", "no"),
    ("What happens to an aura when the enchanted creature dies?", "It goes to its owner's graveyard"),

    # Commander
    ("How much is commander tax after casting it twice?", "{4}"),
    ("What life total do players start with in Commander?", "40"),
    ("How many cards are in a commander deck?", "100"),
    ("Does commander damage count noncombat damage?", "no"),
    ("Do I lose after 21 combat damage from one commander?", "yes"),
    ("Can I have two copies of a card in commander?", "Only basic lands"),
    ("Can I play a card outside my commander's colors?", "no"),
    ("Can a planeswalker be a commander?", "Only if it says it can be your commander"),
    ("Can my commander go to the command zone from exile?", "yes"),
    ("Does my commander start in my hand?", "no"),
    ("Does commander tax go up when I cast it from my hand?", "no"),
    ("Is a mulligan free in multiplayer commander?", "yes"),

    # Multiplayer
    ("What life does a Two-Headed Giant team start with?", "30"),
    ("Are poison counters shared in Two-Headed Giant?", "yes"),
    ("What happens to a player's cards when they leave a multiplayer game?", "They leave the game too"),

    # Nothing verified fits, so none may be claimed
    ("When does a player lose the game?", "not verified"),
    ("How many lands can I play per turn?", "not verified"),
    ("What is the best way to cook pasta?", "not verified"),
    ("How does commander damage work with partners?", "not verified"),
    ("Can I cast a sorcery from cascade during my opponent's turn?", "yes"),  # the ruling itself still leads
]

# A second batch, written after the first passed and checked before anything was tuned to it:
# the same kinds of questions, worded differently
ASKED_DIFFERENTLY = [
    ('Can my creature block the same turn I cast it?', 'yes'),
    ('Do lands have summoning sickness?', 'no'),
    ('Can artifacts with tap abilities be used the turn they enter?', 'yes'),
    ('Can a creature I stole this turn attack?', 'no'),
    ('Does a creature with haste still have summoning sickness for blocking?', 'no'),
    ('If my creature is destroyed, did it die?', 'yes'),
    ('Does bouncing a creature count as it dying?', 'no'),
    ('Does a token that gets exiled trigger leaves the battlefield abilities?', 'yes'),
    ('Can I bring a token back from the graveyard with a reanimation spell?', 'no'),
    ('Do +1/+1 counters stay when a creature is flickered?', 'no'),
    ('If my creature has a shield counter and gets destroyed, what happens?', 'It stops the next destruction'),
    ('Can a creature that attacked last turn block if it has vigilance?', 'yes'),
    ('Does a tapped blocker deal combat damage?', 'yes'),
    ('Does a creature with negative power deal damage?', 'no'),
    ('Can I attack a planeswalker I control?', 'no'),
    ('Can my creatures attack a planeswalker instead of the player?', 'yes'),
    ('Can a creature block more than one attacker?', 'no'),
    ('Can 3 creatures block a single attacker?', 'yes'),
    ('Can creatures with reach block flying creatures?', 'yes'),
    ('Can a flier be blocked by a creature without flying or reach?', 'no'),
    ('Does menace mean it needs two blockers?', 'yes'),
    ('With first strike and deathtouch does my creature take damage from its blocker?', 'no'),
    ('If a creature with deathtouch blocks, does 1 damage kill the attacker?', 'yes'),
    ('Does indestructible stop -X/-X from killing a creature?', 'no'),
    ('Can indestructible creatures be exiled?', 'yes'),
    ('Can I target a creature with hexproof that I control?', 'yes'),
    ('Can my opponent target my hexproof creature?', 'no'),
    ('Does shroud stop me from targeting my own creature?', 'yes'),
    ('Does ward trigger when my opponent targets my creature?', 'yes'),
    ('Does protection from blue stop blue creatures from blocking it?', 'yes'),
    ('Does protection stop board wipes?', 'no'),
    ('What happens to an equipment when the creature gets protection from it?', 'yes'),
    ('Is infect damage permanent on creatures?', 'no'),
    ('Can I regenerate a creature that was sacrificed?', 'no'),
    ('What happens when a creature regenerates?', 'tapped'),
    ("If my spell's target becomes illegal, what happens to the spell?", "doesn't resolve"),
    ('Can I cast removal if there are no creatures to target?', 'no'),
    ('Is a copied spell cast?', 'no'),
    ('Does the stack resolve last in first out?', 'The last'),
    ('After I cast a spell do I get priority first?', 'yes'),
    ('Can my opponent respond to a cost being paid?', 'no'),
    ('Can you counter a land drop?', 'no'),
    ('Does floating mana empty between phases?', 'no'),
    ('Does fetching a land count as my land drop?', 'no'),
    ('How many cards do I put on the bottom after two mulligans?', 'not verified'),
    ('Can a player concede in the middle of a spell resolving?', 'yes'),
    ('Can I pay 5 life at 3 life?', 'no'),
    ("What's the mana value of a card with X in its cost?", 'X counts as 0'),
    ('What is the mana value of a modal double-faced card?', "Its front face's"),
    ('Can I play 4 copies of a card in commander?', 'Only basic lands'),
    ('Can a planeswalker be used as my commander?', 'Only if it says'),
    ("Can my commander go to the command zone if it's exiled?", 'yes'),
    ('Is my commander in my library at the start of the game?', 'no'),
    ('Is Two-Headed Giant life 30?', '30'),
    ('How much poison do you need to lose in two headed giant?', '15'),
    ('What happens if all players lose at the same time?', 'draw'),
    ('If my library is empty, do I lose immediately?', 'no'),
    ('Does 21 noncombat damage from a commander make a player lose?', 'no'),
    ('How does lifelink work?', 'define: '),
    ('What does trample do?', 'define: '),
    ('What is hexproof?', 'define: '),
    ('How does flashback work?', 'define: '),
    ('What is the difference between exile and graveyard?', 'define: '),
    ("What's the difference between first strike and double strike?", 'define: '),
    ('What is a permanent?', 'define: '),
    ('What is priority?', 'define: '),
    ('What does proliferate mean?', 'define: '),
    ('What is the cleanup step?', 'define: '),
    ('Can I cast Wrath of God during combat?', 'no'),
    ("What's the best commander?", 'not verified'),
    ('How do I shuffle?', 'not verified'),
]

# A third batch, run once untouched (42 right, 11 unanswered, 7 wrong), then fixed: traps where
# the nearest ruling is asked the other way round, about another count, or another card type.
# "not verified" ones have no ruling asked their way: the closest one shows, never as the answer.
TRAPS = [
    ('Can I activate a planeswalker ability twice in one turn?', 'no'),
    ("Can I use a loyalty ability on my opponent's turn?", 'no'),
    ('Does damage to a planeswalker remove loyalty?', 'yes'),
    ('Can I respond to split second with a mana ability?', 'yes'),
    ('Can I cast a spell in response to split second?', 'no'),
    ('Does split second stop a morph from being turned face up?', 'not verified'),
    ('Is a face-down creature a 2/2?', 'yes'),
    ("Do my opponent's triggers go on the stack before mine during my turn?", 'no'),
    ('Does a Clone copy counters?', 'no'),
    ('Does a token copy of a creature have the same mana value?', 'yes'),
    ('Can I choose new targets for a copied spell?', 'Only if'),
    ('Does a copy of a spell have the same X?', 'yes'),
    ('If a creature loses all abilities, does an equipment still give it flying?', 'yes'),
    ("Does Blood Moon turn Urborg's other lands into swamps?", 'no'),
    ('Who chooses between two replacement effects on my creature?', 'I do'),
    ('If a creature would die and be exiled instead, do dies triggers happen?', 'no'),
    ('Does a creature that enters tapped still trigger enters abilities?', 'yes'),
    ('Can I tap a land that enters tapped the turn it comes in?', 'no'),
    ('With Doubling Season does a planeswalker enter with double loyalty?', 'yes'),
    ('Does Doubling Season double the +1 on a planeswalker ability?', 'no'),
    ('How many tokens do two token doublers make from one token?', '4'),
    ("Does 'can't be countered' stop me from targeting it with a counterspell?", 'not verified'),
    ('Does a countered creature spell die?', 'no'),
    ('Can I cast a card from my graveyard?', 'no'),
    ('Can I pay kicker when I cast a spell for free?', 'yes'),
    ('What is X when I cast a spell without paying its mana cost?', '0'),
    ('Does cost reduction reduce colored mana?', 'no'),
    ('Does commander tax reset if my commander goes back to the command zone?', 'no'),
    ('Can I cast my commander from my hand without paying commander tax?', 'yes'),
    ('Is hybrid mana both colors for color identity?', 'yes'),
    ('Does reminder text count for color identity?', 'no'),
    ('Does the back face of a double-faced card count for color identity?', 'yes'),
    ('Can two partners both be my commanders?', 'yes'),
    ('Is the companion part of the 100 cards?', 'no'),
    ('Is Armageddon allowed in bracket 3?', 'no'),
    ('Does my commander count as one of my game changers?', 'yes'),
    ('Can I sacrifice a Food whenever I want?', 'yes'),
    ("Is a Treasure's ability a mana ability?", 'yes'),
    ('Does exalted trigger if one creature attacks alone?', 'yes'),
    ('Does prowess trigger on instants?', 'yes'),
    ('Can my opponent respond to cycling?', 'yes'),
    ("Can I cast a sorcery with madness on my opponent's turn?", 'yes'),
    ('Does annihilator trigger when the creature attacks?', 'yes'),
    ('Does undying return a creature without a +1/+1 counter?', 'yes'),
    ('Does a storm copy count as cast?', 'no'),
    ('If I evoke a creature do its enters abilities trigger?', 'yes'),
    ('Can I mutate onto a Human?', 'no'),
    ('Can overload be stopped by hexproof?', 'no'),
    ('Can a creature with flying block a creature without flying?', 'yes'),
    ('Does trample do anything when the creature is blocking?', 'no'),
    ('Does lifelink stack if a creature has it twice?', 'no'),
    ('If I control two legendary permanents with the same name, what happens?', 'keep one'),
    ('Do I draw on my first turn in a four-player Commander game?', 'yes'),
    ('Does the player going first in a two-player game draw?', 'no'),
    ("Does Teferi's Protection stop commander damage?", 'yes'),
    ('Does Craterhoof Behemoth count itself?', 'yes'),
    ('Can Swords to Plowshares target a creature with protection from white?', 'no'),
    ("Does Thassa's Oracle win with an empty library?", 'yes'),
    ('Does Glorious Anthem still pump a creature that became a Frog?', 'not verified'),
    ('Does Humility make every creature 1/1?', 'not verified'),
]


@pytest.fixture(scope="module")
def ask_real():
    cr = rules.parse_cr(CR_PATH.read_text(encoding="utf-8"))
    library = rules.load_library()
    return lambda question: ask.look_up(question, cr, library, [])


@pytest.mark.parametrize("question,expected", QUESTIONS + ASKED_DIFFERENTLY + TRAPS,
                         ids=[q for q, _ in QUESTIONS + ASKED_DIFFERENTLY + TRAPS])
def test_question(ask_real, question, expected):
    found = ask_real(question)
    if expected == "not verified":
        assert found.kind != "verified", found.matches[0][1]["question"]
    elif expected.startswith("define: "):
        assert found.kind == "worked" and found.worked.heading.startswith("DEFINITION"), found.kind
        assert found.worked.verdict.startswith(expected[8:]), found.worked.verdict
    elif expected.startswith("worked: "):
        assert found.kind == "worked", (found.kind, found.matches[:1])
        assert found.worked.verdict.startswith(expected[8:]), found.worked.verdict
    else:
        # A verified ruling, or an answer worked out from the rules: either way, the right one
        assert found.kind in ("verified", "worked"), (found.kind, [(s, e["question"]) for s, e in found.matches])
        lead = (found.matches[0][1]["answer"] if found.kind == "verified" else found.worked.verdict).lower()
        right = lead.startswith(expected.lower()) if expected in ("yes", "no") else expected.lower() in lead
        assert right, (lead, found.matches[0][1]["question"] if found.kind == "verified" else found.worked.steps)


def test_every_keyword_and_glossary_term_has_a_definition():
    # Every keyword and glossary term, asked about plainly, gets a definition with real text
    cr = rules.parse_cr(CR_PATH.read_text(encoding="utf-8"))
    missing = []
    for term in [*cr.keywords(), *(name for name, _ in cr.glossary)]:
        worked = judge.answer_definition(f"What is {term}?", cr)
        if worked is None or len(worked.verdict) < 8 or worked.verdict.startswith("See "):
            missing.append(term)
    assert not missing, missing
