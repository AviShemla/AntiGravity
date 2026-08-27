from __future__ import annotations

import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from audit_continuity_topology import TopologyError, audit
from render_units import render


HERE = Path(__file__).resolve().parent
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


@contextmanager
def writable_directory():
    path = HERE / "_test_work" / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield str(path)
    finally:
        shutil.rmtree(path)


class RenderTests(unittest.TestCase):
    def render(self, root: Path) -> Path:
        output = root / "rendered"
        render(HERE / "systemd", output, controller_sha=SHA_A, ingestion_sha=SHA_B, handoff_sha=SHA_C)
        return output

    def test_rendered_topology_passes(self):
        with writable_directory() as tmp:
            result = audit(self.render(Path(tmp)))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["transitions"], 2)

    def test_seven_units_rendered(self):
        with writable_directory() as tmp:
            output = self.render(Path(tmp))
            self.assertEqual(len(list(output.iterdir())), 7)

    def test_no_mutable_current_alias(self):
        with writable_directory() as tmp:
            output = self.render(Path(tmp))
            self.assertNotIn("/current/", "".join(path.read_text() for path in output.iterdir()))

    def test_invalid_hash_rejected(self):
        with writable_directory() as tmp:
            with self.assertRaises(ValueError):
                render(HERE / "systemd", Path(tmp) / "out", controller_sha="bad", ingestion_sha=SHA_B, handoff_sha=SHA_C)

    def test_existing_output_rejected(self):
        with writable_directory() as tmp:
            output = Path(tmp) / "out"
            output.mkdir()
            with self.assertRaises(FileExistsError):
                render(HERE / "systemd", output, controller_sha=SHA_A, ingestion_sha=SHA_B, handoff_sha=SHA_C)


class MutationTests(unittest.TestCase):
    def copy_rendered(self, root: Path) -> Path:
        output = root / "rendered"
        render(HERE / "systemd", output, controller_sha=SHA_A, ingestion_sha=SHA_B, handoff_sha=SHA_C)
        return output

    def mutate(self, output: Path, name: str, old: str, new: str):
        path = output / name
        path.write_text(path.read_text().replace(old, new), encoding="utf-8")

    def test_wrong_schedule_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            self.mutate(output, "codex-market-nightly-continuity.timer", "03:30:00", "04:30:00")
            with self.assertRaises(TopologyError): audit(output)

    def test_missing_ingestion_successor_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            self.mutate(output, "codex-market-ingestion@.service", "OnSuccess=", "#OnSuccess=")
            with self.assertRaises(TopologyError): audit(output)

    def test_missing_postflight_successor_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            self.mutate(output, "codex-market-ingestion-postflight@.service", "OnSuccess=", "#OnSuccess=")
            with self.assertRaises(TopologyError): audit(output)

    def test_handoff_downstream_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            path = output / "codex-market-ingestion-handoff@.service"
            path.write_text(path.read_text().replace("[Service]", "OnSuccess=codex-stock-baseline@%i.service\n\n[Service]"), encoding="utf-8")
            with self.assertRaises(TopologyError): audit(output)

    def test_mutable_release_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            path = output / "codex-market-ingestion@.service"
            path.write_text(path.read_text().replace(f"market-ingestion-{SHA_B}", "market-ingestion/current"), encoding="utf-8")
            with self.assertRaises(TopologyError): audit(output)

    def test_missing_hardening_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            self.mutate(output, "codex-market-ingestion@.service", "NoNewPrivileges=true", "NoNewPrivileges=false")
            with self.assertRaises(TopologyError): audit(output)

    def test_missing_priority_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            self.mutate(output, "codex-market-ingestion@.service", "CPUWeight=900", "CPUWeight=100")
            with self.assertRaises(TopologyError): audit(output)

    def test_missing_watchdog_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            (output / "codex-market-nightly-continuity-watchdog.timer").unlink()
            with self.assertRaises(TopologyError): audit(output)

    def test_missing_controller_env_boundary_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            self.mutate(
                output, "codex-market-nightly-continuity.service",
                "EnvironmentFile=/etc/codex-oracle/market-ingestion-readonly.env",
                "# removed",
            )
            with self.assertRaises(TopologyError): audit(output)

    def test_forbidden_baseline_token_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            path = output / "codex-market-ingestion-handoff@.service"
            path.write_text(path.read_text() + "\n# baseline\n", encoding="utf-8")
            with self.assertRaises(TopologyError): audit(output)


if __name__ == "__main__":
    unittest.main()
