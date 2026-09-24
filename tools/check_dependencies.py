"""Architecture guard: enforce the dependency direction.

    frontend ──► backend ──► agent ──► rag

Nothing points the other way. In particular **backend must never import rag**:
if the backend needs to know a document was indexed, it learns that from the
agent's HTTP response, not by reaching into the engine.

Run it directly, or as a test (tools/test_dependencies.py), or in CI.

An architecture rule that lives only in a document gets violated within a month,
usually by someone in a hurry who is technically right that it would be easier.
This makes the violation fail the build instead.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Which top-level packages each layer is forbidden to import.
FORBIDDEN: dict[str, set[str]] = {
    # The backend is the reliability layer. It orchestrates AI work over HTTP
    # and knows nothing about how the work is done.
    "backend": {"rag", "agent"},
    # The agent may import rag (that is the point) but must never reach back
    # into the service that calls it.
    "agent": {"backend"},
    # The engine is a library. It depends on nothing above it, which is what
    # lets the eval harness import it with no chatbot in the loop.
    "rag": {"backend", "agent"},
}

SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", ".pytest_cache"}


def python_files(layer: str) -> list[Path]:
    base = ROOT / layer
    if not base.exists():
        return []
    return [
        p
        for p in base.rglob("*.py")
        if not any(part in SKIP_DIRS for part in p.parts)
    ]


def imported_roots(path: Path) -> set[tuple[str, int]]:
    """Top-level package name of every import, with its line number."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        print(f"  ! could not parse {path}: {exc}")
        return set()

    found: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # Relative imports stay inside their own package by definition.
            if node.level == 0 and node.module:
                found.add((node.module.split(".")[0], node.lineno))
    return found


def check() -> list[str]:
    violations: list[str] = []

    for layer, banned in FORBIDDEN.items():
        for path in python_files(layer):
            for root, lineno in imported_roots(path):
                if root in banned:
                    rel = path.relative_to(ROOT).as_posix()
                    violations.append(
                        f"{rel}:{lineno}  {layer} imports {root} "
                        f"— forbidden ({layer} must not depend on {root})"
                    )

    return sorted(violations)


def main() -> int:
    violations = check()

    if violations:
        print("DEPENDENCY DIRECTION VIOLATED\n")
        for v in violations:
            print(f"  {v}")
        print(
            "\n  Allowed direction:  frontend -> backend -> agent -> rag"
            "\n  Nothing points back up. If the backend needs something the"
            "\n  engine knows, it asks the agent over HTTP."
        )
        return 1

    layers = ", ".join(f"{k} ({len(python_files(k))} files)" for k in FORBIDDEN)
    print(f"dependency direction OK — checked {layers}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
