"""The dependency contract, enforced mechanically rather than by prose.

If this test fails, the boundary described in ARCHITECTURE.md has leaked. The
one that matters most: `manalab.search` importing `manalab.game` would mean the
optimizer knows how the simulator works, and swapping in a rules engine later
stops being a drop-in change.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "manalab"

ALLOWED: dict[str, set[str]] = {
    "cards": set(),
    "game": {"cards"},
    "engine": {"cards"},
    "evaluate": {"cards", "game", "engine"},
    "search": {"cards", "evaluate"},
}

MODELS = ("game", "engine")
"""The two fidelity layers. Peers, not a succession — see ARCHITECTURE.md."""

LAYERS = tuple(ALLOWED)


def _layer_of(path: Path) -> str | None:
    rel = path.relative_to(SRC).parts
    return rel[0] if len(rel) > 1 and rel[0] in ALLOWED else None


def _manalab_imports(tree: ast.AST) -> set[str]:
    """Top-level manalab subpackages this module imports."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("manalab"):
            parts = (node.module or "").split(".")
            if len(parts) > 1:
                found.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "manalab" and len(parts) > 1:
                    found.add(parts[1])
    return found


def _modules() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if _layer_of(p))


def test_source_tree_is_discoverable() -> None:
    assert _modules(), f"no layered modules found under {SRC}"


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.name))
def test_dependency_direction(path: Path) -> None:
    layer = _layer_of(path)
    assert layer is not None

    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {m for m in _manalab_imports(tree) if m in LAYERS}
    illegal = imported - ALLOWED[layer] - {layer}

    assert not illegal, (
        f"{path.relative_to(SRC)} is in layer '{layer}' and may only import "
        f"{sorted(ALLOWED[layer]) or 'nothing'}, but imports {sorted(illegal)}. "
        "See ARCHITECTURE.md."
    )


def test_search_never_imports_a_game_model() -> None:
    """The single rule the whole design rests on, stated separately so a failure
    reads as the design violation it is rather than as a generic layering nit."""
    offenders = [
        (p.relative_to(SRC), sorted(hit))
        for p in _modules()
        if _layer_of(p) == "search"
        and (hit := _manalab_imports(ast.parse(p.read_text(encoding="utf-8"))) & set(MODELS))
    ]
    assert not offenders, (
        f"{offenders} import a game model directly. Search must reach the game only "
        "through the Evaluator protocol, or upgrading fidelity becomes a rewrite."
    )


def _all_modules() -> dict[str, set[str]]:
    """Every module in the package, mapped to the manalab modules it imports."""
    graph: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        name = ".".join(path.relative_to(SRC.parent).with_suffix("").parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        deps: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("manalab"):
                deps.add(node.module or "")
            elif isinstance(node, ast.Import):
                deps.update(a.name for a in node.names if a.name.startswith("manalab"))
        graph[name] = deps - {name}
    return graph


def test_no_module_imports_its_own_package_facade() -> None:
    """A submodule must import its siblings directly, never through `__init__`.

    `from manalab.engine import mana` inside `manalab.engine.actions` drags the
    package facade into the graph, and since the facade imports `game` — which
    imports `actions` — the package acquires a cycle. That is precisely how the
    engine grew a four-module tangle that no test caught and no reading of any
    single file would reveal. See ADR 0005.
    """
    offenders = [
        (module, sorted(bad))
        for module, deps in _all_modules().items()
        if "." in module
        and (bad := {d for d in deps if d == module.rsplit(".", 1)[0]})
    ]
    assert not offenders, (
        f"{offenders} import their own package facade. Import the sibling module "
        "directly, e.g. `from manalab.engine.mana import can_pay`."
    )


def test_there_are_no_import_cycles() -> None:
    """Mutual dependency is an architectural fact invisible from any one file."""
    graph = _all_modules()
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycles: list[list[str]] = []
    counter = iter(range(10_000))

    def visit(node: str) -> None:
        index[node] = low[node] = next(counter)
        stack.append(node)
        on_stack.add(node)
        for dep in graph.get(node, ()):
            if dep not in graph:
                continue
            if dep not in index:
                visit(dep)
                low[node] = min(low[node], low[dep])
            elif dep in on_stack:
                low[node] = min(low[node], index[dep])
        if low[node] == index[node]:
            component = []
            while True:
                popped = stack.pop()
                on_stack.discard(popped)
                component.append(popped)
                if popped == node:
                    break
            if len(component) > 1:
                cycles.append(sorted(component))

    for module in list(graph):
        if module not in index:
            visit(module)

    assert not cycles, f"import cycles: {cycles}"


@pytest.mark.parametrize("model", MODELS)
def test_the_two_game_models_stay_independent(model: str) -> None:
    """`game` approximates; `engine` does not. If they shared code the fast
    model's approximations would leak into the real one, and a wrong answer from
    the rules engine is far harder to notice than a wrong answer from a sim that
    advertises its blind spots."""
    others = set(MODELS) - {model}
    offenders = [
        p.relative_to(SRC)
        for p in _modules()
        if _layer_of(p) == model
        and _manalab_imports(ast.parse(p.read_text(encoding="utf-8"))) & others
    ]
    assert not offenders, f"{offenders} reach across from '{model}' into {others}"
