import ast
import copy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    from . import stock_preregistration_runtime as runtime
    from . import audit_stock_preregistration_manifest as auditor
    from . import current_baseline_readback_contract as rb
    from . import verify_current_baseline_readback as readback_verifier
    from .stock_model_preregistration import PreregistrationError, canonical_sha
    from . import test_stock_model_preregistration_binding as binding_tests
except ImportError:  # Direct execution from the artifact directory.
    import stock_preregistration_runtime as runtime
    import audit_stock_preregistration_manifest as auditor
    import current_baseline_readback_contract as rb
    import verify_current_baseline_readback as readback_verifier
    from stock_model_preregistration import PreregistrationError, canonical_sha
    import test_stock_model_preregistration_binding as binding_tests
FAILURES = (runtime.RuntimeBoundaryError, runtime.PreregistrationError,
            auditor.PreregistrationError, rb.ReadbackContractError, PreregistrationError)


class PreregistrationRuntimeTests(unittest.TestCase):
    def setUp(self):
        fixture = binding_tests.V4BindingTests(
            methodName="test_happy_path_is_fixture_only_pass_and_zero_execution")
        fixture.setUp()
        self.fixture = fixture
        self.manifest = fixture.bind()
        self.readback_at = fixture.observed + timedelta(hours=2)
        ml = self.manifest["lineage"]; ba=self.manifest["baseline_audit"]
        lineage=rb.ImmutableV4AuditLineage(rb.SOURCE_AUDIT_CONTRACT_ID,ml["snapshot_id"],ml["snapshot_sha256"],ml["universe_id"],ml["universe_sha256"],ml["full_session_calendar_sha256"],ml["model_session_dates_sha256"],ml["baseline_manifest_sha256"],ml["source_audit_artifact_sha256"],ml["embedded_audit_evidence_sha256"],ml["baseline_audit_sha256"],fixture.executor_commit,fixture.completion, fixture.completion+timedelta(minutes=10))
        evidence=rb.CurrentReadbackEvidence(rb.ReadbackStatus.VERIFIED_SELECT_ONLY,ml["snapshot_id"],ml["snapshot_sha256"],ml["universe_id"],ml["universe_sha256"],ml["full_session_calendar_sha256"],ml["model_session_dates_sha256"],ml["baseline_manifest_sha256"],ml["source_audit_artifact_sha256"],ml["embedded_audit_evidence_sha256"],ml["baseline_audit_sha256"],"c"*64,"d"*64,self.readback_at-timedelta(seconds=2),self.readback_at,self.readback_at,rb.REQUIRED_SELECT_QUERIES,tuple(rb.NamedCount(*x) for x in rb.EXPECTED_COVERAGE),tuple(rb.NamedCount(*x) for x in rb.EXPECTED_SIDE_EFFECTS),tuple(rb.NamedCount(*x) for x in rb.EXPECTED_DOWNSTREAM))
        req=rb.ReadbackRequest(lineage,tuple(self.manifest["full_session_calendar_dates"]),tuple(self.manifest["model_session_dates"]),evidence)
        artifact=rb.build_verified_readback(req,observed_at_utc=self.readback_at)
        self.readback=rb._primitive(artifact)
        self.audit_at = self.readback_at + timedelta(minutes=5)

    @staticmethod
    def resign_manifest(manifest):
        body = dict(manifest)
        body.pop("checkpoint_identity_sha256")
        manifest["checkpoint_identity_sha256"] = canonical_sha(body)

    def audit(self, **changes):
        values = dict(
            manifest=self.manifest, manifest_raw_sha256="a" * 64,
            current_readback=self.readback, current_readback_raw_sha256="b" * 64,
            observed_at_utc=self.audit_at,
        )
        values.update(changes)
        f=self.fixture
        with mock.patch.multiple(auditor,PINNED_EXECUTOR_COMMIT=f.executor_commit,
             SNAPSHOT_ID=f.lineage["snapshot_id"],SNAPSHOT_SHA256=f.lineage["snapshot_sha256"],
             PINNED_UNIVERSE_SHA256=f.lineage["ticker_universe_sha256"],
             SESSION_SHA256=f.session_sha,PINNED_MODEL_SLICE_SHA256=canonical_sha(f.sessions[-416:]),
             PINNED_FINAL_MANIFEST_RAW_SHA256=f.final_raw,
             PINNED_IMMUTABLE_AUDIT_RAW_SHA256=f.immutable_raw,
             PINNED_IMMUTABLE_AUDIT_EMBEDDED_SHA256=f.immutable["audit_evidence_sha256"]):
            return auditor.audit_persisted_manifest(**values)

    def test_perpetual_readback_audits_fixture_only_manifest(self):
        result = self.audit()
        self.assertEqual(result["status"], "VERIFIED_FIXTURE_ONLY")
        self.assertFalse(result["model_fit_authorized"])
        self.assertEqual(result["checkpoint_identity_sha256"],
                         self.manifest["checkpoint_identity_sha256"])

    def test_new_run_binder_uses_perpetual_readback_not_expired_v4_reaudit(self):
        f=self.fixture
        with (mock.patch.multiple(runtime.binding,
              SESSION_SHA256=f.session_sha,
              PINNED_FINAL_MANIFEST_RAW_SHA256=f.final_raw,
              PINNED_IMMUTABLE_AUDIT_RAW_SHA256=f.immutable_raw,
              PINNED_IMMUTABLE_AUDIT_EMBEDDED_SHA256=f.immutable["audit_evidence_sha256"],
              PINNED_EXECUTOR_COMMIT=f.executor_commit,
              PINNED_EXECUTOR_MANIFEST_RAW_SHA256="2"*64,
              PINNED_CHECKPOINT_SET_SHA256="3"*64,
              PINNED_DETERMINISTIC_EVIDENCE_SHA256=f.final["deterministic_evidence_sha256"],
              PINNED_BASELINE_LINEAGE_SHA256=canonical_sha(f.lineage),
              PINNED_UNIVERSE_SHA256=f.lineage["ticker_universe_sha256"],
              PINNED_MODEL_SLICE_SHA256=canonical_sha(f.sessions[-416:])),
              mock.patch.multiple(auditor,PINNED_EXECUTOR_COMMIT=f.executor_commit,
              SNAPSHOT_ID=f.lineage["snapshot_id"],SNAPSHOT_SHA256=f.lineage["snapshot_sha256"],
              PINNED_UNIVERSE_SHA256=f.lineage["ticker_universe_sha256"],SESSION_SHA256=f.session_sha,
              PINNED_MODEL_SLICE_SHA256=canonical_sha(f.sessions[-416:]),
              PINNED_FINAL_MANIFEST_RAW_SHA256=f.final_raw,
              PINNED_IMMUTABLE_AUDIT_RAW_SHA256=f.immutable_raw,
              PINNED_IMMUTABLE_AUDIT_EMBEDDED_SHA256=f.immutable["audit_evidence_sha256"])):
            manifest=runtime.bind_perpetual_readback(
                final_manifest=f.final,immutable_audit=f.immutable,
                lineage_mapping=f.lineage,current_readback=self.readback,
                final_manifest_file_sha256=f.final_raw,
                immutable_audit_file_sha256=f.immutable_raw,
                current_model_git_commit="4"*40,observed_at_utc=self.audit_at,
                run_id="perpetual-new-run")
        self.assertEqual(manifest["preflight"]["status"],"PASS")
        self.assertFalse(manifest["preflight"]["model_fit_authorized"])

    def test_rehashed_readback_semantic_attacks_fail_closed(self):
        mutations = []
        lineage = copy.deepcopy(self.readback)
        lineage["lineage"]["snapshot_sha256"] = "c" * 64
        mutations.append(lineage)
        downstream = copy.deepcopy(self.readback)
        next(x for x in downstream["evidence"]["downstream_counts"] if x["name"]=="model_runs")["count"] = 1
        mutations.append(downstream)
        checks = copy.deepcopy(self.readback)
        checks["boundary"]["model_fit_authorized"] = True
        mutations.append(checks)
        partial = copy.deepcopy(self.readback)
        next(x for x in partial["evidence"]["coverage"] if x["name"]=="tickers")["count"] = 473
        mutations.append(partial)
        for attacked in mutations:
            with self.subTest(attacked=attacked):
                with self.assertRaises(FAILURES):
                    self.audit(current_readback=attacked)

    def test_stale_retimestamped_and_digest_substitution_fail(self):
        with self.assertRaises(FAILURES):
            self.audit(observed_at_utc=self.readback_at + timedelta(hours=2))
        attacked = copy.deepcopy(self.readback)
        attacked["observed_at_utc"] = (self.readback_at + timedelta(minutes=1)).isoformat()
        with self.assertRaises(FAILURES):
            self.audit(current_readback=attacked)
        attacked=copy.deepcopy(self.readback)
        attacked["evidence"]["source_readback_artifact_sha256"]=attacked["evidence"]["source_readback_embedded_evidence_sha256"]
        with self.assertRaises(FAILURES):
            self.audit(current_readback=attacked)

    def test_ready_sampler_and_operational_attacks_fail_after_rehash(self):
        attacks = []
        ready = copy.deepcopy(self.manifest)
        ready["preflight"]["status"] = "READY"
        ready["preflight"]["model_fit_authorized"] = True
        attacks.append(ready)
        sampler = copy.deepcopy(self.manifest)
        sampler["sampler_config"]["engine"] = "unsafe"
        sampler["lineage"]["sampler_sha256"] = canonical_sha(sampler["sampler_config"])
        attacks.append(sampler)
        order = copy.deepcopy(self.manifest)
        order["execution"]["orders_created"] = 1
        attacks.append(order)
        for attacked in attacks:
            self.resign_manifest(attacked)
            with self.subTest():
                with self.assertRaises(FAILURES):
                    self.audit(manifest=attacked)

    def test_strict_json_rejects_duplicate_nonfinite_and_wrong_root(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'', b'\xff'):
            with self.subTest(raw=raw):
                with self.assertRaises(runtime.RuntimeBoundaryError):
                    runtime.decode_strict_json(raw, "fixture")

    def test_secure_reader_rejects_relative_path(self):
        with self.assertRaises(runtime.RuntimeBoundaryError):
            runtime.read_root_owned_json(Path("relative.json"), "fixture")

    @unittest.skipUnless(os.name == "posix", "POSIX ownership/symlink semantics")
    def test_secure_reader_rejects_symlink(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory).resolve()
            source = root / "source.json"
            source.write_text("{}", encoding="utf-8")
            link = root / "link.json"
            try:
                link.symlink_to(source)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(runtime.RuntimeBoundaryError):
                runtime.read_root_owned_json(link, "fixture")

    @unittest.skipUnless(os.name == "posix", "POSIX O_EXCL/fsync/hard-link semantics")
    def test_write_once_uses_new_target_and_refuses_overwrite(self):
        if not hasattr(os, "link"):
            self.skipTest("hard links unavailable")
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory).resolve()
            output = root / "manifest.json"
            with (mock.patch.object(runtime, "_require_root_owned", return_value=None),
                  mock.patch.object(runtime, "_secure_output_parent", return_value=root)):
                digest = runtime.write_json_once(output, {"fixture_only": True})
                self.assertEqual(digest, hashlib.sha256(output.read_bytes()).hexdigest())
                with self.assertRaises(runtime.RuntimeBoundaryError):
                    runtime.write_json_once(output, {"fixture_only": True})

    def test_runtime_modules_have_no_network_database_or_model_imports(self):
        forbidden = {"socket", "requests", "urllib", "httpx", "sqlite3", "libsql", "pymc"}
        for module in (runtime, auditor):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.add((node.module or "").split(".")[0])
            self.assertTrue(imports.isdisjoint(forbidden), imports & forbidden)

    def test_persistence_source_requires_exclusive_create_and_never_renames(self):
        source = Path(runtime.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        attributes = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        self.assertIn("O_EXCL", attributes)
        self.assertIn("O_NOFOLLOW", source)
        self.assertIn("fsync", attributes)
        self.assertIn("link", attributes)
        self.assertTrue({"rename", "replace"}.isdisjoint(attributes))

    def test_file_wrapper_passes_independent_raw_hashes_and_safe_state_only(self):
        safe = {
            "preflight": {"status": "PASS", "fixture_only": True,
                          "model_fit_authorized": False},
            "execution": {"model_fit_started": False},
        }
        paths = [Path.cwd() / f"input-{index}.json" for index in range(4)]
        output = Path.cwd() / "never-written-by-mock.json"
        decoded = [{"source": index} for index in range(4)]
        decoded[2]["lineage_mapping"] = {"bound": True}
        hashes = [str(index + 1) * 64 for index in range(4)]
        with (mock.patch.object(runtime, "read_root_owned_0600_json",
                                side_effect=list(zip(decoded, hashes))),
              mock.patch.object(runtime, "_verify_current_readback") as verify,
              mock.patch.object(runtime, "bind_perpetual_readback", return_value=safe) as bind,
              mock.patch.object(runtime, "write_json_once", return_value="f" * 64) as write):
            manifest, digest = runtime.bind_from_files(
                final_manifest_path=paths[0], immutable_audit_path=paths[1],
                source_readback_path=paths[2], current_readback_path=paths[3],
                output_path=output, current_model_git_commit="a" * 40,
                observed_at_utc=self.audit_at, run_id="fixture-run")
        self.assertIs(manifest, safe)
        self.assertEqual(digest, "f" * 64)
        kwargs = bind.call_args.kwargs
        self.assertEqual(kwargs["final_manifest_file_sha256"], hashes[0])
        self.assertEqual(kwargs["immutable_audit_file_sha256"], hashes[1])
        self.assertEqual(kwargs["lineage_mapping"], {"bound": True})
        verify.assert_called_once_with(
            source=decoded[2], source_raw_sha256=hashes[2],
            artifact=decoded[3], artifact_raw_sha256=hashes[3],
            final_manifest=decoded[0], final_raw_sha256=hashes[0],
            immutable_audit=decoded[1], immutable_audit_raw_sha256=hashes[1],
            proposed_model_git_commit="a" * 40,
        )
        write.assert_called_once_with(output, safe)

    def test_binder_and_auditor_cli_require_current_source_not_external_lineage(self):
        for module in (runtime, auditor):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertIn("--current-readback-source", source)
            self.assertNotIn("--readback-source", source)
            self.assertNotIn("--lineage-mapping", source)

    def test_auditor_file_wrapper_byte_binds_both_readback_layers_and_model_commit(self):
        commit = "9" * 40
        decoded = [
            {"lineage": {"code_git_commit": commit}}, {"source": True},
            {"artifact": True}, {"final": True}, {"audit": True},
        ]
        hashes = [str(index + 1) * 64 for index in range(5)]
        safe = {"status": "VERIFIED_FIXTURE_ONLY", "model_fit_authorized": False}
        with (mock.patch.object(auditor, "read_root_owned_0600_json",
                                side_effect=list(zip(decoded, hashes))),
              mock.patch.object(readback_verifier, "verify") as verify,
              mock.patch.object(auditor, "audit_persisted_manifest",
                                return_value=safe) as persisted):
            result = auditor.audit_from_files(
                manifest_path=Path("/root/manifest.json"),
                source_readback_path=Path("/root/source.json"),
                current_readback_path=Path("/root/readback.json"),
                final_manifest_path=Path("/root/final.json"),
                immutable_audit_path=Path("/root/audit.json"),
                observed_at_utc=self.audit_at,
            )
        self.assertIs(result, safe)
        verify.assert_called_once_with(
            source=decoded[1], source_raw_sha256=hashes[1],
            artifact=decoded[2], artifact_raw_sha256=hashes[2],
            final_manifest=decoded[3], final_raw_sha256=hashes[3],
            immutable_audit=decoded[4], immutable_audit_raw_sha256=hashes[4],
            proposed_model_git_commit=commit,
        )
        persisted.assert_called_once_with(
            manifest=decoded[0], manifest_raw_sha256=hashes[0],
            current_readback=decoded[2], current_readback_raw_sha256=hashes[2],
            observed_at_utc=self.audit_at,
        )


if __name__ == "__main__":
    unittest.main()
