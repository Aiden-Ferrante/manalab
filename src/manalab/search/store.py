"""Persisting runs, so a claim survives the session that produced it.

Keyed by the trace digest: an identical run stored twice is one row, and a run
that *should* have been identical but isn't shows up immediately as a second
row. That makes the reproducibility gate a property of the data, not of a test
someone remembers to run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import duckdb

from manalab.search.trace import Trace

DEFAULT_DB = Path("data/search.duckdb")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       VARCHAR PRIMARY KEY,
    problem      VARCHAR,
    optimizer    VARCHAR,
    seed         BIGINT,
    budget       BIGINT,
    games_spent  BIGINT,
    n_evals      BIGINT,
    best_score   DOUBLE,
    best_stderr  DOUBLE,
    best_vector  VARCHAR,
    config       VARCHAR,
    problem_spec VARCHAR,
    created_at   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evaluations (
    run_id           VARCHAR,
    step             BIGINT,
    cumulative_games BIGINT,
    tag              VARCHAR,
    score            DOUBLE,
    stderr           DOUBLE,
    games            BIGINT,
    stream           BIGINT,
    vector           VARCHAR
);
"""


class ResultStore:
    def __init__(self, db_path: Path = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.db_path))
        self._con.execute(_SCHEMA)

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "ResultStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def save(self, trace: Trace, problem_spec: Mapping[str, Any] | None = None) -> str:
        run_id = trace.digest()
        if self._con.execute(
            "SELECT 1 FROM runs WHERE run_id = ?", [run_id]
        ).fetchone():
            return run_id  # identical run already recorded

        best = trace.best
        self._con.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                run_id,
                trace.problem,
                trace.optimizer,
                trace.seed,
                trace.budget,
                trace.games_spent,
                len(trace),
                best.score if best else None,
                best.stderr if best else None,
                json.dumps(list(best.vector)) if best else None,
                json.dumps(trace.to_dict()["config"], sort_keys=True),
                json.dumps(problem_spec or {}, sort_keys=True, default=str),
                datetime.now(timezone.utc),
            ],
        )

        rows = [
            (
                run_id,
                ev.step,
                ev.cumulative_games,
                ev.tag,
                ev.estimate.score,
                ev.estimate.stderr,
                ev.estimate.games,
                ev.estimate.stream,
                json.dumps(list(ev.estimate.vector)),
            )
            for ev in trace
        ]
        if rows:
            self._con.executemany(
                "INSERT INTO evaluations VALUES (?,?,?,?,?,?,?,?,?)", rows
            )
        return run_id

    def summary(self, problem: str | None = None):
        """One row per (optimizer, budget): mean best score across seeds."""
        where = "WHERE problem = ?" if problem else ""
        params = [problem] if problem else []
        return self._con.execute(
            f"""
            SELECT optimizer, budget,
                   count(*)          AS runs,
                   avg(best_score)   AS mean_best,
                   stddev(best_score) AS sd_best,
                   avg(games_spent)  AS mean_games
            FROM runs {where}
            GROUP BY optimizer, budget
            ORDER BY budget, mean_best DESC
            """,
            params,
        ).fetchall()

    def count(self) -> int:
        (n,) = self._con.execute("SELECT count(*) FROM runs").fetchone()
        return int(n)
