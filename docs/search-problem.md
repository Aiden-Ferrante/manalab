# The deck-search problem, stated precisely

*2026-08-11. The problem description M2's next phase optimizes against, and the
mathematical frameworks that fit each part of its structure. Companion to
`M2_PROMPT.md` (the harness) and ADRs 0002/0004 (the seam, honest modelling).*

---

## 1. The object

A deck is a **multiset** over a card pool: `D : C → ℕ` with

- `Σ D(c) = 60` (or 100),
- `D(c) ≤ 4` except basic lands (Commander: `≤ 1`),
- format legality and color identity as membership constraints on `C`.

The feasible set is the integer points of a scaled simplex intersected with box
constraints — a lattice polytope. Its size is the first honest fact: even a
*curated* 250-card pool admits on the order of 10⁶⁰ legal 60-card decks; the full
legal pool is ~10¹⁵⁰⁺. Enumeration is not a tool here. Structure is.

## 2. The objective

`f(D)` is whatever the `Evaluator` seam returns. Three layers, in increasing
honesty and cost:

1. **Analytic** — hypergeometric identities over the multiset. Karsten's tables
   are this; we reproduce them. Closed-form, exact, narrow.
2. **Goldfish simulation** — the current `ConsistencyEvaluator`. Stochastic:
   `f(D) = E[g(D, ω)]` over shuffles `ω`, observed with noise; CRN gives paired
   comparisons a 5.8× variance reduction (ADR 0004).
3. **Games against a metagame** — eventually `f(D, M)` against an opponent
   distribution `M`. The objective becomes game-theoretic and moves under you.

Everything below is written against the seam, not against goldfish. The seam is
the reason the search layer outlives the simulator.

## 3. The structure that makes it searchable

Five properties. Each one licenses a framework; ignoring any one of them is a
known failure mode of naive deck optimizers.

**(a) Synergy is k-ary, not pairwise.** A three-piece combo has value only when
all three pieces are present; every pair is worthless. Pairwise models
(graphs, quadratic objectives) structurally cannot represent this — they smear
combo value across edges that individually mean nothing. The natural object is a
**weighted hypergraph** `H = (C, E, w)`: vertices are cards, a hyperedge is a
*package* — the minimal set that jointly does something — with weight for how
much. Deck value gains a term `Σ_{e ⊆ supp(D)} w(e)`.

**(b) Value is submodular and supermodular at once.** Redundancy has
diminishing returns (the 4th board wipe is worth less than the 1st) —
submodular. Combos are complementarities (the pieces are worth more together
than apart) — supermodular. Neither theory alone applies; the mix is the
problem's signature.

**(c) Cards are exchangeable within roles.** Deck value is invariant under
permutation and *nearly* invariant under substitution inside a functional group
— swap one 2-mana removal spell for another and `f` barely moves. The
`face_types` classification and the effect verbs define these groups
mechanically. This licenses a **two-level decomposition**: search over the
*composition* (how many lands, how many ≤2-drops, how many removal slots — a
low-dimensional integer simplex), then instantiate each slot with the best
member of its group (an assignment problem).

**(d) The mana base is a nearly separable inner problem.** Given the spells,
choosing lands is close to a solved analytic subproblem (Karsten). This makes
the whole thing **bilevel**: outer search over spells, inner closed-form or
cheap solve for lands. Never spend simulation budget learning what the
hypergeometric distribution already says.

**(e) The noise has known form.** Draws are hypergeometric; some statistics
have closed forms and every simulated statistic has a variance we can estimate.
Comparisons, not point estimates, are the primitive — and CRN makes comparisons
cheap.

## 4. The frameworks, mapped

| Structure | Framework | What it buys | Plugs into |
|---|---|---|---|
| (a) k-ary synergy | **Hypergraphs**: dense-subhypergraph mining, hypergraph clustering/partitioning, spectral methods | "Pick k cards maximizing package weight" *is* densest-k-subhypergraph; clustering finds archetypes without being told them | hyperedges built from effect verbs (§5) |
| (b) mixed curvature | **Submodular optimization** (greedy with 1−1/e guarantees) for coverage terms; **BP decomposition** (submodular + supermodular parts split explicitly) for the mix | Principled greedy for the goodstuff core; combos handled as explicit supermodular terms on known hyperedges rather than pretending they don't exist | `objective.py` term structure |
| (c) role symmetry | **Two-level / mean-field**: composition simplex first, assignment second | Collapses 10⁶⁰ decks to a composition space of maybe 10⁴ points, each cheap to evaluate; identity-level search happens only inside the winning compositions | `face_types` + verb groups |
| (d) bilevel mana | **Bilevel optimization**, inner problem analytic | Every outer candidate is auto-fitted with its best mana base before evaluation; search never wastes budget on fixable mana | Karsten machinery in `game/mana` |
| (e) stochastic f | **Simulation optimization**: ranking & selection (OCBA), racing, bandits over neighborhoods; **multi-fidelity** (analytic screen → goldfish → engine); **combinatorial Bayesian optimization** with a multiset kernel if sample-efficiency becomes binding | Spend games where the comparison is close; kill obviously-dominated candidates at fidelity 0 for free | `budget.py`, `compare.py` (CRN) |
| the walk itself | **Local search on the lattice**: 1-out-1-in swaps, large-neighborhood moves (re-solve a whole role group), annealing/population variants | The only part that is commodity; everything above decides *which* neighborhood and *how to compare* | `moves.py`, `runner.py` |
| the outer game (later) | **Empirical game theory / double oracle (PSRO)**: best-respond to the meta-mixture, add to pool, re-equilibrate | Turns "best deck" into the well-posed "best response to M" once opponents exist | future engine evaluator |

## 5. Where hyperedges come from

The honest weakness of the hypergraph frame is edge discovery — the packages
have to come from somewhere. Three sources, in order of trust:

1. **Typed interfaces from effect verbs.** Every parsed card exposes *provides*
   and *requires* ports: `create_token` provides `token`; a sacrifice outlet
   requires it. `put_counters` provides `counters(kind)`; proliferate requires
   them. A hyperedge is a minimal provider/consumer matching. This is mechanical,
   local, keyless — and it is what the effects layer was for. Coverage today is
   65.6% with unparsed clauses named, so edge recall is bounded and *known*.
2. **Explicit combo lists** (hand-curated or imported once): supermodular terms
   too semantic for port-matching ("these three go infinite").
3. **Co-occurrence in real decklists**, if a corpus is ever imported: hyperedges
   as frequent itemsets. Deferred — external data, and confounded by popularity.

## 6. The load-bearing hypothesis — test this first

> **Most of the variance in `f` across legal decks is explained by composition
> (role counts), not by card identity within roles.**

If true, the two-level decomposition is the architecture and everything else
refines it. If false — identity dominates, synergy hyperedges carry the value —
the hypergraph terms are load-bearing and composition is just a constraint.

It is cheaply falsifiable with machinery that already exists: sample decks
uniformly (Phase 1), group by composition vector, run the variance decomposition
`Var(f) = Var(E[f|comp]) + E[Var(f|comp)]` under CRN. One experiment, one
number, and it decides which column of the table above leads.

## 7. Order of attack

1. The variance-decomposition experiment (§6). Architecture-deciding, cheap.
2. Bilevel mana fitting as a fixture: every candidate deck gets its Karsten-fit
   land base before evaluation, permanently.
3. Composition-level search on the simplex with the existing harness — greedy /
   local moves over role counts, goldfish objective.
4. Provide/require port extraction from effect verbs; first synergy hyperedges;
   add explicit supermodular terms for a curated combo list.
5. Identity-level assignment inside winning compositions.
6. Only then: fancier machinery (BO with multiset kernels, PSRO) — each admitted
   on evidence from the harness, per M2's own rule: ranked, statistically
   defensible comparisons, not a pile of optimizers.

*The prior that governs all of it (ARCHITECTURE.md): the objective function
matters more than simulator fidelity. Every framework above is written against
the seam, so the simulator stays disposable.*
