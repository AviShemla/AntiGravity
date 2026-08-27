"""Render immutable systemd units from reviewed templates."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Sequence

from audit_continuity_topology import audit


SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def render(template_dir: Path, output_dir: Path, *, controller_sha: str, ingestion_sha: str, handoff_sha: str) -> None:
    for value in (controller_sha, ingestion_sha, handoff_sha):
        if not SHA_RE.fullmatch(value):
            raise ValueError("release identity must be a lowercase SHA-256")
    output_dir.mkdir(parents=True, exist_ok=False)
    replacements = {
        "@CONTROLLER_RELEASE_SHA256@": controller_sha,
        "@INGESTION_RELEASE_SHA256@": ingestion_sha,
        "@HANDOFF_RELEASE_SHA256@": handoff_sha,
    }
    for source in sorted(template_dir.glob("*.in")):
        body = source.read_text(encoding="utf-8")
        for old, new in replacements.items():
            body = body.replace(old, new)
        if re.search(r"@[A-Z][A-Z0-9_]+@", body):
            raise ValueError(f"unrendered placeholder remains in {source.name}")
        target = output_dir / source.name.removesuffix(".in")
        target.write_text(body, encoding="utf-8", newline="\n")
        os.chmod(target, 0o600)
    audit(output_dir)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--controller-sha", required=True)
    parser.add_argument("--ingestion-sha", required=True)
    parser.add_argument("--handoff-sha", required=True)
    args = parser.parse_args(argv)
    render(args.templates, args.output, controller_sha=args.controller_sha, ingestion_sha=args.ingestion_sha, handoff_sha=args.handoff_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
