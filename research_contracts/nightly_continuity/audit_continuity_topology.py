"""Static fail-closed audit for rendered nightly continuity systemd units."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Sequence


class TopologyError(RuntimeError):
    pass


def _read(path: Path) -> str:
    if not path.is_file():
        raise TopologyError(f"missing unit: {path.name}")
    return path.read_text(encoding="utf-8")


def audit(directory: Path) -> dict[str, object]:
    names = {
        "timer": "codex-market-nightly-continuity.timer",
        "controller": "codex-market-nightly-continuity.service",
        "watchdog_timer": "codex-market-nightly-continuity-watchdog.timer",
        "watchdog": "codex-market-nightly-continuity-watchdog.service",
        "ingestion": "codex-market-ingestion@.service",
        "postflight": "codex-market-ingestion-postflight@.service",
        "handoff": "codex-market-ingestion-handoff@.service",
    }
    units = {key: _read(directory / value) for key, value in names.items()}
    timer = units["timer"]
    if "OnCalendar=*-*-* 03:30:00 Asia/Jerusalem" not in timer:
        raise TopologyError("nightly timer is not pinned to 03:30 Asia/Jerusalem")
    if "Persistent=true" not in timer or "RandomizedDelaySec=0" not in timer:
        raise TopologyError("timer persistence/determinism contract is missing")
    expected_edges = {
        "ingestion": "OnSuccess=codex-market-ingestion-postflight@%i.service",
        "postflight": "OnSuccess=codex-market-ingestion-handoff@%i.service",
    }
    for key, edge in expected_edges.items():
        if not re.search(rf"^{re.escape(edge)}$", units[key], re.MULTILINE):
            raise TopologyError(f"missing exact {key} successor")
    if re.search(r"^OnSuccess=", units["handoff"], re.MULTILINE):
        raise TopologyError("handoff must be terminal; downstream research is forbidden")
    all_text = "\n".join(units.values())
    forbidden = ("baseline", "model", "recommend", "order", "validate", "promote", "sniper")
    lowered = all_text.lower()
    for word in forbidden:
        if word in lowered and word != "sniper":
            raise TopologyError(f"forbidden downstream token in units: {word}")
    if "ExecStartPre=/usr/bin/test ! -e /run/systemd/system/ag-sniper.service" in all_text:
        raise TopologyError("safety cannot be inferred from unit-file absence")
    if "/current/" in all_text or "@RELEASE_SHA256@" in all_text:
        raise TopologyError("unit set is not bound to an immutable rendered release")
    if (
        "OnUnitActiveSec=5min" not in units["watchdog_timer"]
        or "/run-nightly-continuity-watchdog --config " not in units["watchdog"]
    ):
        raise TopologyError("five-minute durable liveness monitoring is missing")
    for directive in (
        "EnvironmentFile=/etc/codex-oracle/market-ingestion-readonly.env",
        "ReadOnlyPaths=/etc/codex-oracle/market-ingestion-readonly.env",
    ):
        if directive not in units["controller"]:
            raise TopologyError("controller lacks the root-only SELECT credential boundary")
    if not all(token in units["ingestion"] for token in (
        "CPUWeight=900", "IOWeight=900", "Nice=-5",
        "IOSchedulingClass=best-effort", "IOSchedulingPriority=0",
    )):
        raise TopologyError("guarded ingestion priority controls are missing")
    marker = "/var/lib/codex-oracle/market-ingestion/%i/progress.json"
    for key in ("ingestion", "postflight", "handoff"):
        if f"--progress-marker {marker}" not in units[key]:
            raise TopologyError(f"{key} lacks the exact durable progress-marker binding")
        if "ReadWritePaths=/var/lib/codex-oracle/market-ingestion/%i" not in units[key]:
            raise TopologyError(f"{key} cannot atomically persist its progress marker")
    expected_entrypoints = {
        "controller": "/run-nightly-continuity --config ",
        "watchdog": "/run-nightly-continuity-watchdog --config ",
        "ingestion": "/run-market-ingestion --source-session %i ",
        "postflight": "/run-market-ingestion-postflight --source-session %i ",
        "handoff": "/run-market-ingestion-handoff --source-session %i ",
    }
    for key, token in expected_entrypoints.items():
        if token not in units[key]:
            raise TopologyError(f"{key} is not bound to its concrete immutable entrypoint")
    for key in ("controller", "watchdog", "ingestion", "postflight", "handoff"):
        body = units[key]
        for directive in (
            "User=root", "UMask=0077", "Environment=PYTHONDONTWRITEBYTECODE=1",
            "NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true",
        ):
            if directive not in body:
                raise TopologyError(f"{key} lacks {directive}")
    for forbidden_unit in ("ag-sniper.service", "antigravity-nightly.timer", "antigravity-qa-watchdog.timer"):
        if f"ExecStartPre=/usr/bin/systemctl --quiet is-active {forbidden_unit}" in all_text:
            raise TopologyError("positive active-state safety check found")
    return {"status": "PASS", "units": len(units), "transitions": 2, "terminal": names["handoff"], "watchdog_minutes": 5}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(audit(args.directory), sort_keys=True))
        return 0
    except TopologyError as exc:
        print(f"TOPOLOGY_FAILED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
