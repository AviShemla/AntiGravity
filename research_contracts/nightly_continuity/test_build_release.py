from __future__ import annotations

import os
import shutil
import subprocess
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from build_release import build_release
from release_layout import REQUIRED_ARTIFACTS, ReleaseLayoutError, verify_release


HERE = Path(__file__).resolve().parent


@contextmanager
def writable_directory():
    path = HERE / "_test_work" / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        if os.name != "nt":
            path.chmod(0o700)
        yield path
    finally:
        shutil.rmtree(path)


def write_source(root: Path, kind: str) -> Path:
    source = root / "source"
    source.mkdir()
    names = {
        "nightly-continuity": (
            "run-nightly-continuity", "run-nightly-continuity-watchdog",
        ),
        "market-ingestion": ("run-market-ingestion",),
        "market-ingestion-handoff": (
            "run-market-ingestion-postflight", "run-market-ingestion-handoff",
        ),
    }[kind]
    for name in names:
        path = source / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    implementation = source / "implementation.py"
    implementation.write_text("# implementation\n", encoding="utf-8")
    if kind == "nightly-continuity":
        (source / "continuity_controller.py").write_text("# controller\n", encoding="utf-8")
    else:
        (source / "stage_runner.py").write_text("# supervisor\n", encoding="utf-8")
        payloads = (
            ("run-market-ingestion-impl",)
            if kind == "market-ingestion"
            else ("run-market-ingestion-postflight-impl", "run-market-ingestion-handoff-impl")
        )
        payload_dir = source / "payload"
        payload_dir.mkdir()
        for name in payloads:
            payload = payload_dir / name
            payload.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    (source / "release_layout.py").write_text("# verifier\n", encoding="utf-8")
    fill_required(source, kind)
    return source


def fill_required(source: Path, kind: str) -> None:
    for relative in REQUIRED_ARTIFACTS[kind]:
        path = source / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# required fixture\n", encoding="utf-8")


class BuildReleaseTests(unittest.TestCase):
    def test_atomic_build_is_verified_and_idempotent(self):
        with writable_directory() as root:
            source = write_source(root, "market-ingestion")
            releases = root / "releases"
            first_id, first_path = build_release(
                source, releases, "market-ingestion", require_root=False,
            )
            second_id, second_path = build_release(
                source, releases, "market-ingestion", require_root=False,
            )
            self.assertEqual((first_id, first_path), (second_id, second_path))
            self.assertEqual(len([p for p in releases.iterdir() if not p.name.startswith(".")]), 1)
            verify_release(releases, "market-ingestion", first_id, require_root=False)

    def test_source_mutation_changes_release_identity(self):
        with writable_directory() as root:
            source = write_source(root, "market-ingestion")
            releases = root / "releases"
            first_id, _ = build_release(source, releases, "market-ingestion", require_root=False)
            (source / "implementation.py").write_text("# changed\n", encoding="utf-8")
            second_id, _ = build_release(source, releases, "market-ingestion", require_root=False)
            self.assertNotEqual(first_id, second_id)

    def test_builder_assigns_executable_and_data_modes(self):
        with writable_directory() as root:
            source = write_source(root, "market-ingestion")
            releases = root / "releases"
            release_id, release = build_release(source, releases, "market-ingestion", require_root=False)
            verify_release(releases, "market-ingestion", release_id, require_root=False)
            if os.name != "nt":
                self.assertEqual((release / "run-market-ingestion").stat().st_mode & 0o777, 0o700)
                self.assertEqual((release / "implementation.py").stat().st_mode & 0o777, 0o600)
                self.assertEqual((release / "payload/run-market-ingestion-impl").stat().st_mode & 0o777, 0o700)

    def test_symlink_source_fails_closed(self):
        with writable_directory() as root:
            source = write_source(root, "market-ingestion")
            target = source / "implementation.py"
            link = source / "linked.py"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(ReleaseLayoutError):
                build_release(source, root / "releases", "market-ingestion", require_root=False)

    def test_missing_entrypoint_fails_before_release_creation(self):
        with writable_directory() as root:
            source = root / "source"
            source.mkdir()
            (source / "implementation.py").write_text("x", encoding="utf-8")
            with self.assertRaises(ReleaseLayoutError):
                build_release(source, root / "releases", "market-ingestion", require_root=False)

    @unittest.skipIf(os.name == "nt", "release entrypoint execution contract is Linux-only")
    def test_all_five_actual_entrypoints_self_verify_and_execute(self):
        with writable_directory() as root:
            releases = root / "releases"

            controller_source = root / "controller-source"
            controller_source.mkdir()
            for name in ("run-nightly-continuity", "run-nightly-continuity-watchdog"):
                shutil.copyfile(HERE / "runner_sources" / name, controller_source / name)
            for name in ("continuity_controller.py", "release_layout.py"):
                shutil.copyfile(HERE / name, controller_source / name)
            controller_id, controller_release = build_release(
                controller_source, releases, "nightly-continuity", require_root=False,
            )
            self.assertEqual(len(controller_id), 64)
            for name in ("run-nightly-continuity", "run-nightly-continuity-watchdog"):
                result = subprocess.run(
                    [str(controller_release / name), "--help"],
                    check=False, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            ingestion_source = root / "ingestion-source"
            ingestion_source.mkdir()
            shutil.copyfile(HERE / "runner_sources/run-market-ingestion", ingestion_source / "run-market-ingestion")
            for name in ("stage_runner.py", "release_layout.py"):
                shutil.copyfile(HERE / name, ingestion_source / name)
            ingestion_payload = ingestion_source / "payload/run-market-ingestion-impl"
            ingestion_payload.parent.mkdir()
            ingestion_payload.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
            fill_required(ingestion_source, "market-ingestion")
            ingestion_id, ingestion_release = build_release(
                ingestion_source, releases, "market-ingestion", require_root=False,
            )

            handoff_source = root / "handoff-source"
            handoff_source.mkdir()
            for name in ("run-market-ingestion-postflight", "run-market-ingestion-handoff"):
                shutil.copyfile(HERE / "runner_sources" / name, handoff_source / name)
            for name in ("stage_runner.py", "release_layout.py"):
                shutil.copyfile(HERE / name, handoff_source / name)
            payload_dir = handoff_source / "payload"
            payload_dir.mkdir()
            for name in ("run-market-ingestion-postflight-impl", "run-market-ingestion-handoff-impl"):
                (payload_dir / name).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
            fill_required(handoff_source, "market-ingestion-handoff")
            handoff_id, handoff_release = build_release(
                handoff_source, releases, "market-ingestion-handoff", require_root=False,
            )

            environment = dict(os.environ, INVOCATION_ID="fixture-invocation")
            runners = (
                (ingestion_release / "run-market-ingestion", ingestion_id, root / "ingestion-progress.json"),
                (handoff_release / "run-market-ingestion-postflight", handoff_id, root / "postflight-progress.json"),
                (handoff_release / "run-market-ingestion-handoff", handoff_id, root / "handoff-progress.json"),
            )
            for runner, code_version, marker in runners:
                result = subprocess.run(
                    [
                        str(runner), "--source-session", "2026-08-27",
                        "--progress-marker", str(marker), "--code-version", code_version,
                        "--heartbeat-seconds", "0.01", "--total-units", "1",
                    ],
                    check=False, capture_output=True, text=True, timeout=10,
                    env=environment,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(__import__("json").loads(marker.read_text())["status"], "SUCCEEDED")


if __name__ == "__main__":
    unittest.main()
