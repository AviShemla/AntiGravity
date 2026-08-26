"""Content binding for primary evidence artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_bound_json(ref: Any, root: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if root is None:
        return None, "an evidence root is required"
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        return None, "evidence ref must contain only path and sha256"
    relative = ref.get("path")
    digest = ref.get("sha256")
    if not isinstance(relative, str) or not relative or not isinstance(digest, str) or len(digest) != 64:
        return None, "evidence ref path/sha256 is invalid"
    base = root.resolve()
    target = (base / relative).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None, "evidence ref escapes the evidence root"
    try:
        payload = target.read_bytes()
    except OSError as exc:
        return None, f"evidence ref cannot be read: {exc}"
    actual = hashlib.sha256(payload).hexdigest()
    if actual != digest:
        return None, "evidence ref digest mismatch"
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        return None, f"evidence ref is not JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "evidence artifact must be a JSON object"
    return parsed, None
