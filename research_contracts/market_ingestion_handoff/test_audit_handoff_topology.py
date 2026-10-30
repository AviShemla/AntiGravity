from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from .audit_handoff_topology import TopologyError, audit_topology, audit_topology_units
except ImportError:
    from audit_handoff_topology import (  # type: ignore
        TopologyError,
        audit_topology,
        audit_topology_units,
    )


ROOT = Path(__file__).resolve().parent


class HandoffTopologyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(
            (ROOT / "systemd" / "handoff-topology.json").read_text(encoding="utf-8")
        )
        self.units = {
            path.name: path.read_text(encoding="utf-8")
            for path in (ROOT / "systemd").glob("*.service")
        }

    def test_canonical_topology_has_exactly_one_owner_per_transition(self):
        result = audit_topology(ROOT / "systemd", self.manifest)
        self.assertEqual("PASS", result["status"])
        self.assertEqual(
            "codex-market-ingestion-handoff@.service",
            result["baseline_on_success_owner"],
        )

    def test_multiple_baseline_trigger_candidates_fail_closed(self):
        units = dict(self.units)
        units["duplicate-trigger.service"] = (
            "[Unit]\nOnSuccess=codex-stock-baseline@%i.service\n"
        )
        with self.assertRaisesRegex(TopologyError, "exactly owner"):
            audit_topology_units(units, self.manifest)

    def test_missing_owner_fails_closed(self):
        units = {
            name: text
            for name, text in self.units.items()
            if name != "codex-market-ingestion-handoff@.service"
        }
        with self.assertRaises(TopologyError):
            audit_topology_units(units, self.manifest)


if __name__ == "__main__":
    unittest.main()
