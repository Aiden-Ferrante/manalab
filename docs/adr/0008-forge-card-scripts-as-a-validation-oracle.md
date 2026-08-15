# ADR 0008: Forge card scripts as a validation oracle

Date: 2026-08-15
Status: accepted

## Context

Every check this project had was internal. Unit tests exercise boards we built,
against expectations we wrote. Parse coverage is computed by the same parser it
grades. ADR 0004's machinery makes *measurements* honest, but nothing outside the
project ever said whether a card means what we think it means.

The 2026-08-15 audit found what that buys. Three defect classes reached the
faithful pool — the tier `evaluate.pool` hands to search as trustworthy:

1. Text dropped and honestly recorded. `fidelity` refuses the card. This works.
2. Text dropped and **not** recorded: `coverage=1.0`, `unparsed=()`, and the
   engine executes half the card. 211 of 1,397 faithful cards.
3. Text fully parsed and the **meaning** mis-encoded. Nothing is dropped, so
   coverage is honestly 1.0 and the card still does the wrong thing —
   *Life Goes On* gains 12 life instead of 4 because "instead" is a replacement
   and we store two additive effects.

Class 3 is the important one: **no coverage metric can detect it**, because
nothing was lost. It is invisible to every instrument we own. ADR 0001 already
named this shape as the failure to avoid — measuring against something that
shares your bias is undetectable from inside the loop — and named 17Lands as the
answer. But 17Lands validates *outcomes*. It cannot tell us that Nameless
Inversion is a removal spell.

ADR 0006 deferred benchmarking external parsers (CubeArtisan, Demystify,
oracle-parser). Revisiting that, the framing was wrong. Those are *parsers* —
they share our problem of reading English. What we needed was a corpus where
somebody already did the reading.

## Decision

**Adopt Forge's `res/cardsfolder` card scripts as an external oracle for card
semantics — to validate our parse, not to replace it.**

Forge publishes ~33,700 cards as verb plus named parameters, maintained by people
who execute them in a rules engine. Measured against our corpus: 100% of
modern-legal cards, 93.3% of all 35,142 rows (the remainder is mostly emblems,
planes and tokens we do not want).

The encoding is close enough to `Effect(verb, params)` — which ADR 0005 arrived
at independently — to diff directly:

    A:SP$ Pump | ValidTgts$ Creature | NumAtt$ +3 | NumDef$ -3 | SubAbility$ DBAnimate

`NumAtt$` and `NumDef$` are separate fields, so `max(power, toughness)` is not
expressible. The "loses all creature types" rider hangs off `SubAbility$` rather
than being dropped. Both of the audit's critical defects are structurally absent
from that schema.

The reason to trust it over another regex layer is not that the authors are
smarter. It is that **their encodings are correctness-pressured**: a wrong script
makes a rules engine play a wrong game, and somebody files a bug. Our regexes had
no such pressure, which is precisely how Class 3 survived.

`examples/forge_validation.py` reports four disagreement classes on cards we call
faithful, since those are the ones we actually execute.

## Consequences

**Validation, deliberately, and not replacement.** Two reasons, one practical and
one legal.

Practically, the oracle is most valuable as a *disagreement detector*. It turns
the hand-written 43-card golden set into ~32,800 machine-checked cards, and it
partitions our misses into "verb we never implemented", "parameters we dropped"
and "genuinely hard" — which is a work queue, not just a score.

Legally: **Forge is GPL-3.0, and the scripts carry no separate grant.** Reading a
local clone to compare against is not distribution. Vendoring a derived corpus
into a repo we publish is a copyleft question, and it must be answered
deliberately before any importer is written rather than discovered afterwards.
So the scripts live in gitignored `data/forge/`, fetched on demand, exactly like
the Scryfall corpus — a rebuildable build artifact, never committed, never
redistributed. `fetch()` records the upstream commit, because an oracle that
moves silently under you is not an oracle.

**What this does not settle.** Forge's encoding is engine-idiomatic rather than a
normalized logical form: `SVar:` indirection, AI hints, Forge-specific
conventions. It is a strong reference, not a neutral standard, and where it and
we disagree the correct reading still has to be judged. Adopting its ontology
wholesale would be a different and much larger decision.

**The cheaper second oracle we already have.** `data/oracle_tags.jsonl.gz` is
already on disk: Scryfall's Tagger labels, 4,520 tags across ~93% of cards. No
new dependency and no licensing question beyond the ones we already accept. It
carries no parameters, so it cannot catch Class 3 — but it is free and it is
sitting there.

**On the roadmap.** M4 was recorded as "Forge-backed evaluator (needs JDK 17+)"
and parked on a Java version this box does not have. That was a misreading of
where Forge's value is. The card semantics are plain text files; reading them
needs no JVM at all. The blocked part was only ever the *engine*.

This is the first instrument attached to the chart's "Validate against something
outside the simulator" group, which the audit called the open flank and which had
been deliberately empty since it was created.
