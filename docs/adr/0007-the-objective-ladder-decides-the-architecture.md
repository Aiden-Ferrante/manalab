# ADR 0007: the objective ladder decides the architecture

Date: 2026-08-11
Status: accepted

## Context

`docs/search-problem.md` posed the deck-search architecture as a fork on one
falsifiable hypothesis: if variance in the objective is mostly explained by
*composition* (role counts), search the low-dimensional simplex first and
assign card identities afterwards; if *identity* dominates, the synergy
hypergraph is load-bearing and composition is only a constraint.

The obvious failure mode was deciding this by taste — hypergraphs are
interesting, simplexes are tractable, and either preference could have been
argued indefinitely. The other failure mode was deciding it *once*: any single
measurement is conditioned on an objective, and every objective this project
can currently compute is known-gameable in a named way.

## Decision

**The architecture is decided by a standing experiment, rerun at every objective
rung, not by a one-time verdict.** `examples/composition_variance.py` is that
experiment: fixed design (48 compositions × 6 identities, 300 CRN games, noise
floor measured on a second seed and subtracted), one number out — the
composition share of explainable variance — and the framework table in
`search-problem.md` §4 activates columns according to it.

Three rungs are on record:

| Objective | Composition share | Identity share |
|---|---|---|
| `consistency_t4` | 86.6% | 13.4% |
| `throughput` | 67.7% | 32.3% |
| `throughput+synergy@0.5` | 46.4% | **53.6%** |

The movement is monotone, was predicted in direction before each run, and each
rung's gameable edge (lands-rail, big-mana drift) was closed by the next rung's
objective rather than patched in the searcher.

## Consequences

**As of rung 3 the hypergraph column is load-bearing.** Identity carries the
majority of explainable variance, so identity-level machinery — port-closing
assignment, synergy terms, eventually hyperedge weights — is now on the
critical path, not the wish list. The two-level decomposition survives as the
outer loop.

**Objectives are versioned artifacts.** Each rung lives in
`search/objective.py` with its known gameability written into its docstring at
birth. An objective without a stated edge is an objective nobody has looked at
hard enough.

**The experiment is part of the definition of done for any new objective.**
A rung that has not been through the variance decomposition has not been
adopted; its share number joins the table above or it does not ship.

**What would change this decision:** an evaluator change that breaks the CRN
pairing or the noise-floor estimate (both assumptions are stated in the
experiment's docstring), or a rung where the share moves *against* the
predicted direction — that would mean the mechanism is not understood, and the
ladder pauses until it is.
