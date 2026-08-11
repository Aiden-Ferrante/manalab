# GOAL PROMPT — manalab M2: Deckbuilding Search Benchmark

## Context

You are working in `~/Desktop/code/manalab`, a Python 3.12 project (uv; the only
runtime dependency is duckdb). It is a Magic: the Gathering **deckbuilding search
engine that happens to contain a simulator** — the simulator is the disposable
part, the search machinery is built to last.

Read `ARCHITECTURE.md` first. Then skim `src/manalab/evaluate/__init__.py`, which
defines the only boundary that matters.

**Current state.** M0 and M1 are complete and verified:

- `manalab.cards` — Scryfall bulk → DuckDB (35,139 cards). `Card`, `ManaCost`,
  `Decklist` (a count-map over card names), `CandidatePool` (ordered pool giving
  `to_vector`/`from_vector`, copy limits, deck size). CLI: `manalab fetch|build|info`.
- `manalab.game` — abstract goldfish sim. Shuffling, London mulligans with
  pluggable policies, bipartite-matching mana payment, hand-aware land sequencing,
  greedy curve-out. No opponent, no interaction.
- `manalab.evaluate` — the seam. `Evaluator` protocol
  (`evaluate(deck, *, n_games, seed) -> EvalResult`), `EvalResult` (scalar
  `metrics`, per-game `samples`, `unmodeled`, `stderr`, `ci95`), and `Objective`
  (`EvalResult -> float`). One implementation: `ConsistencyEvaluator`.
- `manalab.search` — **empty**. Only a docstring stating the contract. This is you.
- 45 tests pass. `examples/karsten_validation.py` reproduces Frank Karsten's
  colored-source tables (14 sources → 90.7% for a turn-1 single pip).

Metrics currently available from `ConsistencyEvaluator`: `p_on_curve_t{2..5}`,
`mana_t{2..5}`, `mulligans`, `kept_hand`, `missed_land_drops`, `mana_spent`, and
per-target `castable_<card>_by_t<n>` / `cast_<card>_by_t<n>`.

---

## Mission

Build the deckbuilding search layer. But the deliverable is **a ranked,
statistically defensible comparison of optimization techniques on this problem**,
together with the harness that produced it — not a pile of optimizers.

That distinction is the whole point. On a noisy objective, every optimizer you
write will report that it found something good. Without a benchmark you cannot
tell which one is right, and the work is worthless. M2 is done when you can
answer, with confidence intervals:

> Given a fixed budget of B simulated games, which combination of variance
> reduction, budget allocation, and search strategy finds the best deck — by how
> much, and on which classes of problem?

That result survives replacing the goldfish simulator with a full rules engine.
Conclusions about Magic do not. Keep the two separate at all times.

---

## Problem

A deck is an integer vector **x** over an ordered candidate pool of *n* cards:

```
maximize    f(x) = E_ω [ g(x, ω) ]     objective, estimable only by sampling
subject to  Σ xᵢ = D                   deck size (60 constructed, 100 singleton)
            0 ≤ xᵢ ≤ uᵢ                copy limit (4, or 1 in singleton)
            xᵢ ∈ ℤ
```

This is **stochastic combinatorial optimization over a bounded integer simplex
with a noisy, expensive oracle**. The applicable literature is simulation
optimization, ranking-and-selection, and derivative-free optimization — not
gradient methods or convex programming.

Two structural facts to exploit. **Verify both empirically; do not assume them.**

1. The sum constraint makes the natural move a **swap**: `xᵢ -= 1; xⱼ += 1`
   preserves feasibility exactly. The search lives on one slice of the lattice
   and local moves need no repair operator.
2. The objective is probably **concave along single-card axes** — the 15th red
   source is worth less than the 10th. If diminishing returns hold, coordinate-wise
   integer line search is strong and a separable surrogate captures most of *f*.
   Measure the curvature and report it.

---

## Hard constraints

1. **`manalab.search` must never import `manalab.game`.** Enforced mechanically
   by `tests/test_architecture.py`. Reach the game only through the `Evaluator`
   protocol. If an optimizer needs to know about lands, expose a metric — do not
   reach through the boundary. This is what makes a future Forge-backed evaluator
   a drop-in rather than a rewrite.
2. **Budget is counted in simulated games, never wall clock.** Every optimizer
   takes a budget and reports exact consumption. Comparisons at unequal budget are
   meaningless; wall clock silently rewards whichever technique got the fast path.
3. **Everything is seeded and reproducible.** A run is a pure function of
   `(problem, optimizer, config, seed)`. Persist configs and results to DuckDB so
   any claim can be re-derived months later.
4. **Optimizer code never sees a `Card`.** Only `CandidatePool`, count vectors,
   and `EvalResult`.
5. Match the existing code's style: frozen dataclasses, explicit seeds, protocols
   over inheritance, comments that explain *why*. Keep runtime deps minimal; put
   anything heavier under an optional extra.

---

## Phases

Phases 0 → 1 → 2 → 3 are **strictly sequential** — doing variance reduction after
the optimizer comparisons invalidates them. Phase 4 fans out once 3 is stable.
Phase 5 may run alongside 4 but must land before any claim about Magic. Phases
6–8 are continuous.

**Stop and check in at each phase gate.** Report what you measured, then wait.

### Phase 0 — Harness
`Problem` (pool + evaluator + objective + start deck + budget), `Optimizer`
protocol (`optimize(problem, budget, seed) -> Trace`), `Trace` (every deck
evaluated with estimate, stderr, games spent, cumulative budget), `BudgetMeter`
(overrun raises, never warns), DuckDB results store keyed by config hash.

*Gate:* two runs at the same seed produce byte-identical traces.

### Phase 1 — Ground truth and baselines
You cannot rank optimizers without problems whose answer is known. Three tiers:

| Tier | Construction | Gives you |
|---|---|---|
| Analytic | Land-count / color-source questions with closed-form hypergeometric answers | Exact optimum, zero noise |
| Enumerable | Tiny real instance (pool 6–8, deck 12–20) brute-forced at high sample count | True optimum of the *actual* objective |
| Realistic | Full 60-card deck, 30–40 candidate pool | No known optimum; rank by held-out score |

Baselines every optimizer must beat, several of which are embarrassingly
competitive: random feasible sampling; a human reference decklist; Karsten-rule
construction with no search at all; coordinate-wise integer line search.

*Gate:* on the analytic tier some optimizer recovers the known optimum. If none
do, the harness is broken — not the optimizers.

### Phase 2 — Variance reduction
Do this **before** any optimizer work; it multiplies the effective budget of
everything downstream.

Implement: common random numbers; antithetic variates; control variates (the
analytic hypergeometric P(≥k lands in 7+t) has a *known* mean and correlates
hard with simulated on-curve outcomes); stratified sampling on opening-hand land
count; paired differencing.

**Exploit this coupling deliberately.** `random.shuffle` draws a permutation
depending only on list length and seed. Every deck is size *D* and
`Decklist.expand()` is canonically ordered, so the same seed yields the *same
positional permutation* — two decks differing by one swapped card see identical
draws except in the swapped slots. Near-ideal coupling for paired comparison. Be
honest about where it breaks: if one deck mulligans and the other does not, the
streams desynchronize from that point. Measure realized correlation.

*Gate:* report the measured variance-reduction factor per technique. Target ≥5×
from CRN + pairing alone. State what you measured, not what the textbook promises.

### Phase 3 — Budget allocation
Equal games per candidate is the largest waste available. This is
ranking-and-selection.

Implement: uniform (baseline); successive halving; Hyperband; sequential halving;
LUCB / UCB-E; **OCBA**; **KN++ indifference-zone** (guarantees correct selection
w.p. ≥ 1−α given zone δ); Hoeffding and Bernstein racing; Thompson sampling.

OCBA and KN++ are the two most people skip and the two designed most directly
for this problem. Include them.

*Gate:* probability-of-correct-selection vs budget for each allocator on the
enumerable tier, where the true best is known.

### Phase 4 — Search strategies
One good implementation per family beats three sloppy ones.

- **Local:** hill climbing on 1-swap; simulated annealing with a *noise-aware*
  acceptance rule (accepting on a noisy delta ≠ accepting on a true delta); tabu
  over recent swap pairs; variable-neighborhood (1-, 2-, k-swap); late-acceptance
  hill climbing; iterated local search with perturbation restarts.
- **Population:** genetic algorithm (uniform crossover on count vectors, repair to
  size *D*); **cross-entropy method** (a deck *is* a multinomial draw — unusually
  well matched); estimation-of-distribution algorithms; CMA-ES on relaxed weights,
  rounded and repaired.
- **Surrogate:** regularized linear model over counts (ridge/lasso) — the
  coefficients are literally learned card values, interpretable, and the natural
  test of the separability hypothesis; Bayesian linear + Thompson sampling;
  gradient-boosted or random-forest surrogate (SMAC-style); trust-region BO
  (TuRBO-style) for high-dimensional discrete; surrogate-assisted EA that screens
  cheaply and spends real games only on survivors.
- **Mathematical programming:** MIP for the mana base (minimize taplands subject
  to per-color source requirements; `pulp` bundles CBC and stays local/keyless);
  submodular greedy with its (1−1/e) guarantee *if* you verify approximate
  submodularity; Lagrangian relaxation of the size constraint.

*Gate:* every optimizer on all three tiers, ≥3 budgets × ≥10 seeds. Report mean
regret with CIs — never best-run-ever.

### Phase 5 — Objectives
Where the project either succeeds or produces nonsense.

**Optimizing `castable_*` naively yields degenerate decks.** Sixty one-drops
score beautifully on castability and play terribly, because castability is blind
to competition for mana. Every optimizer will find that deck. That is an
objective failure, not an optimizer failure.

Implement and compare: scalarized weighted sums; **constrained** (maximize clock
subject to consistency ≥ floor) via penalty, repair, and feasibility-preserving
moves — compare all three; **multi-objective** NSGA-II for a Pareto front over
(clock, consistency, resilience), which is more honest and more useful to a
deckbuilder than any scalar; Chebyshev scalarization for non-convex front
regions; **robust** CVaR over seeds rather than the mean, since a deck that is
good on average but catastrophic 10% of the time is a bad deck; distributionally
robust across several metagame scenarios.

*Gate:* **exhibit** the degenerate solution appearing under naive scalarization,
then show which formulation suppresses it. Demonstrating the failure is worth
more than asserting it.

### Phase 6 — Statistical validity
The trap that otherwise invalidates everything.

- **Winner's curse:** the max of *M* noisy estimates is biased upward by roughly
  `σ√(2 ln M / N)`. With M in the thousands this is routinely *larger than the
  improvement being claimed*.
- **Held-out seeds** — optimize on training seeds, report the final deck on fresh
  ones. This is a train/test split and it is mandatory.
- Bootstrap CIs on the *improvement over baseline*, not the raw score.
- Paired t-test / Wilcoxon on CRN-paired differences.
- Benjamini–Hochberg across the technique comparison table.
- Sequential testing (SPRT / mSPRT) for early stopping without inflating error.
- **Power analysis up front:** how many games to detect a 1% edge at 80% power?
  Answer before running, or you will run underpowered comparisons and interpret
  noise as signal.

*Gate:* in-sample vs held-out score for every optimizer's final deck. Expect a
visible gap. Report it rather than hiding it.

### Phase 7 — Interpretation
The output is one deck; the contribution is understanding why.

Marginal card value via paired swap deltas with CIs; Shapley values over card
inclusion (expensive, principled — sample them); functional ANOVA over which
decisions drive score variance; constraint sensitivity as land count is pinned,
yielding the consistency/clock frontier; surrogate coefficients as a learned
card-evaluation table checked against community intuition — **disagreements are
the interesting findings**.

### Phase 8 — Report
One page of findings, plus figures, plus a reproducibility appendix. Rank the
techniques. State what did *not* work: "successive halving plus CRN beats
everything fancier" is a legitimate and valuable conclusion.

Separate explicitly:
- conclusions about **optimization** (which technique wins) — survive a simulator upgrade
- conclusions about **Magic** (how many lands) — only as good as the goldfish
  model, and each must carry its `unmodeled` caveat

---

## Traps

1. **Reporting a proxy as strength.** The sim has no opponent. Never write "this
   deck is better" when you mean "this deck is more consistent."
2. **Unequal budgets.** Wall-clock comparisons will mislead you.
3. **Tuning on the test set.** Optimizer hyperparameters get training seeds only.
4. **Degenerate optima.** See Phase 5. Expect them; build for them.
5. **Believing the sim.** `EvalResult.unmodeled` is non-empty for most real decks.
   A deck full of cantrips is systematically undervalued, so search will
   systematically avoid cantrips. That is *bias*, not noise — more games will not
   fix it. Surface it in every Magic-facing conclusion.
6. Trap 5 is why M3 exists: validating against 17Lands, where real human outcomes
   are ground truth, is what tells you whether any of this transfers.

---

## Defensible minimum

If the full sweep is more compute than is warranted, this subset is a complete
and honest result, and everything else merely widens it:

Phase 0 · Phase 1 analytic + enumerable tiers · CRN and paired differencing from
Phase 2 · successive halving from Phase 3 · hill climbing, cross-entropy method,
and the linear surrogate from Phase 4 · the constrained formulation from Phase 5
· held-out validation from Phase 6.
