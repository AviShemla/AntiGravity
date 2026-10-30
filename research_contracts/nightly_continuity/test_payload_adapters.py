from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from assemble_payload_release_source import (
    AssemblyError,
    FILE_MAPS,
    assemble_source,
    resolve_reviewed_source,
)
from build_release import build_release
from payload_adapter_contract import (
    HANDOFF_ROOT,
    PayloadAdapterError,
    handoff_arguments,
    ingestion_arguments,
    invoke_noarg_main,
    postflight_arguments,
)
from release_layout import verify_release


HERE = Path(__file__).resolve().parent


def default_workspace_root() -> Path:
    package_parent = HERE.parent
    if (
        package_parent.name == "research_contracts"
        and (package_parent.parent / ".git").exists()
    ):
        return package_parent.parent
    return package_parent


WORKSPACE = Path(
    os.environ.get("CODEX_TEST_WORKSPACE_ROOT", str(default_workspace_root()))
).resolve()


@contextmanager
def writable_directory():
    path = HERE / "_test_work" / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


class IngestionAdapterTests(unittest.TestCase):
    def env(self, **updates):
        result = {
            "CODEX_MARKET_UNIVERSE_SNAPSHOT": "market_features_2026-08-26_deadbeefdeadbeef",
            "CODEX_MARKET_REQUIRED_TICKERS": "SPY",
            "CODEX_MARKET_WORKERS": "8",
        }
        result.update(updates)
        return result

    def test_exact_reviewed_cli_preserves_fallback_inputs_and_staging_boundary(self):
        result = ingestion_arguments(["--source-session", "2026-08-27"], self.env())
        self.assertEqual(result[:4], (
            "--source-session", "2026-08-27", "--universe-snapshot",
            "market_features_2026-08-26_deadbeefdeadbeef",
        ))
        self.assertIn("--tiingo-token-file", result)
        self.assertEqual(result[result.index("--tiingo-token-file") + 1], "/etc/antigravity/tiingo.token")
        self.assertNotIn("--dry-run", result)
        self.assertFalse(any("validat" in value.lower() or "promot" in value.lower() for value in result))

    def test_missing_pinned_universe_fails_closed(self):
        with self.assertRaises(PayloadAdapterError):
            ingestion_arguments(["--source-session", "2026-08-27"], self.env(CODEX_MARKET_UNIVERSE_SNAPSHOT=""))

    def test_unknown_or_lifecycle_flag_is_rejected(self):
        for flag in ("--dry-run", "--validate", "--promote"):
            with self.subTest(flag=flag), self.assertRaises(SystemExit):
                ingestion_arguments(["--source-session", "2026-08-27", flag], self.env())

    def test_required_tickers_are_explicit_and_deduplicated(self):
        result = ingestion_arguments(
            ["--source-session", "2026-08-27"],
            self.env(CODEX_MARKET_REQUIRED_TICKERS="SPY,^VIX"),
        )
        start = result.index("--required-tickers") + 1
        self.assertEqual(result[start:start + 2], ("SPY", "^VIX"))
        with self.assertRaises(PayloadAdapterError):
            ingestion_arguments(
                ["--source-session", "2026-08-27"],
                self.env(CODEX_MARKET_REQUIRED_TICKERS="SPY,SPY"),
            )

    def test_noarg_main_receives_exact_argv_and_process_argv_is_restored(self):
        prior = sys.argv
        observed = []

        def main():
            observed.extend(sys.argv[1:])
            return 7

        self.assertEqual(invoke_noarg_main(main, ("--source-session", "2026-08-27")), 7)
        self.assertEqual(observed, ["--source-session", "2026-08-27"])
        self.assertIs(sys.argv, prior)


class ReadOnlySuccessorAdapterTests(unittest.TestCase):
    SOURCE = "2026-08-27"
    ARTIFACT = HANDOFF_ROOT / SOURCE / "postflight-handoff.json"

    def test_postflight_allows_only_canonical_select_only_handoff_contract(self):
        result = postflight_arguments([
            "--source-session", self.SOURCE,
            "--expected-code-version", "a" * 64,
            "--handoff-output", str(self.ARTIFACT),
            "--attempts", "6", "--retry-seconds", "5",
        ])
        self.assertEqual(result[0:2], ("--source-session", self.SOURCE))
        self.assertNotIn("--env-file", result)
        self.assertFalse(any("validat" in value.lower() or "promot" in value.lower() for value in result))

    def test_postflight_rejects_noncanonical_output_and_unknown_flags(self):
        base = [
            "--source-session", self.SOURCE,
            "--expected-code-version", "a" * 64,
            "--attempts", "6", "--retry-seconds", "5",
        ]
        with self.assertRaises(PayloadAdapterError):
            postflight_arguments([*base, "--handoff-output", "/tmp/handoff.json"])
        with self.assertRaises(SystemExit):
            postflight_arguments([*base, "--handoff-output", str(self.ARTIFACT), "--token-env", "OTHER"])

    def test_handoff_is_terminal_canonical_and_freshness_bounded(self):
        result = handoff_arguments([
            "--source-session", self.SOURCE,
            "--artifact", str(self.ARTIFACT),
            "--max-age-seconds", "300",
        ])
        self.assertEqual(result[-2:], ("--max-age-seconds", "300"))
        with self.assertRaises(PayloadAdapterError):
            handoff_arguments([
                "--source-session", self.SOURCE,
                "--artifact", str(self.ARTIFACT),
                "--max-age-seconds", "901",
            ])


class ReviewedSourceAssemblyTests(unittest.TestCase):
    def test_reviewed_sources_are_copied_byte_exact_and_manifest_bound(self):
        with writable_directory() as root:
            releases = root / "releases"
            for kind, mapping in FILE_MAPS.items():
                with self.subTest(kind=kind):
                    source = root / f"{kind}-source"
                    created = assemble_source(WORKSPACE, source, kind)
                    self.assertEqual(len(created), len(mapping))
                    for original_relative, release_relative in mapping.items():
                        original = resolve_reviewed_source(
                            WORKSPACE, original_relative
                        )
                        copied = source / release_relative
                        self.assertEqual(
                            hashlib.sha256(copied.read_bytes()).hexdigest(),
                            hashlib.sha256(original.read_bytes()).hexdigest(),
                        )
                    release_id, _ = build_release(
                        source, releases, kind, require_root=False,
                    )
                    verify_release(releases, kind, release_id, require_root=False)

    def test_existing_assembly_target_is_never_overwritten(self):
        with writable_directory() as root:
            output = root / "source"
            output.mkdir()
            marker = output / "preserved"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                assemble_source(WORKSPACE, output, "market-ingestion")
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_source_resolution_supports_canonical_layout_without_guessing(self):
        with writable_directory() as root:
            canonical = root / "research_contracts" / "nightly_continuity"
            canonical.mkdir(parents=True)
            expected = canonical / "stage_runner.py"
            expected.write_text("canonical", encoding="utf-8")
            self.assertEqual(
                resolve_reviewed_source(
                    root, "nightly_continuity_impl/stage_runner.py"
                ),
                expected,
            )

    def test_exact_review_layout_precedes_canonical_alias(self):
        with writable_directory() as root:
            exact = root / "nightly_continuity_impl" / "stage_runner.py"
            alias = (
                root
                / "research_contracts"
                / "nightly_continuity"
                / "stage_runner.py"
            )
            exact.parent.mkdir(parents=True)
            alias.parent.mkdir(parents=True)
            exact.write_text("reviewed", encoding="utf-8")
            alias.write_text("canonical", encoding="utf-8")
            self.assertEqual(
                resolve_reviewed_source(
                    root, "nightly_continuity_impl/stage_runner.py"
                ),
                exact,
            )

    def test_legacy_review_prefix_maps_to_canonical_repository_root(self):
        with writable_directory() as root:
            expected = root / "market_data_provider.py"
            expected.write_text("canonical", encoding="utf-8")
            self.assertEqual(
                resolve_reviewed_source(
                    root, "antigravity/market_data_provider.py"
                ),
                expected,
            )

    def test_source_resolution_rejects_unsafe_or_missing_paths(self):
        with writable_directory() as root:
            for source in (
                "../outside.py",
                "/absolute.py",
                "nightly_continuity_impl/missing.py",
            ):
                with self.subTest(source=source), self.assertRaises(AssemblyError):
                    resolve_reviewed_source(root, source)

    @unittest.skipIf(os.name == "nt", "release adapter execution contract is Linux-only")
    def test_all_three_actual_adapters_execute_only_reviewed_fixture_mains(self):
        with writable_directory() as root:
            shutil.copyfile(HERE / "payload_adapter_contract.py", root / "payload_adapter_contract.py")
            payload = root / "payload"
            payload.mkdir()
            implementation = root / "implementation"
            scripts = implementation / "scripts"
            scripts.mkdir(parents=True)
            fixture_noarg = (
                "import json,os,sys\n"
                "def main():\n"
                " open(os.environ['CAPTURE_PATH'],'w').write(json.dumps(sys.argv[1:]))\n"
                " return 0\n"
            )
            fixture_argv = (
                "import json,os\n"
                "def main(argv=None):\n"
                " open(os.environ['CAPTURE_PATH'],'w').write(json.dumps(list(argv or [])))\n"
                " return 0\n"
            )
            (scripts / "rebuild_market_features_to_turso.py").write_text(fixture_noarg, encoding="utf-8")
            (implementation / "market_ingestion_postflight_cli.py").write_text(fixture_argv, encoding="utf-8")
            (implementation / "verify_postflight_handoff.py").write_text(fixture_argv, encoding="utf-8")
            for name in (
                "run-market-ingestion-impl",
                "run-market-ingestion-postflight-impl",
                "run-market-ingestion-handoff-impl",
            ):
                target = payload / name
                shutil.copyfile(HERE / "payload_adapter_sources" / name, target)
                target.chmod(0o700)
            artifact = HANDOFF_ROOT / "2026-08-27" / "postflight-handoff.json"
            cases = (
                (
                    "run-market-ingestion-impl",
                    ["--source-session", "2026-08-27"],
                    {
                        "CODEX_MARKET_UNIVERSE_SNAPSHOT": "market_features_2026-08-26_deadbeefdeadbeef",
                        "CODEX_MARKET_REQUIRED_TICKERS": "SPY",
                        "CODEX_MARKET_WORKERS": "8",
                    },
                    "--tiingo-token-file",
                ),
                (
                    "run-market-ingestion-postflight-impl",
                    [
                        "--source-session", "2026-08-27",
                        "--expected-code-version", "a" * 64,
                        "--handoff-output", str(artifact),
                        "--attempts", "6", "--retry-seconds", "5",
                    ],
                    {},
                    "--expected-code-version",
                ),
                (
                    "run-market-ingestion-handoff-impl",
                    [
                        "--source-session", "2026-08-27",
                        "--artifact", str(artifact),
                        "--max-age-seconds", "300",
                    ],
                    {},
                    "--max-age-seconds",
                ),
            )
            for index, (name, argv, additions, expected_token) in enumerate(cases):
                capture = root / f"capture-{index}.json"
                environment = dict(
                    os.environ,
                    PYTHONDONTWRITEBYTECODE="1",
                    CAPTURE_PATH=str(capture),
                    **additions,
                )
                result = subprocess.run(
                    [str(payload / name), *argv], capture_output=True, text=True,
                    timeout=10, env=environment, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                observed = json.loads(capture.read_text(encoding="utf-8"))
                self.assertIn(expected_token, observed)
                self.assertFalse(any("validat" in item.lower() or "promot" in item.lower() for item in observed))


if __name__ == "__main__":
    unittest.main()
