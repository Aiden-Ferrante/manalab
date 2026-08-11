"""Turning oracle text into structured effects.

Magic's oracle text is heavily templated, which makes a rules-based parser
viable in a way it would not be for ordinary prose. It also makes it very easy
to *feel* successful while quietly dropping half of every card, so the design
rule here is:

    every clause is either matched to a verb or recorded as unparsed.

Nothing is skipped, nothing is approximated silently. `Parsed.coverage` is the
fraction of clauses that matched, and a card with coverage below 1.0 is one the
engine must not pretend to understand.

What this is not: a rules implementation. It produces `Effect(verb, params)`
tuples describing *what a card says*. Deciding what that means in a game is the
engine's job, and the engine implements a subset of these verbs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from manalab.cards.model import Card, Effect

# --- text normalisation -------------------------------------------------

CARDNAME = "CARDNAME"

_REMINDER = re.compile(r"\([^)]*\)")
# Newlines separate abilities and must survive normalisation — collapsing them
# merges a keyword line into the trigger below it and loses both.
_HORIZONTAL_SPACE = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n{2,}")

WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "twenty": 20,
}

"""Stands in for X and other undetermined counts. Never confuse it with a real
count — a card that draws X cards is not a card that draws -1."""


def quantity(token: str) -> int | str:
    """A number when the text names one; the text itself when it does not.

    `X` used to become -1, so "You gain X life" parsed as gain_life(-1) — a
    confident wrong value wearing a success tick, which is worse than an unparsed
    clause because coverage cannot see it. An amount is now either an int or the
    original token ("X", "that many"), and the engine can tell which it got.
    """
    stripped = token.strip()
    lowered = stripped.lower()
    if lowered.isdigit():
        return int(lowered)
    return WORD_NUMBERS.get(lowered, stripped)


def normalise(text: str, card_name: str = "") -> str:
    """Strip reminder text and replace the card's own name with a placeholder.

    Self-reference matters: "Grizzly Bears gets +1/+1" and "target creature gets
    +1/+1" are different effects, and the only signal distinguishing them is
    whether the subject is the card's own name.
    """
    text = _REMINDER.sub(" ", text or "")
    if card_name:
        text = text.replace(card_name, CARDNAME)
        short = card_name.split(",")[0].strip()
        if short and short != card_name:
            text = text.replace(short, CARDNAME)
    text = _HORIZONTAL_SPACE.sub(" ", text)
    return _BLANK_LINES.sub("\n", text).strip()


# --- the verb table -----------------------------------------------------
#
# Order matters: the first pattern that matches a clause wins, so specific
# templates must precede general ones. "Counter target spell" has to be tried
# before anything matching a bare "target".

@dataclass(frozen=True)
class Pattern:
    verb: str
    regex: re.Pattern[str]
    params: tuple[str, ...]
    numeric: frozenset[str] = frozenset()

    def match(self, clause: str) -> Effect | None:
        found = self.regex.search(clause)
        if not found:
            return None
        values: list[tuple[str, str | int]] = []
        for name, raw in zip(self.params, found.groups()):
            if raw is None:
                continue
            values.append((name, quantity(raw) if name in self.numeric else raw.strip()))
        return Effect(verb=self.verb, params=tuple(values))


def _p(verb: str, pattern: str, *params: str, numeric: Iterable[str] = ()) -> Pattern:
    return Pattern(verb, re.compile(pattern, re.I), tuple(params), frozenset(numeric))


PATTERNS: tuple[Pattern, ...] = (
    # --- mana -----------------------------------------------------------
    _p("add_mana", r"\badds? ((?:\{[^}]+\}\s*)+)", "mana"),
    _p("add_mana_any", r"\badds? (\w+) mana of any (?:one )?colou?r", "amount",
       numeric=("amount",)),
    # --- damage and life ------------------------------------------------
    _p("deal_damage", r"\bdeals? (\d+|X) damage to ([^.,]+)", "amount", "target",
       numeric=("amount",)),
    _p("gain_life", r"\bgains? (\d+|X) life", "amount", numeric=("amount",)),
    _p("lose_life", r"\bloses? (\d+|X) life", "amount", numeric=("amount",)),
    # --- cards ----------------------------------------------------------
    _p("draw", r"\bdraws? (\w+) cards?", "amount", numeric=("amount",)),
    _p("discard", r"\bdiscards? (\w+) cards?", "amount", numeric=("amount",)),
    _p("mill", r"\bmills? (\w+) cards?", "amount", numeric=("amount",)),
    _p("search_library", r"\bsearch(?:es)? your library for ([^.]+)", "what"),
    _p("scry", r"\bscry (\d+)", "amount", numeric=("amount",)),
    _p("surveil", r"\bsurveil (\d+)", "amount", numeric=("amount",)),
    _p("shuffle", r"\bshuffles?\b"),
    # --- removal --------------------------------------------------------
    _p("counter_spell", r"\bcounters? target ([^.,]*spell[^.,]*)", "target"),
    _p("destroy", r"\bdestroys? ([^.,]+)", "target"),
    _p("exile", r"\bexiles? ([^.,]+)", "target"),
    _p("sacrifice", r"\bsacrifices? ([^.,]+)", "what"),
    _p("return_to_hand", r"\breturns? ([^.]+?) to (?:its|their) owner'?s? hand", "target"),
    _p("return_from_graveyard", r"\breturns? ([^.]+?) from your graveyard", "target"),
    # --- board ----------------------------------------------------------
    _p("create_token", r"\bcreates? (\w+) ([^.]*?) tokens?", "amount", "what",
       numeric=("amount",)),
    _p("put_counters", r"\bputs? (\w+) ([+\-]\d/[+\-]\d|\w+) counters? on ([^.,]+)",
       "amount", "kind", "target", numeric=("amount",)),
    _p("pump", r"([^.,]+?) gets? ([+\-](?:\d+|X)/[+\-](?:\d+|X))", "target", "amount"),
    _p("gain_control", r"\bgains? control of ([^.,]+)", "target"),
    _p("attach", r"\battach(?:es)? ([^.,]+?) to ([^.,]+)", "what", "target"),
    # search() finds the verb inside a conditional clause, so the werewolf pair
    # ("if no spells were cast last turn, transform…") lands here too, with the
    # condition captured rather than discarded.
    _p("transform", r"(?:if ([^,]+), )?transforms? ([^.,]+)", "condition", "target"),
    _p("must_attack", r"\battacks? each combat if able"),
    _p("block_restriction", r"\bcan block only ([^.,]+)", "only"),
    _p("tap", r"\btaps? ([^.,]+)", "target"),
    _p("untap", r"\buntaps? ([^.,]+)", "target"),
    # --- modifiers ------------------------------------------------------
    _p("cost_reduction", r"costs? (\{[^}]+\}|\d+) less", "amount"),
    _p("cost_increase", r"costs? (\{[^}]+\}|\d+) more", "amount"),
    _p("prevent_damage", r"\bprevents? ([^.,]+)", "what"),
    _p("cant_block", r"\bcan'?t block\b"),
    _p("cant_be_blocked", r"\bcan'?t be blocked\b"),
    _p("cant_be_countered", r"\bcan'?t be countered\b"),
    _p("cant_be_regenerated", r"\bcan'?t be regenerated\b"),
    _p("enters_tapped", r"\benters? tapped\b"),
    _p("regenerate", r"\bregenerate ([^.,]+)", "target"),
    # --- keyword actions ------------------------------------------------
    _p("proliferate", r"\bproliferate\b"),
    _p("venture", r"\bventure into the dungeon\b"),
    _p("monstrosity", r"\bmonstrosity (\d+|x)", "amount", numeric=("amount",)),
    _p("ring_tempts", r"\bthe ring tempts you\b"),
    _p("become_monarch", r"\bbecomes? the monarch\b"),
    _p("get_energy", r"\byou get ((?:\{e\})+)", "amount"),
    _p("flip_coin", r"\bflips? \w+ coins?\b"),
    _p("roll_die", r"\broll [^.,]*?\bdi(?:e|ce)\b"),
    _p("choose_type", r"\bchoose an? (\w+(?: card)?) type\b", "kind"),
    # --- structure and riders -------------------------------------------
    # Not effects themselves, but the alternative is reporting a modal spell's
    # header as an unparsed gap and overstating how much is missing.
    _p("modal", r"\bchoose (one|two|three|up to \w+)\b", "count"),
    _p("timing_restriction", r"\bactivate only ([^.]+)", "when"),
    _p("trigger_limit", r"\btriggers only ([^.]+)", "when"),
    _p("optional_cost", r"\byou may pay (\{[^}]+\}|\d+)", "amount"),
    # Copy riders, impulse-draw riders, animation riders: clauses that qualify a
    # neighbouring effect. Reporting them as gaps overstated what was missing.
    _p("may_choose_new_targets", r"\bmay choose new targets\b"),
    _p("may_play", r"\bmay play (?:that card|those cards|them|it)\b"),
    _p("may_look_top", r"\bmay look at the top card of your library"),
    _p("still_a_land", r"\b(?:it'?s|they'?re) still (?:a )?lands?\b"),
    _p("can_be_commander", r"\bcan be your commander\b"),
    _p("anyone_may_activate", r"\bany player may activate\b"),
    _p("enters_with_counters",
       r"\benters(?: the battlefield)? with (\w+) ([+\-]\d/[+\-]\d|\w+) counters?",
       "amount", "kind", numeric=("amount",)),
    # Leveler and sticker layout lines. Not effects — the printed frame leaking
    # into oracle text — but reporting "LEVEL 6-11" and "6/6" as unparsed gaps
    # made the parser look worse at exactly the cards it understood fine.
    # Two shapes share the word: a leveler's band header ("LEVEL 6-11",
    # "LEVEL 12+") and a Class's level-up effect ("{4}{G}: Level 2" — the clause
    # is just "Level 2"). One pattern, optional range.
    _p("level_band", r"^level (\d+)(?:-(\d+))?\+?$", "from", "to",
       numeric=("from", "to")),
    _p("stat_line", r"^(\d+|\*)/(\d+|\*)$", "power", "toughness"),
    _p("sticker_stats", r"(?:\{tk\})+\s*—\s*(\d+)/(\d+)", "power", "toughness"),
    # --- information ----------------------------------------------------
    _p("reveal", r"\breveals? ([^.,]+)", "what"),
    _p("look_at", r"\blook at the top (?:(\w+) )?cards?", "amount", numeric=("amount",)),
    _p("put_on_bottom", r"\bput the rest on the bottom", ),
    _p("investigate", r"\binvestigate\b"),
    _p("grant_ability", r"\bgains? ([^.,]+) until end of turn", "ability"),
    # A bare grant with no duration — "It gains haste." Restricted to a keyword
    # list so "gains that much life" stays with its own verb, and fenced off from
    # the durationed form above: patterns are all-match-per-clause, not first-wins,
    # so without the lookahead "gains flying until end of turn" fired both and
    # counted twice.
    _p("grant_ability",
       r"\bgains? (haste|flying|trample|first strike|double strike|vigilance"
       r"|lifelink|deathtouch|menace|reach|hexproof|shroud|indestructible"
       r"|protection from [^.,]+)\b(?![^.]*until end of turn)", "ability"),
    _p("gain_life", r"\bgains? (that much) life", "amount"),
)


# --- ability structure --------------------------------------------------

_ACTIVATED = re.compile(r"^([^:]{1,60}):\s*(.+)$", re.S)
_TRIGGERED = re.compile(r"^(when(?:ever)?|at)\b([^,]*),\s*(.+)$", re.I | re.S)
_CLAUSE_SPLIT = re.compile(r"(?<=[.;])\s+")


@dataclass(frozen=True)
class Ability:
    kind: str
    """`spell`, `activated`, `triggered`, `static`, or `keyword`."""
    text: str
    effects: tuple[Effect, ...] = ()
    unparsed: tuple[str, ...] = ()
    cost: str = ""
    trigger: str = ""

    @property
    def fully_parsed(self) -> bool:
        return not self.unparsed


@dataclass(frozen=True)
class Parsed:
    card_name: str
    abilities: tuple[Ability, ...] = ()
    keywords: frozenset[str] = frozenset()

    @property
    def effects(self) -> tuple[Effect, ...]:
        return tuple(e for a in self.abilities for e in a.effects)

    @property
    def verbs(self) -> frozenset[str]:
        return frozenset(e.verb for e in self.effects)

    @property
    def unparsed(self) -> tuple[str, ...]:
        return tuple(c for a in self.abilities for c in a.unparsed)

    @property
    def coverage(self) -> float:
        """Fraction of clauses that matched a verb. 1.0 for vanilla cards."""
        matched = len(self.effects)
        total = matched + len(self.unparsed)
        return 1.0 if total == 0 else matched / total

    @property
    def fully_parsed(self) -> bool:
        return not self.unparsed


# Lines that are purely keyword abilities, e.g. "Flying, vigilance".
# Older cards separate them with a semicolon — "Flying; swampwalk", "Trample;
# banding" — and rejecting those made 30 cards, several of them nothing *but*
# keywords, parse at 0%.
_KEYWORD_LINE = re.compile(r"^[A-Za-z][A-Za-z' \-]*([,;]\s*[A-Za-z][A-Za-z' \-]*)*$")

EXTRA_KEYWORDS = frozenset({
    "enchant", "equip", "cycling", "crew", "ward", "kicker", "level up",
    "flashback", "buyback", "echo", "fortify", "reconfigure", "bestow",
    "escape", "unearth", "embalm", "eternalize", "adapt", "monstrosity",
    "outlast", "scavenge", "transmute", "channel", "ninjutsu", "prowl",
    "evoke", "madness", "morph", "megamorph", "disguise", "suspend",
    "reinforce", "awaken", "surge", "spectacle", "escalate", "entwine",
    "overload", "replicate", "multikicker", "affinity", "protection",
    "landwalk", "hexproof from",
})
"""Keywords that take a parameter. Scryfall usually lists these in `keywords`,
but not always — and a keyword ability line is not an effect to parse, it is a
named ability whose meaning is defined in the rules."""

_KEYWORD_PARAM = re.compile(r"^\s*(?:[—\-:]\s*)?(.*)$", re.S)


def _keyword_ability(line: str, known: set[str]) -> Ability | None:
    """Recognise a keyword ability line, with or without a parameter.

    "Equip {1}", "Cycling—Pay 1 life.", "Enchant creature", "Crew 3" are all
    keyword abilities, not effects. Requiring the whole line to be bare words
    rejects every one of them, which is where a large share of apparent
    "unparsed" text was coming from.
    """
    lowered = line.lower()
    vocabulary = sorted(known | EXTRA_KEYWORDS, key=len, reverse=True)

    for keyword in vocabulary:
        if not keyword:
            continue
        if lowered == keyword:
            return Ability(kind="keyword", text=line)
        if lowered.startswith(keyword) and len(lowered) > len(keyword):
            tail = lowered[len(keyword):]
            if tail[0] in " —-:{":
                param = _KEYWORD_PARAM.match(tail).group(1).strip(" .")
                return Ability(
                    kind="keyword",
                    text=line,
                    effects=(Effect("keyword", (("name", keyword), ("param", param))),),
                )

    # A pure comma-separated list of keywords, e.g. "Flying, vigilance".
    if _KEYWORD_LINE.match(line):
        parts = [p.strip().lower() for p in re.split(r"[,;]", line)]
        if parts and all(p in known for p in parts):
            return Ability(kind="keyword", text=line)

    return None


def parse_text(text: str, card_name: str = "", keywords: Iterable[str] = ()) -> Parsed:
    """Parse oracle text into abilities and effects."""
    known = {k.lower() for k in keywords}
    body = normalise(text, card_name)

    abilities: list[Ability] = []
    for line in (l.strip() for l in body.split("\n")):
        if line:
            abilities.append(_parse_line(line, known))

    return Parsed(card_name=card_name, abilities=tuple(abilities), keywords=frozenset(known))


def _parse_line(line: str, known_keywords: set[str]) -> Ability:
    # A keyword ability names a rule; it is not text to be parsed into effects.
    keyword = _keyword_ability(line, known_keywords)
    if keyword is not None:
        return keyword

    trigger_match = _TRIGGERED.match(line)
    if trigger_match:
        _, condition, body = trigger_match.groups()
        effects, unparsed = _parse_clauses(body)
        return Ability("triggered", line, effects, unparsed, trigger=condition.strip())

    activated_match = _ACTIVATED.match(line)
    if activated_match and "{" in activated_match.group(1):
        cost, body = activated_match.groups()
        effects, unparsed = _parse_clauses(body)
        return Ability("activated", line, effects, unparsed, cost=cost.strip())

    effects, unparsed = _parse_clauses(line)
    return Ability("spell", line, effects, unparsed)


def _parse_clauses(body: str) -> tuple[tuple[Effect, ...], tuple[str, ...]]:
    effects: list[Effect] = []
    unparsed: list[str] = []

    for clause in _CLAUSE_SPLIT.split(body):
        clause = clause.strip(" .;")
        if not clause:
            continue
        matched = [e for pattern in PATTERNS if (e := pattern.match(clause))]
        if matched:
            # One clause can carry several verbs ("draw a card, then discard a
            # card"), so all matches are kept rather than only the first.
            effects.extend(matched)
        else:
            unparsed.append(clause)

    return tuple(effects), tuple(unparsed)


def parse_card(card: Card) -> Parsed:
    """Parse every printed side, not just the top-level text.

    Each face is parsed under its *own* name because `normalise` substitutes the
    card name with `~`: the text of Fire reads "Fire deals 2 damage", and matching
    it against the joined "Fire // Ice" would leave the clause unrecognised. So this
    is a correctness requirement rather than tidiness.

    Falls back to the top-level text when a card has no faces attached — cards built
    straight from a Scryfall row, as the tests do, never went through the store.
    """
    if not card.faces:
        return parse_text(card.oracle_text, card.name, card.keywords)

    abilities: list[Ability] = []
    for face in card.faces:
        if face.oracle_text.strip():
            abilities.extend(
                parse_text(face.oracle_text, face.name, card.keywords).abilities)
    return Parsed(card_name=card.name, abilities=tuple(abilities),
                  keywords=frozenset(card.keywords))


def with_effects(card: Card) -> Card:
    """A copy of `card` carrying its parsed effects."""
    from dataclasses import replace

    return replace(card, effects=parse_card(card).effects)


# --- coverage reporting -------------------------------------------------


@dataclass
class Coverage:
    cards: int = 0
    fully_parsed: int = 0
    vanilla: int = 0
    unread: int = 0
    """Cards whose text lives on faces we do not load. Not vanilla — unread."""
    clauses: int = 0
    matched: int = 0
    verb_counts: dict[str, int] = field(default_factory=dict)
    misses: dict[str, int] = field(default_factory=dict)

    @property
    def card_rate(self) -> float:
        return self.fully_parsed / self.cards if self.cards else 0.0

    @property
    def readable(self) -> int:
        """Cards whose text we can actually see. The honest denominator."""
        return self.cards - self.unread

    @property
    def clause_rate(self) -> float:
        return self.matched / self.clauses if self.clauses else 0.0

    def top_misses(self, n: int = 25) -> list[tuple[str, int]]:
        return sorted(self.misses.items(), key=lambda kv: -kv[1])[:n]

    def top_verbs(self, n: int = 25) -> list[tuple[str, int]]:
        return sorted(self.verb_counts.items(), key=lambda kv: -kv[1])[:n]


_NUMBERS = re.compile(r"\b\d+\b")


def measure(cards: Sequence[Card]) -> Coverage:
    """Parse a corpus and report how much of it was actually understood."""
    report = Coverage()

    for card in cards:
        parsed = parse_card(card)
        report.cards += 1

        # A card with no clauses cannot fail one, so `fully_parsed` is True for
        # anything textless — correct for a vanilla bear, and a lie for a card whose
        # text we simply never read. Counting those as wins put 886 cards in the
        # success column the parser had not seen a word of.
        #
        # Readability is now a property of the faces, not of the top-level field:
        # a multi-face card *always* has a null `oracle_text`, so testing that would
        # keep reporting 886 unread long after the text became reachable.
        text = "".join(f.oracle_text for f in card.faces) if card.faces else card.oracle_text
        if card.has_faces and not card.faces:
            report.unread += 1          # faces exist upstream but were not loaded
            continue

        if not text.strip():
            report.vanilla += 1
        if parsed.fully_parsed:
            report.fully_parsed += 1

        for effect in parsed.effects:
            report.verb_counts[effect.verb] = report.verb_counts.get(effect.verb, 0) + 1
        report.matched += len(parsed.effects)
        report.clauses += len(parsed.effects) + len(parsed.unparsed)

        for clause in parsed.unparsed:
            # Collapse numbers so "deals 3 damage" and "deals 5 damage" report
            # as one gap rather than as many.
            key = _NUMBERS.sub("N", clause.lower())[:70]
            report.misses[key] = report.misses.get(key, 0) + 1

    return report
