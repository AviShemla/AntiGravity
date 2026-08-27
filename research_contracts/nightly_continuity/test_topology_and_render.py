from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from audit_continuity_topology import TopologyError, audit
from release_layout import MANIFEST_CONTRACT, ReleaseLayoutError, canonical_bytes, verify_release
from render_units import render


HERE = Path(__file__).resolve().parent
@contextmanager
def writable_directory():
    path = HERE / "_test_work" / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield str(path)
    finally:
        shutil.rmtree(path)


def create_release(root: Path, kind: str, files: dict[str, tuple[bytes, int]]) -> str:
    staging = root / f"{kind}-staging"
    staging.mkdir(parents=True)
    rows = []
    for relative, (content, mode) in sorted(files.items()):
        path = staging / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)
        rows.append({
            "path": relative,
            "sha256": hashlib.sha256(content).hexdigest(),
            "mode": f"{mode:04o}",
        })
    manifest = {
        "contract_id": MANIFEST_CONTRACT,
        "release_kind": kind,
        "files": rows,
    }
    encoded = canonical_bytes(manifest)
    release_id = hashlib.sha256(encoded).hexdigest()
    manifest_path = staging / "release-manifest.json"
    manifest_path.write_bytes(encoded)
    manifest_path.chmod(0o600)
    target = root / f"{kind}-{release_id}"
    staging.rename(target)
    return release_id


def create_release_set(root: Path) -> tuple[str, str, str]:
    root.mkdir()
    controller = create_release(root, "nightly-continuity", {
        "run-nightly-continuity": (b"#!/bin/sh\nexit 0\n", 0o700),
        "run-nightly-continuity-watchdog": (b"#!/bin/sh\nexit 0\n", 0o700),
        "continuity_controller.py": (b"# controller\n", 0o600),
        "release_layout.py": (b"# verifier\n", 0o600),
    })
    ingestion = create_release(root, "market-ingestion", {
        "run-market-ingestion": (b"#!/bin/sh\nexit 0\n", 0o700),
        "stage_runner.py": (b"# supervisor\n", 0o600),
        "release_layout.py": (b"# verifier\n", 0o600),
        "payload_adapter_contract.py": (b"# adapter contract\n", 0o600),
        "payload/run-market-ingestion-impl": (b"#!/bin/sh\nexit 0\n", 0o700),
        "implementation/scripts/rebuild_market_features_to_turso.py": (b"# rebuild\n", 0o600),
        "implementation/scripts/stage_market_features_to_turso.py": (b"# stage\n", 0o600),
        "implementation/market_data_provider.py": (b"# provider\n", 0o600),
        "implementation/market_data_guard.py": (b"# guard\n", 0o600),
        "implementation/turso_read_pipeline.py": (b"# read\n", 0o600),
        "implementation/model_lineage.py": (b"# lineage\n", 0o600),
    })
    handoff = create_release(root, "market-ingestion-handoff", {
        "run-market-ingestion-postflight": (b"#!/bin/sh\nexit 0\n", 0o700),
        "run-market-ingestion-handoff": (b"#!/bin/sh\nexit 0\n", 0o700),
        "stage_runner.py": (b"# supervisor\n", 0o600),
        "release_layout.py": (b"# verifier\n", 0o600),
        "payload_adapter_contract.py": (b"# adapter contract\n", 0o600),
        "payload/run-market-ingestion-postflight-impl": (b"#!/bin/sh\nexit 0\n", 0o700),
        "payload/run-market-ingestion-handoff-impl": (b"#!/bin/sh\nexit 0\n", 0o700),
        "implementation/market_ingestion_postflight_cli.py": (b"# postflight\n", 0o600),
        "implementation/market_ingestion_postflight.py": (b"# reconcile\n", 0o600),
        "implementation/verify_postflight_handoff.py": (b"# verify\n", 0o600),
        "implementation/turso_read_pipeline.py": (b"# read\n", 0o600),
        "implementation/model_lineage.py": (b"# lineage\n", 0o600),
    })
    return controller, ingestion, handoff


class RenderTests(unittest.TestCase):
    def render(self, root: Path) -> Path:
        release_root = root / "releases"
        controller, ingestion, handoff = create_release_set(release_root)
        output = root / "rendered"
        render(
            HERE / "systemd", output, controller_sha=controller,
            ingestion_sha=ingestion, handoff_sha=handoff,
            release_root=release_root, require_root=False,
        )
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
                render(
                    HERE / "systemd", Path(tmp) / "out", controller_sha="bad",
                    ingestion_sha="b" * 64, handoff_sha="c" * 64,
                    release_root=Path(tmp) / "missing", require_root=False,
                )

    def test_existing_output_rejected(self):
        with writable_directory() as tmp:
            output = Path(tmp) / "out"
            output.mkdir()
            release_root = Path(tmp) / "releases"
            controller, ingestion, handoff = create_release_set(release_root)
            with self.assertRaises(FileExistsError):
                render(
                    HERE / "systemd", output, controller_sha=controller,
                    ingestion_sha=ingestion, handoff_sha=handoff,
                    release_root=release_root, require_root=False,
                )

    def test_unmanifested_release_file_rejected(self):
        with writable_directory() as tmp:
            release_root = Path(tmp) / "releases"
            controller, _, _ = create_release_set(release_root)
            release = release_root / f"nightly-continuity-{controller}"
            (release / "unexpected").write_text("x", encoding="utf-8")
            with self.assertRaises(ReleaseLayoutError):
                verify_release(release_root, "nightly-continuity", controller, require_root=False)

    def test_release_hash_mutation_rejected(self):
        with writable_directory() as tmp:
            release_root = Path(tmp) / "releases"
            controller, _, _ = create_release_set(release_root)
            release = release_root / f"nightly-continuity-{controller}"
            (release / "continuity_controller.py").write_text("mutated", encoding="utf-8")
            with self.assertRaises(ReleaseLayoutError):
                verify_release(release_root, "nightly-continuity", controller, require_root=False)

    def test_release_missing_required_entrypoint_rejected(self):
        with writable_directory() as tmp:
            release_root = Path(tmp) / "releases"
            release_root.mkdir()
            release_id = create_release(release_root, "market-ingestion", {
                "implementation.py": (b"# no runtime\n", 0o600),
            })
            with self.assertRaises(ReleaseLayoutError):
                verify_release(release_root, "market-ingestion", release_id, require_root=False)

    def test_release_entrypoint_mode_downgrade_rejected(self):
        with writable_directory() as tmp:
            release_root = Path(tmp) / "releases"
            _, ingestion, _ = create_release_set(release_root)
            release = release_root / f"market-ingestion-{ingestion}"
            (release / "run-market-ingestion").chmod(0o600)
            with self.assertRaises(ReleaseLayoutError):
                verify_release(release_root, "market-ingestion", ingestion, require_root=False)


class MutationTests(unittest.TestCase):
    def copy_rendered(self, root: Path) -> Path:
        release_root = root / "releases"
        controller, ingestion, handoff = create_release_set(release_root)
        output = root / "rendered"
        render(
            HERE / "systemd", output, controller_sha=controller,
            ingestion_sha=ingestion, handoff_sha=handoff,
            release_root=release_root, require_root=False,
        )
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
            path.write_text(
                re.sub(r"market-ingestion-[0-9a-f]{64}", "market-ingestion/current", path.read_text()),
                encoding="utf-8",
            )
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

    def test_idle_io_priority_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            self.mutate(output, "codex-market-ingestion@.service", "IOSchedulingClass=best-effort", "IOSchedulingClass=idle")
            with self.assertRaises(TopologyError): audit(output)

    def test_missing_ingestion_environment_binding_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            self.mutate(
                output, "codex-market-ingestion@.service",
                "EnvironmentFile=/etc/codex-oracle/market-ingestion.env", "# removed",
            )
            with self.assertRaises(TopologyError): audit(output)

    def test_missing_tiingo_token_boundary_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            self.mutate(
                output, "codex-market-ingestion@.service",
                "ReadOnlyPaths=/etc/antigravity/tiingo.token", "# removed",
            )
            with self.assertRaises(TopologyError): audit(output)

    def test_missing_progress_marker_binding_rejected(self):
        with writable_directory() as tmp:
            output = self.copy_rendered(Path(tmp))
            self.mutate(
                output, "codex-market-ingestion-postflight@.service",
                "--progress-marker /var/lib/codex-oracle/market-ingestion/%i/progress.json", "",
            )
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
