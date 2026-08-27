import ast
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import unittest

try:
    from .current_baseline_readback_contract import (
        CONTRACT_ID,
        EXPECTED_COVERAGE,
        EXPECTED_DOWNSTREAM,
        EXPECTED_SIDE_EFFECTS,
        ImmutableV4AuditLineage,
        CurrentReadbackEvidence,
        NamedCount,
        OperationalBoundary,
        ReadbackContractError,
        ReadbackRequest,
        ReadbackStatus,
        REQUIRED_SELECT_QUERIES,
        SOURCE_AUDIT_CONTRACT_ID,
        audit_verified_readback,
        build_verified_readback,
        canonical_sha,
    )
except ImportError:  # Direct execution from the artifact directory.
    from current_baseline_readback_contract import (
    CONTRACT_ID,
    EXPECTED_COVERAGE,
    EXPECTED_DOWNSTREAM,
    EXPECTED_SIDE_EFFECTS,
    ImmutableV4AuditLineage,
    CurrentReadbackEvidence,
    NamedCount,
    OperationalBoundary,
    ReadbackContractError,
    ReadbackRequest,
    ReadbackStatus,
    REQUIRED_SELECT_QUERIES,
    SOURCE_AUDIT_CONTRACT_ID,
    audit_verified_readback,
    build_verified_readback,
    canonical_sha,
    )


class CurrentBaselineReadbackContractTests(unittest.TestCase):
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

    def calendars(self):
        full = tuple(
            (date(2022, 1, 1) + timedelta(days=index)).isoformat()
            for index in range(1_246)
        )
        return full, full[830:]

    @staticmethod
    def counts(values):
        return tuple(NamedCount(name, count) for name, count in values)

    def lineage(self):
        full, model = self.calendars()
        return ImmutableV4AuditLineage(
            source_contract_id=SOURCE_AUDIT_CONTRACT_ID,
            snapshot_id="market-features-20260826",
            snapshot_sha256="a" * 64,
            universe_id="approved-universe-v4",
            universe_sha256="b" * 64,
            full_session_calendar_sha256=canonical_sha(list(full)),
            model_session_dates_sha256=canonical_sha(list(model)),
            baseline_manifest_sha256="c" * 64,
            source_audit_artifact_sha256="d" * 64,
            embedded_audit_evidence_sha256="e" * 64,
            audit_envelope_sha256="f" * 64,
            source_code_git_sha="1" * 40,
            audit_completed_at_utc=self.now - timedelta(days=1, minutes=10),
            audit_observed_at_utc=self.now - timedelta(days=1),
        )

    def evidence(self, lineage=None, *, at=None, **changes):
        lineage = lineage or self.lineage()
        completed = at or self.now - timedelta(minutes=1)
        values = dict(
            status=ReadbackStatus.VERIFIED_SELECT_ONLY,
            snapshot_id=lineage.snapshot_id,
            snapshot_sha256=lineage.snapshot_sha256,
            universe_id=lineage.universe_id,
            universe_sha256=lineage.universe_sha256,
            full_session_calendar_sha256=lineage.full_session_calendar_sha256,
            model_session_dates_sha256=lineage.model_session_dates_sha256,
            baseline_manifest_sha256=lineage.baseline_manifest_sha256,
            source_audit_artifact_sha256=lineage.source_audit_artifact_sha256,
            embedded_audit_evidence_sha256=lineage.embedded_audit_evidence_sha256,
            audit_envelope_sha256=lineage.audit_envelope_sha256,
            source_readback_artifact_sha256="7" * 64,
            source_readback_embedded_evidence_sha256="8" * 64,
            query_started_at_utc=completed - timedelta(seconds=2),
            query_completed_at_utc=completed,
            source_readback_observed_at_utc=completed,
            select_query_ids=REQUIRED_SELECT_QUERIES,
            coverage=self.counts(EXPECTED_COVERAGE),
            side_effects=self.counts(EXPECTED_SIDE_EFFECTS),
            downstream_counts=self.counts(EXPECTED_DOWNSTREAM),
        )
        values.update(changes)
        return CurrentReadbackEvidence(**values)

    def request(self, *, lineage=None, evidence=None, full=None, model=None):
        lineage = lineage or self.lineage()
        actual_full, actual_model = self.calendars()
        return ReadbackRequest(
            lineage=lineage,
            full_session_calendar_dates=actual_full if full is None else full,
            model_session_dates=actual_model if model is None else model,
            evidence=evidence or self.evidence(lineage),
        )

    def test_exact_select_only_fixture_builds_verified_nonoperational_artifact(self):
        request = self.request()
        artifact = build_verified_readback(request, observed_at_utc=self.now)
        self.assertEqual(artifact.contract_id, CONTRACT_ID)
        self.assertEqual(artifact.status, ReadbackStatus.VERIFIED_SELECT_ONLY)
        self.assertTrue(artifact.artifact_id.startswith("current_baseline_readback_"))
        self.assertEqual(len(artifact.full_session_calendar_dates), 1_246)
        self.assertEqual(len(artifact.model_session_dates), 416)
        self.assertEqual(artifact.boundary, OperationalBoundary())
        self.assertFalse(artifact.boundary.model_fit_authorized)
        self.assertFalse(artifact.boundary.ready_state_available)
        audit_verified_readback(request, artifact, observed_at_utc=self.now)

    def test_contract_is_perpetual_but_each_readback_must_be_fresh(self):
        future = self.now + timedelta(days=30)
        request = self.request()
        with self.assertRaisesRegex(ReadbackContractError, "stale"):
            build_verified_readback(request, observed_at_utc=future)
        fresh = replace(request, evidence=self.evidence(request.lineage, at=future - timedelta(minutes=1)))
        artifact = build_verified_readback(fresh, observed_at_utc=future)
        self.assertEqual(artifact.lineage, request.lineage)

    def test_retimestamp_only_and_contradictory_chronology_fail(self):
        request = self.request()
        retimestamped = replace(
            request.evidence,
            query_completed_at_utc=self.now,
        )
        with self.assertRaisesRegex(ReadbackContractError, "contradictory or retimestamped"):
            build_verified_readback(replace(request, evidence=retimestamped), observed_at_utc=self.now)
        early = replace(
            request.evidence,
            query_started_at_utc=request.lineage.audit_observed_at_utc - timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ReadbackContractError, "contradictory"):
            build_verified_readback(replace(request, evidence=early), observed_at_utc=self.now)

    def test_raw_and_embedded_hashes_are_lowercase_distinct_and_not_substitutable(self):
        request = self.request()
        for value in (
            request.evidence.source_readback_artifact_sha256,
            request.lineage.source_audit_artifact_sha256,
            request.lineage.embedded_audit_evidence_sha256,
            request.lineage.audit_envelope_sha256,
        ):
            with self.subTest(value=value):
                forged = replace(request.evidence, source_readback_embedded_evidence_sha256=value)
                with self.assertRaisesRegex(ReadbackContractError, "identities are conflated"):
                    build_verified_readback(replace(request, evidence=forged), observed_at_utc=self.now)
        with self.assertRaisesRegex(ReadbackContractError, "lowercase"):
            build_verified_readback(
                replace(request, evidence=replace(
                    request.evidence,
                    source_readback_embedded_evidence_sha256="A" * 64,
                )),
                observed_at_utc=self.now,
            )

    def test_every_immutable_v4_identity_is_revalidated(self):
        request = self.request()
        fields = (
            "snapshot_id", "snapshot_sha256", "universe_id", "universe_sha256",
            "full_session_calendar_sha256", "model_session_dates_sha256",
            "baseline_manifest_sha256", "source_audit_artifact_sha256",
            "embedded_audit_evidence_sha256", "audit_envelope_sha256",
        )
        for field in fields:
            old = getattr(request.evidence, field)
            value = "changed-id" if field.endswith("_id") else "9" * 64
            self.assertNotEqual(old, value)
            with self.subTest(field=field):
                forged = replace(request.evidence, **{field: value})
                with self.assertRaisesRegex(ReadbackContractError, "preserve immutable"):
                    build_verified_readback(replace(request, evidence=forged), observed_at_utc=self.now)

    def test_full_and_model_calendar_identities_and_slice_are_exact(self):
        request = self.request()
        wrong_slice = request.full_session_calendar_dates[:416]
        with self.assertRaisesRegex(ReadbackContractError, "exact governed v4 slice"):
            build_verified_readback(replace(request, model_session_dates=wrong_slice), observed_at_utc=self.now)
        shifted = tuple(
            (date.fromisoformat(value) + timedelta(days=1)).isoformat()
            for value in request.full_session_calendar_dates
        )
        with self.assertRaisesRegex(ReadbackContractError, "identity differs"):
            build_verified_readback(
                replace(request, full_session_calendar_dates=shifted, model_session_dates=shifted[830:]),
                observed_at_utc=self.now,
            )

    def test_coverage_six_side_effects_and_eight_downstream_counts_are_exact(self):
        request = self.request()
        lanes = (
            ("coverage", EXPECTED_COVERAGE),
            ("side_effects", EXPECTED_SIDE_EFFECTS),
            ("downstream_counts", EXPECTED_DOWNSTREAM),
        )
        for field, expected in lanes:
            exact = list(self.counts(expected))
            variants = (
                tuple(exact[:-1]),
                tuple((*exact, NamedCount("extra", 0))),
                tuple((replace(exact[0], count=1), *exact[1:])),
                tuple((replace(exact[0], count=False), *exact[1:])),
                tuple((replace(exact[0], count=0.0), *exact[1:])),
            )
            for variant in variants:
                with self.subTest(field=field, variant=variant):
                    evidence = replace(request.evidence, **{field: variant})
                    with self.assertRaises(ReadbackContractError):
                        build_verified_readback(replace(request, evidence=evidence), observed_at_utc=self.now)

    def test_exact_select_query_set_rejects_missing_extra_duplicate_and_nonselect(self):
        request = self.request()
        variants = (
            REQUIRED_SELECT_QUERIES[:-1],
            (*REQUIRED_SELECT_QUERIES, "SELECT_EXTRA"),
            (*REQUIRED_SELECT_QUERIES[:-1], REQUIRED_SELECT_QUERIES[0]),
            (*REQUIRED_SELECT_QUERIES[:-1], "UPDATE_COUNTS"),
        )
        for query_ids in variants:
            with self.subTest(query_ids=query_ids):
                with self.assertRaisesRegex(ReadbackContractError, "SELECT"):
                    build_verified_readback(
                        replace(request, evidence=replace(request.evidence, select_query_ids=query_ids)),
                        observed_at_utc=self.now,
                    )

    def test_string_status_and_timestamp_coercions_fail_closed(self):
        request = self.request()
        with self.assertRaisesRegex(ReadbackContractError, "status"):
            build_verified_readback(
                replace(request, evidence=replace(request.evidence, status="VERIFIED_SELECT_ONLY")),
                observed_at_utc=self.now,
            )
        for timestamp in ("2026-08-27T12:00:00Z", date(2026, 8, 27), True):
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(ReadbackContractError):
                    build_verified_readback(
                        replace(request, evidence=replace(request.evidence, query_completed_at_utc=timestamp)),
                        observed_at_utc=self.now,
                    )
        non_utc = self.now.astimezone(timezone(timedelta(hours=2)))
        with self.assertRaisesRegex(ReadbackContractError, "normalized to UTC"):
            build_verified_readback(request, observed_at_utc=non_utc)

    def test_deep_freeze_detaches_mutable_fixture_collections(self):
        request = self.request()
        queries = list(request.evidence.select_query_ids)
        coverage = list(request.evidence.coverage)
        full = list(request.full_session_calendar_dates)
        mutable = replace(
            request,
            full_session_calendar_dates=full,
            evidence=replace(request.evidence, select_query_ids=queries, coverage=coverage),
        )
        artifact = build_verified_readback(mutable, observed_at_utc=self.now)
        before = canonical_sha(artifact)
        queries.clear()
        coverage.clear()
        full.clear()
        self.assertEqual(canonical_sha(artifact), before)
        self.assertIsInstance(artifact.evidence.coverage, tuple)

    def test_semantic_auditor_rejects_boundary_and_evidence_forgery_after_rehash(self):
        request = self.request()
        artifact = build_verified_readback(request, observed_at_utc=self.now)
        forged_boundary = replace(
            artifact,
            boundary=replace(artifact.boundary, model_fit_authorized=True),
        )
        forged_boundary = replace(
            forged_boundary,
            artifact_id="current_baseline_readback_" + canonical_sha(forged_boundary),
        )
        with self.assertRaisesRegex(ReadbackContractError, "boundary"):
            audit_verified_readback(request, forged_boundary, observed_at_utc=self.now)
        forged_evidence = replace(
            artifact,
            evidence=replace(
                artifact.evidence,
                downstream_counts=tuple((NamedCount("model_runs", 1), *artifact.evidence.downstream_counts[1:])),
            ),
        )
        forged_evidence = replace(
            forged_evidence,
            artifact_id="current_baseline_readback_" + canonical_sha(forged_evidence),
        )
        with self.assertRaisesRegex(ReadbackContractError, "semantics"):
            audit_verified_readback(request, forged_evidence, observed_at_utc=self.now)

    def test_no_ready_state_and_no_runtime_io_capabilities(self):
        self.assertEqual(tuple(ReadbackStatus), (ReadbackStatus.VERIFIED_SELECT_ONLY,))
        path = Path(__file__).with_name("current_baseline_readback_contract.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(imported <= {
            "__future__", "dataclasses", "datetime", "enum", "hashlib", "json", "re", "typing",
        })
        forbidden = {"open", "connect", "execute", "executemany", "request", "run", "Popen", "system"}
        called = {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden.isdisjoint(called))


if __name__ == "__main__":
    unittest.main()
