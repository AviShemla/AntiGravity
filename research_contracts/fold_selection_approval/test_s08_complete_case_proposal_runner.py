from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
import ast
import hashlib
import unittest
from unittest.mock import Mock, patch

from research_contracts.fold_selection_approval import s08_complete_case_proposal_runner as runner
from research_contracts.fold_selection_approval.s08_complete_case_proposal_runtime import (
    SelectOnlyProposalAssembly,
)


def assembly(*, fresh=True, execution=False):
    proposal = SimpleNamespace(
        status="APPROVAL_REQUIRED", selections=(),
        proposal_core_sha256="a" * 64,
        approval_record_sha256="b" * 64,
        artifact_sha256=MappingProxyType({"proposal_core": "c" * 64}),
    )
    return SelectOnlyProposalAssembly(
        contract_id="runtime", status="AUDIT_ONLY_PROPOSAL_ASSEMBLED_AUTHORITY_PENDING",
        canonical_git_head="d" * 40, runtime_git_commit="e" * 40,
        frozen_dataset_version="dataset", snapshot_id="snapshot",
        frozen_content_sha256="f" * 64, fresh_readback_evidence_sha256="1" * 64,
        s07_reconstruction_sha256="2" * 64, s07_source_sha256="3" * 64,
        s07_independent_verification_sha256="4" * 64,
        preregistration_manifest_sha256="5" * 64,
        panel_sha256="6" * 64, panel_shape=(472, 416),
        upstream_universe_sha256="7" * 64,
        required_dates_sha256="8" * 64,
        presence_mask_sha256="9" * 64,
        eligible_universe_sha256="a" * 64,
        exclusion_evidence_sha256="b" * 64,
        excluded_tickers=(("FISV", 416), ("SNDK", 358)),
        proposal=proposal, proposal_core_sha256="a" * 64,
        query_count=54, database_writes=0, selection_runs=0, model_runs=0,
        predictions=0, recommendations=0, orders=0, downstream_outputs=0,
        execution_authorized=execution, s07_readback_fresh=fresh,
        s07_readback_age_seconds=2.0, unresolved_authority_gate="APPROVAL_ABSENT",
    )


class RunnerTests(unittest.TestCase):
    def call(self, result=None):
        result = result or assembly()
        captured = {}

        def write_once(path, payload):
            captured.update(payload)
            raw = runner.canonical_json_bytes(payload) + b"\n"
            return hashlib.sha256(raw).hexdigest()

        with patch.object(runner, "_effective_uid", return_value=0), \
             patch.object(runner, "load_canonical_artifacts", return_value=object()), \
             patch.object(runner, "load_installed_s07_artifacts", return_value=object()), \
             patch.object(runner, "assemble_v6_proposal", return_value=result), \
             patch.object(runner, "_write_once", side_effect=write_once):
            payload, digest = runner.run(
                client=object(), repository_root=Path("repo"),
                s07_directory=Path("s07"),
                preregistration_manifest_path=Path("manifest"),
                output_path=Path("output"), runtime_git_commit="e" * 40,
                observed_at_utc=datetime(2026, 8, 28, 12, tzinfo=timezone.utc),
            )
        return payload, digest, captured

    def test_exact_unsigned_zero_output_payload(self):
        payload, digest, captured = self.call()
        self.assertEqual(payload, captured)
        self.assertEqual(payload["status"], "VERIFIED_UNSIGNED_PROPOSAL_ONLY")
        self.assertEqual(payload["proposal"]["selection_count"], 0)
        self.assertFalse(payload["boundary"]["execution_authorized"])
        self.assertTrue(all(
            value == 0 for key, value in payload["boundary"].items()
            if key != "execution_authorized"
        ))
        self.assertEqual(len(digest), 64)

    def test_real_immutable_mapping_proposal_is_not_deepcopied(self):
        result = assembly()
        summary = runner._assembly_summary(result)
        self.assertNotIn("proposal", summary)
        self.assertEqual(summary["panel_shape"], (472, 416))
        self.assertEqual(
            runner._proposal_summary(result.proposal)["artifact_sha256"],
            {"proposal_core": "c" * 64},
        )

    def test_stale_or_authorized_assembly_never_writes(self):
        for result in (assembly(fresh=False), assembly(execution=True)):
            write = Mock()
            with patch.object(runner, "_effective_uid", return_value=0), \
                 patch.object(runner, "load_canonical_artifacts", return_value=object()), \
                 patch.object(runner, "load_installed_s07_artifacts", return_value=object()), \
                 patch.object(runner, "assemble_v6_proposal", return_value=result), \
                 patch.object(runner, "_write_once", write):
                with self.assertRaisesRegex(runner.SelectOnlyRunnerError, "fresh and inert"):
                    runner.run(
                        client=object(), repository_root=Path("repo"),
                        s07_directory=Path("s07"),
                        preregistration_manifest_path=Path("manifest"),
                        output_path=Path("output"), runtime_git_commit="e" * 40,
                        observed_at_utc=datetime.now(timezone.utc),
                    )
            write.assert_not_called()

    def test_nonroot_and_invalid_commit_fail_before_loading(self):
        load = Mock()
        with patch.object(runner, "_effective_uid", return_value=1000), \
             patch.object(runner, "load_canonical_artifacts", load):
            with self.assertRaisesRegex(runner.SelectOnlyRunnerError, "root"):
                runner.run(
                    client=object(), repository_root=Path("repo"),
                    s07_directory=Path("s07"), preregistration_manifest_path=Path("m"),
                    output_path=Path("o"), runtime_git_commit="e" * 40,
                    observed_at_utc=datetime.now(timezone.utc),
                )
        load.assert_not_called()

        with patch.object(runner, "_effective_uid", return_value=0), \
             patch.object(runner, "load_canonical_artifacts", load):
            with self.assertRaisesRegex(runner.SelectOnlyRunnerError, "Git commit"):
                runner.run(
                    client=object(), repository_root=Path("repo"),
                    s07_directory=Path("s07"), preregistration_manifest_path=Path("m"),
                    output_path=Path("o"), runtime_git_commit="bad",
                    observed_at_utc=datetime.now(timezone.utc),
                )
        load.assert_not_called()

    def test_write_once_refuses_existing_output(self):
        with patch.object(runner, "_root_directory"), \
             patch.object(runner, "write_json_once", side_effect=runner.RuntimeBoundaryError(
                 "output already exists; overwrite is prohibited"
             )):
            with self.assertRaisesRegex(runner.SelectOnlyRunnerError, "already exists"):
                runner._write_once(Path("evidence.json"), {"status": "x"})

    def test_timeout_contract(self):
        for timeout in (9.9, 300.1):
            with self.assertRaisesRegex(runner.SelectOnlyRunnerError, "timeout"):
                runner.run_from_files(
                    env_file=Path("env"), repository_root=Path("repo"),
                    s07_directory=Path("s07"), preregistration_manifest_path=Path("m"),
                    output_path=Path("o"), runtime_git_commit="e" * 40,
                    timeout_seconds=timeout,
                )

    def test_source_has_no_model_selection_or_operational_surface(self):
        tree = ast.parse(Path(runner.__file__).read_text(encoding="utf-8"))
        forbidden_imports = {"pymc", "arviz", "subprocess"}
        forbidden_calls = {"system", "popen", "remove", "rename", "rmdir"}
        imports, calls = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
        self.assertTrue(forbidden_imports.isdisjoint(imports))
        self.assertTrue(forbidden_calls.isdisjoint(calls))


if __name__ == "__main__":
    unittest.main()
