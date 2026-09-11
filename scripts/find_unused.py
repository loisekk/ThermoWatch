"""One-shot pyright-style unused-import / unused-module-variable detector (AST)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

FILES = [
    "app/ml/classifier.py",
    "app/ml/feature_engineering.py",
    "app/ml/features.py",
    "app/ml/model_loader.py",
    "app/ml/train_multimodal.py",
    "app/ml/dataset_multimodal.py",
    "app/services/weather.py",
    "app/services/population.py",
    "app/services/landcover.py",
    "app/services/pipeline.py",
    "app/api/v1/ml_inference.py",
    "app/schemas/fire.py",
    "app/main.py",
    "app/api/v1/router.py",
    "tests/test_multimodal_features.py",
]


def used_names(tree: ast.AST) -> set[str]:
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            pass
    return used


def walk_file(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    used = used_names(tree)
    problems: list[str] = []
    for node in tree.body:  # top-level imports only (our files are flat)
        names: list[tuple[str, ast.stmt]] = []
        if isinstance(node, ast.Import):
            names = [(a.asname or a.name.split(".")[0], node) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(a.asname or a.name, node) for a in node.names]
        for name, stmt in names:
            if name not in used:
                problems.append(f"{path.name}:{stmt.lineno}: unused import '{name}'")
    # unused top-level assignments (simple Name targets, UPPER/._private included)
    assigned: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned[t.id] = node.lineno
    for name, lineno in assigned.items():
        if name not in used:
            problems.append(f"{path.name}:{lineno}: unused module variable '{name}'")
    for p in problems:
        print(p)
    if not problems:
        print(f"{path.name}: OK")


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "server" / "api"
    for rel in FILES:
        p = root / rel
        if p.exists():
            walk_file(p)
        else:
            print(f"{rel}: MISSING")
    sys.exit(0)


if __name__ == "__main__":
    main()