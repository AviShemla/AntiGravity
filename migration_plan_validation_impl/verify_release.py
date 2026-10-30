"""Deterministic release checks for canonical migration-plan artifacts."""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    ROOT / "migration_plan_impl",
    ROOT / "migration_plan_validation_impl",
)
SECRET_PATTERN = re.compile(
    r"(?i)(?:token|password|secret|api[_-]?key)\s*[:=]\s*"
    r"[\"']?[A-Za-z0-9_-]{24,}"
)


def canonical_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        files.extend(
            path
            for path in root.iterdir()
            if path.is_file() and path.suffix in {".py", ".md", ".json"}
        )
    return tuple(sorted(files))


def main() -> int:
    files = canonical_files()
    python_files = tuple(path for path in files if path.suffix == ".py")
    for path in python_files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    secret_hits = tuple(
        path for path in files if SECRET_PATTERN.search(path.read_text(encoding="utf-8"))
    )
    if secret_hits:
        for path in secret_hits:
            print(f"secret_pattern_hit={path.relative_to(ROOT)}")
        return 1

    for relative in (
        Path("migration_plan_impl/CODEX_ORACLE_MIGRATION_PLAN.md"),
        Path("migration_plan_impl/CODEX_ORACLE_STAGE_REGISTRY.json"),
    ):
        payload = (ROOT / relative).read_bytes()
        print(f"sha256={hashlib.sha256(payload).hexdigest()} file={relative.as_posix()}")
    print(f"release_files={len(files)} ast_files={len(python_files)} secret_hits=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
