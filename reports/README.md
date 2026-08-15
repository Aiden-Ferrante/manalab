# Reports

Experiment output. **Read the replication status before believing any of it.**

## Everything here is archived, as of 2026-08-15

`archive/2026-08-15-pre-engine-fixes/` holds every run this project has produced.
None of it is current, and the reason is worth stating precisely, because it is
not the reason the last retraction gave.

On 2026-08-15 an audit found three defects that reached the **faithful pool** —
the tier `evaluate.pool` hands to search as trustworthy — each with
`fidelity.assess` reporting no problem at all:

- **43 of 102 pump cards were executed with the wrong arithmetic.** Both halves
  were collapsed with `max(power, toughness)`, so Nameless Inversion (+3/-3) was
  a permanent +3/+3 buff instead of a removal spell, and every all-negative
  shrink was a silent no-op.
- **90 of 819 faithful cards carried text the parser never read.** Pact of
  Negation was a free, drawback-free counterspell.
- **"you" meant "any player"**, so a card's own drawback was aimed at the
  opponent.

Every run in the archive was measured through that engine. The faithful pool has
since moved from 819 cards to 729, and blue lost the most of any colour.

### Why replication did not protect these

`replicates.txt` was the one file this README previously called trustworthy: 4
seeds, a measured noise floor of ±0.116, tiers instead of a ranking. All of that
was done correctly and none of it helped.

Replication answers "would another seed give a different number?" It cannot
answer "is the thing generating the number doing the right thing?" A wrong
engine is **bias**, and ADR 0004 already says what bias means here: more games
will never fix it. Ten seeds through an engine that turns removal spells into
buffs produce ten consistent readings of the wrong quantity.

So the archived results are not *refuted* — several may well reproduce. They are
**unrepeatable**: the machinery that produced them no longer exists, and nothing
in the record distinguishes a conclusion that survives the fixes from one that
does not. Re-running is the only way to tell.

### What is archived

| File | What it was |
|---|---|
| `replicates.txt` | 4 seeds × 2 gauntlet conditions; noise floor ±0.116, sweeper effect −0.006. Surviving claims at the time: black strongest 0.69 ± 0.06, blue weakest 0.26 ± 0.07, middle three not ordered. **Blue's weakness is the most suspect single result**, since blue lost the largest share of its pool to the fidelity fix. |
| `colors-with-spells.txt` | creature-only archetypes, engine with effect verbs |
| `colors-spell-gauntlet.txt` | burn and removal archetypes added |
| `colors-counterspells.txt` | counterspells added to the removal archetype |
| `colors-sweepers.txt` | sweepers preferred by the removal archetype |
| `coevo-before-verbs.txt` | 5 rounds, engine with no effect verbs |
| `coevo-after-verbs.txt` | 5 rounds, same script and seed, verbs implemented |

The four `colors-*.txt` files were **already retracted on 2026-08-13** as
single-run noise: the spread 0.538 → 0.527 → 0.412 → 0.379 → 0.609, narrated at
the time as verbs opening the metagame and sweepers closing it, is smaller than
the noise floor. That retraction stands on its own and is not superseded by this
one — they are independent failures, one of variance and one of correctness.

The co-evolution pair carries a further caveat: `compare_coevolution.py` still
diffs them, and two structural observations there never depended on effect size —
no champion from a final round holds Nash weight, and before verbs every
intransitive triple ran through zero-weight decks. Those may survive. The
magnitudes will not.

## Not archived

| File | Why it stays |
|---|---|
| `audit_effects.md` | A 30-card human precision audit of the *parser*, not a run of the engine. Still open: all 30 verdicts are unmarked, so the 2.11% figure quoted elsewhere remains an automated smell rate, not a human-verified precision number. |

## Reproducing

`examples/evolve_all_colors.py` replicates by default and prints tiers rather
than a ranking; `--seeds 1` warns. Note the known gap: at one run per label
`search/report.py` still prints a confident full ordering, because `stderr` is
0.0 for n < 2. Do not read a single-seed table as separable.
