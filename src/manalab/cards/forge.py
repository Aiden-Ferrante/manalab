"""Forge card scripts as an external oracle for card semantics. Keyless, stdlib-only.

Every other source this project reads — Scryfall, MTGJSON — publishes what a card
*says*. `effects.py` then has to work out what it *does*, from English, with
regexes. Forge is the only freely available corpus that publishes the second
thing: ~33,700 cards hand-encoded as verb plus named parameters, maintained by
the people who run them in an actual rules engine.

The encoding is close enough to `Effect(verb, params)` to compare directly:

    Name:Nameless Inversion
    ManaCost:1 B
    Types:Kindred Instant Shapeshifter
    K:Changeling
    A:SP$ Pump | ValidTgts$ Creature | NumAtt$ +3 | NumDef$ -3 | SubAbility$ DBAnimate
    SVar:DBAnimate:DB$ Animate | Defined$ Targeted | RemoveCreatureTypes$ True

Two things to notice, because they are exactly what this module exists to catch.
`NumAtt$` and `NumDef$` are *separate fields*, so a pump that is +3 power and -3
toughness cannot be collapsed into one number. And the "loses all creature types"
rider is not dropped — it hangs off `SubAbility$`, which is why `effect_chain()`
follows those links rather than reading the first ability and stopping.

**This is an oracle, not a source.** We read it to find out where our own parse
disagrees; we do not import its ontology and we do not ship its data. Forge is
GPL-3.0, so the scripts stay in `data/` — a gitignored, rebuildable build
artifact, exactly like the Scryfall corpus (ADR 0008). Nothing here is copied
into the repo and nothing here is redistributed.

Coverage against our own corpus, measured rather than claimed: 33,287 of 35,142
cards (94.7%) have a script. The misses are mostly emblems, planes and tokens.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO = "https://github.com/Card-Forge/forge.git"
CARDS_SUBDIR = "forge-gui/res/cardsfolder"

# Forge splits a multi-part card into whole card blocks separated by this token.
_ALTERNATE = "ALTERNATE"

# `A:SP$ DealDamage | NumDmg$ 3 | ...` — the verb sits behind a mode sigil.
# SP = spell, AB = activated, DB = sub-ability (the target of a `SubAbility$`),
# ST = static. We keep the sigil: an AB costs mana to use and an SP does not,
# and conflating them would make an activated ability look like a cast trigger.
_HEAD = re.compile(r"^(?P<mode>SP|AB|DB|ST)\$\s*(?P<verb>[A-Za-z_]+)\s*(?P<rest>.*)$")


@dataclass(frozen=True)
class ForgeAbility:
    """One Forge ability. `kind` is the script line type it came from.

    A = activated or spell, T = triggered, R = replacement, S = static.
    The last three are the categories our `Effect` has nowhere to put, which is
    why they are worth carrying even though nothing consumes them yet.
    """

    kind: str
    mode: str
    verb: str
    params: tuple[tuple[str, str], ...] = ()

    def get(self, key: str, default: str | None = None) -> str | None:
        return dict(self.params).get(key, default)


@dataclass(frozen=True)
class ForgeCard:
    name: str
    mana_cost: str
    types: str
    pt: str
    oracle: str
    keywords: tuple[str, ...] = ()
    abilities: tuple[ForgeAbility, ...] = ()
    # `SVar:DBDraw:DB$ Draw | ...` — named fragments that abilities point at.
    svars: tuple[tuple[str, str], ...] = ()

    def effect_chain(self) -> tuple[ForgeAbility, ...]:
        """Every ability on the card, with `SubAbility$` links followed.

        Reading only `abilities` sees the *first* clause of a card and stops,
        which is precisely the failure mode being audited on our side — a rider
        that resolves after the main effect looks like it does not exist. Cycles
        are impossible in well-formed scripts but are guarded anyway; a malformed
        script should degrade to a short chain, never hang the run.
        """
        by_name = dict(self.svars)
        out: list[ForgeAbility] = []
        seen: set[str] = set()

        def walk(ability: ForgeAbility) -> None:
            out.append(ability)
            nxt = ability.get("SubAbility")
            while nxt and nxt not in seen:
                seen.add(nxt)
                body = by_name.get(nxt)
                if not body:
                    return
                sub = _ability("A", body)
                if sub is None:
                    return
                out.append(sub)
                nxt = sub.get("SubAbility")

        for ability in self.abilities:
            walk(ability)
        return tuple(out)

    @property
    def verbs(self) -> tuple[str, ...]:
        return tuple(a.verb for a in self.effect_chain())


def slug(name: str) -> str:
    """Forge's filename for a card.

    Apostrophes are *deleted* rather than turned into separators — "Saheeli's
    Artistry" is `saheelis_artistry`. Getting that wrong silently loses ~6% of
    the corpus to phantom misses, which is how this rule was found.
    """
    cleaned = name.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")


def parse_script(text: str) -> tuple[ForgeCard, ...]:
    """Parse one `.txt` script. Returns one card per ALTERNATE block."""
    blocks = [b for b in re.split(rf"^{_ALTERNATE}$", text, flags=re.M) if b.strip()]
    return tuple(c for c in (_parse_block(b) for b in blocks) if c is not None)


def _parse_block(block: str) -> ForgeCard | None:
    fields: dict[str, str] = {}
    keywords: list[str] = []
    abilities: list[ForgeAbility] = []
    svars: list[tuple[str, str]] = []

    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        tag, _, body = line.partition(":")

        if tag == "K":
            keywords.append(body.strip())
        elif tag == "SVar":
            var_name, _, var_body = body.partition(":")
            svars.append((var_name.strip(), var_body.strip()))
        elif tag in ("A", "T", "R", "S"):
            ability = _ability(tag, body.strip())
            if ability is not None:
                abilities.append(ability)
        elif tag not in fields:
            fields[tag] = body.strip()

    if "Name" not in fields:
        return None
    return ForgeCard(
        name=fields["Name"],
        mana_cost=fields.get("ManaCost", ""),
        types=fields.get("Types", ""),
        pt=fields.get("PT", ""),
        oracle=fields.get("Oracle", ""),
        keywords=tuple(keywords),
        abilities=tuple(abilities),
        svars=tuple(svars),
    )


def _ability(kind: str, body: str) -> ForgeAbility | None:
    """`SP$ DealDamage | NumDmg$ 3 | ...` -> one ability.

    Triggered and replacement lines lead with their own keys and carry the actual
    effect behind `Execute$`, so the verb is not always in first position. All
    16,961 `T:` and 7,088 `S:` lines lead with `Mode$`; all 1,692 `R:` lines lead
    with `Event$` — counted over the corpus rather than assumed, after a first
    draft that only knew about `Mode$` silently dropped every replacement effect.
    That is the same class of defect this oracle exists to catch, so it is worth
    saying plainly: a line we cannot shape is kept as its descriptor, never
    discarded, because an ability we cannot model is still evidence the card has
    one.
    """
    head = _HEAD.match(body)
    if head:
        params = _params(head.group("rest"))
        return ForgeAbility(kind, head.group("mode"), head.group("verb"), params)

    params = _params(body)
    lookup = dict(params)
    for descriptor in ("Mode", "Event"):
        if lookup.get(descriptor):
            return ForgeAbility(kind, "", lookup[descriptor], params)
    return None


def _params(rest: str) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for chunk in rest.split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, value = chunk.partition("$")
        if not sep:
            continue
        out.append((key.strip(), value.strip()))
    return tuple(out)


def load(cards_dir: Path | str) -> dict[str, ForgeCard]:
    """Every script under `cards_dir`, keyed by `slug(name)`.

    Keyed by the *card's own name* rather than by filename, so an ALTERNATE block
    ("Fire" inside `fire_ice.txt`) is reachable under its own name.
    """
    root = Path(cards_dir)
    out: dict[str, ForgeCard] = {}
    for path in sorted(root.rglob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for card in parse_script(text):
            out.setdefault(slug(card.name), card)
    return out


def default_dir(data_dir: Path | str = "data") -> Path:
    return Path(data_dir) / "forge" / CARDS_SUBDIR


def fetch(data_dir: Path | str = "data", *, force: bool = False) -> Path:
    """Sparse-checkout Forge's card scripts into `data/forge/`.

    A blobless, depth-1, sparse clone: we want ~34k text files, not 74k commits
    of Java. Records the commit in a sidecar so a disagreement found today can be
    re-checked against the same upstream state later — an oracle that silently
    moves under you is not an oracle.

    Requires `git` on PATH. Returns the cardsfolder path.
    """
    root = Path(data_dir) / "forge"
    cards = root / CARDS_SUBDIR
    meta = root / "provenance.json"

    if cards.exists() and not force:
        return cards

    root.parent.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", "--depth", "1",
             REPO, str(root)],
            check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(root), "sparse-checkout", "set", CARDS_SUBDIR],
                   check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(root), "checkout"],
                   check=True, capture_output=True, text=True)

    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            check=True, capture_output=True, text=True).stdout.strip()
    meta.write_text(json.dumps({
        "source": REPO,
        "commit": commit,
        "subdir": CARDS_SUBDIR,
        "scripts": sum(1 for _ in cards.rglob("*.txt")),
        "license": "GPL-3.0 (not redistributed; see ADR 0008 and ATTRIBUTION.md)",
    }, indent=2) + "\n")
    return cards
