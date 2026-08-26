#!/usr/bin/env python3
"""Single-purpose entrypoint for one explicitly pinned unbound-branch cleanup."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_lineage import LineageError
from oracle_research_unbound_branch_recovery import (
    recover_with_ephemeral_turso_home,
)
from scripts.oracle_research_dataset_isolated_matrix_execute import SubprocessCliRunner
from scripts.run_oracle_research_dataset_isolated_matrix_lifecycle import (
    _production_credentials,
)
from turso_read_pipeline import TursoReadPipeline


CONFIRMATION = "DESTROY_EXACT_DISPOSABLE_BRANCH_AFTER_BOUND_EVIDENCE"


def _existing_absolute_file(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise LineageError(f"{label} path must be absolute.")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise LineageError(f"{label} file is unavailable.") from exc
    if resolved != path or path.is_symlink() or not path.is_file():
        raise LineageError(f"{label} path identity is not exact.")
    return path


def _new_absolute_file(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise LineageError(f"{label} path must be absolute.")
    if path.exists() or path.is_symlink():
        raise LineageError(f"{label} evidence target already exists.")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise LineageError(f"{label} evidence parent is unavailable.") from exc
    if parent != path.parent or not parent.is_dir():
        raise LineageError(f"{label} evidence parent identity is not exact.")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent-json", type=Path, required=True)
    parser.add_argument("--intent-file-sha256", required=True)
    parser.add_argument("--terminal-json", type=Path, required=True)
    parser.add_argument("--terminal-file-sha256", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--branch-name", required=True)
    parser.add_argument("--branch-id", required=True)
    parser.add_argument("--production-fingerprint-sha256", required=True)
    parser.add_argument("--production-object-count", type=int, required=True)
    parser.add_argument("--production-env-file", type=Path, required=True)
    parser.add_argument("--turso-settings-file", type=Path, required=True)
    parser.add_argument("--turso-settings-owner-uid", type=int, required=True)
    parser.add_argument("--pre-cleanup-evidence-json", type=Path, required=True)
    parser.add_argument("--final-evidence-json", type=Path, required=True)
    parser.add_argument("--confirm-exact-cleanup", required=True)
    return parser


def run_recovery_cli(
    argv: list[str] | None = None,
    *,
    now=None,
    credentials_loader=_production_credentials,
    production_reader_factory=None,
    cli_runner_factory=SubprocessCliRunner,
    recovery_wrapper=recover_with_ephemeral_turso_home,
):
    """Parse and preflight every binding before entering the recovery wrapper."""

    args = _parser().parse_args(argv)
    if args.confirm_exact_cleanup != CONFIRMATION:
        raise LineageError("Exact cleanup confirmation phrase differs.")
    if args.turso_settings_owner_uid < 0:
        raise LineageError("Turso settings owner UID is invalid.")
    intent_path = _existing_absolute_file(args.intent_json, "Intent")
    terminal_path = _existing_absolute_file(args.terminal_json, "Terminal")
    production_env_path = _existing_absolute_file(
        args.production_env_file, "Production environment"
    )
    settings_path = _existing_absolute_file(args.turso_settings_file, "Turso settings")
    pre_path = _new_absolute_file(args.pre_cleanup_evidence_json, "Pre-cleanup")
    final_path = _new_absolute_file(args.final_evidence_json, "Final")
    if pre_path == final_path:
        raise LineageError("Pre-cleanup and final evidence targets must differ.")

    _, production_token, production_endpoint = credentials_loader(production_env_path)
    reader_factory = production_reader_factory or (
        lambda endpoint, token: TursoReadPipeline(endpoint, token, timeout_seconds=45.0)
    )
    production_reader = reader_factory(production_endpoint, production_token)
    observed_at = (now or datetime.now)(timezone.utc)
    return recovery_wrapper(
        turso_settings_path=settings_path,
        turso_settings_owner_uid=args.turso_settings_owner_uid,
        runner_factory=cli_runner_factory,
        production_reader=production_reader,
        intent_path=intent_path,
        expected_intent_file_sha256=args.intent_file_sha256,
        terminal_path=terminal_path,
        expected_terminal_file_sha256=args.terminal_file_sha256,
        expected_approval_id=args.approval_id,
        expected_branch_name=args.branch_name,
        expected_branch_id=args.branch_id,
        expected_production_fingerprint=args.production_fingerprint_sha256,
        expected_production_object_count=args.production_object_count,
        pre_cleanup_evidence_path=pre_path,
        final_evidence_path=final_path,
        observed_at=observed_at,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        run_recovery_cli(argv)
    except Exception:
        print(
            "Oracle exact-branch cleanup failed; inspect only redacted evidence.",
            file=sys.stderr,
        )
        return 1
    print("Oracle exact-branch cleanup evidence was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
