import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

try:
    from .stock_model_preregistration import (
        BaselineAuditEvidence,
        BaselineReadbackProof,
        CLAIM_SCOPE,
        EXPECTED_DEPTHS,
        EXPECTED_LAGS,
        INDEPENDENT_TOPOLOGY,
        ImmutableLineage,
        ModelConfiguration,
        PreregistrationError,
        PreregistrationRequest,
        ProhibitedOutputIntent,
        RUN_MODE_NEW,
        RUN_MODE_RESUME,
        SamplerConfiguration,
        WalkForwardFold,
        audit_preregistration_manifest,
        canonical_sha,
        compute_baseline_audit_sha256,
        preregister_model_run,
    )
except ImportError:  # Direct execution from the artifact directory.
    from stock_model_preregistration import (
        BaselineAuditEvidence,
        BaselineReadbackProof,
        CLAIM_SCOPE,
        EXPECTED_DEPTHS,
        EXPECTED_LAGS,
        INDEPENDENT_TOPOLOGY,
        ImmutableLineage,
        ModelConfiguration,
        PreregistrationError,
        PreregistrationRequest,
        ProhibitedOutputIntent,
        RUN_MODE_NEW,
        RUN_MODE_RESUME,
        SamplerConfiguration,
        WalkForwardFold,
        audit_preregistration_manifest,
        canonical_sha,
        compute_baseline_audit_sha256,
        preregister_model_run,
    )


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_D = "d" * 64


class StockModelPreregistrationTests(unittest.TestCase):
    now = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)

    def model_config(self, **changes):
        values = dict(
            topology=INDEPENDENT_TOPOLOGY,
            candidate_lags=EXPECTED_LAGS,
            candidate_depths=EXPECTED_DEPTHS,
            minimum_fit_observations=126,
            purge_sessions=7,
            claim_scope=CLAIM_SCOPE,
            fold_count=4,
            training_width_sessions=289,
            test_width_sessions=30,
            step_sessions=30,
            calendar_start_ordinal=0,
            calendar_end_ordinal=415,
        )
        values.update(changes)
        return ModelConfiguration(**values)

    def sampler_config(self):
        return SamplerConfiguration("pymc-nuts", 4, 1_000, 1_000, 0.9, 20260827)

    def audit(self, **changes):
        values = dict(
            status="VERIFIED",
            baseline_manifest_sha256=SHA_D,
            audit_sha256="0" * 64,
            completed_at_utc=self.now - timedelta(minutes=10),
            observed_at_utc=self.now - timedelta(minutes=5),
            ticker_count=474,
            fold_count=1_896,
            oos_observation_count=56_880,
            side_effects={
                "database_writes": 0,
                "bayesian_fits": 0,
                "predictions": 0,
                "recommendations": 0,
                "orders": 0,
                "etf_outputs": 0,
            },
        )
        values.update(changes)
        evidence = BaselineAuditEvidence(**values)
        return replace(evidence, audit_sha256=compute_baseline_audit_sha256(evidence))

    def readback(self, audit=None, **changes):
        audit = audit or self.audit()
        values = dict(
            status="VERIFIED",
            baseline_manifest_sha256=audit.baseline_manifest_sha256,
            baseline_audit_sha256=audit.audit_sha256,
            readback_at_utc=self.now - timedelta(minutes=1),
            ticker_count=audit.ticker_count,
            fold_count=audit.fold_count,
            oos_observation_count=audit.oos_observation_count,
            side_effects=dict(audit.side_effects),
        )
        values.update(changes)
        return BaselineReadbackProof(**values)

    def folds_for(self, model):
        folds = []
        for index in range(model.fold_count):
            train_start = model.calendar_start_ordinal + index * model.step_sessions
            train_end = train_start + model.training_width_sessions - 1
            test_start = train_end + model.purge_sessions + 1
            test_end = test_start + model.test_width_sessions - 1
            folds.append(WalkForwardFold(
                index + 1, train_start, train_end, test_start, test_end,
                model.training_width_sessions, model.purge_sessions,
            ))
        return tuple(folds)

    def request(self, *, model=None, sampler=None, audit="default", output=None, folds=None):
        model = model or self.model_config()
        sampler = sampler or self.sampler_config()
        baseline_audit = self.audit() if audit == "default" else audit
        audit_sha = baseline_audit.audit_sha256 if baseline_audit else "e" * 64
        calendar = tuple(range(416))
        return PreregistrationRequest(
            run_id="stock-hierarchical-20260827-v1",
            lineage=ImmutableLineage(
                snapshot_id="market-features-20260826",
                snapshot_sha256=SHA_A,
                universe_id="approved-universe-v1",
                universe_sha256=SHA_B,
                session_calendar_sha256=canonical_sha(list(calendar)),
                baseline_manifest_sha256=SHA_D,
                baseline_audit_sha256=audit_sha,
                code_git_commit="1" * 40,
                config_sha256=canonical_sha(model.__dict__),
                sampler_sha256=canonical_sha(sampler.__dict__),
            ),
            model_config=model,
            sampler_config=sampler,
            folds=self.folds_for(model) if folds is None else folds,
            output_intent=output or ProhibitedOutputIntent(),
            baseline_audit=baseline_audit,
            session_calendar_ordinals=calendar,
        )

    def new_manifest(self, request=None, readback=None):
        request = request or self.request()
        return preregister_model_run(
            request,
            observed_at_utc=self.now,
            mode=RUN_MODE_NEW,
            current_readback=readback or self.readback(request.baseline_audit),
        )

    def manifest_readback(self, manifest, *, readback_at=None, **changes):
        audit = manifest["baseline_audit"]
        values = dict(
            status="VERIFIED",
            baseline_manifest_sha256=audit["baseline_manifest_sha256"],
            baseline_audit_sha256=audit["audit_sha256"],
            readback_at_utc=readback_at or self.now - timedelta(minutes=1),
            ticker_count=audit["ticker_count"],
            fold_count=audit["fold_count"],
            oos_observation_count=audit["oos_observation_count"],
            side_effects=dict(audit["side_effects"]),
        )
        values.update(changes)
        return BaselineReadbackProof(**values)

    def independent_audit(self, manifest, *, observed_at=None, readback=None):
        return audit_preregistration_manifest(
            manifest,
            observed_at_utc=observed_at or self.now,
            current_readback=readback or self.manifest_readback(manifest),
        )

    @staticmethod
    def resign(manifest):
        payload = copy.deepcopy(manifest)
        payload.pop("checkpoint_identity_sha256")
        manifest["checkpoint_identity_sha256"] = canonical_sha(payload)

    @staticmethod
    def rebind_audit(manifest):
        audit = manifest["baseline_audit"]
        payload = {key: value for key, value in audit.items() if key != "audit_sha256"}
        audit_sha = canonical_sha(payload)
        audit["audit_sha256"] = audit_sha
        manifest["lineage"]["baseline_audit_sha256"] = audit_sha

    @staticmethod
    def rebind_config(manifest):
        manifest["lineage"]["config_sha256"] = canonical_sha(manifest["model_config"])

    def test_valid_contract_binds_semantics_preflight_and_audit_digest(self):
        manifest = self.new_manifest()
        self.assertEqual(manifest["model_config"]["candidate_lags"], EXPECTED_LAGS)
        self.assertEqual(manifest["model_config"]["candidate_depths"], EXPECTED_DEPTHS)
        self.assertFalse(manifest["execution"]["model_fit_started"])
        self.assertFalse(manifest["preflight"]["model_fit_authorized"])
        identity_payload = dict(manifest)
        identity_payload.pop("checkpoint_identity_sha256")
        self.assertEqual(manifest["checkpoint_identity_sha256"], canonical_sha(identity_payload))
        self.independent_audit(manifest)
        serialized = json.loads(json.dumps(manifest))
        self.independent_audit(serialized)

    def test_new_run_and_resume_modes_are_explicit_and_identity_bound(self):
        request = self.request()
        manifest = self.new_manifest(request)
        initial_readback = self.readback(request.baseline_audit)
        with self.assertRaisesRegex(PreregistrationError, "explicitly NEW_RUN or RESUME"):
            preregister_model_run(
                request, observed_at_utc=self.now, mode="AUTO",
                current_readback=initial_readback,
            )
        with self.assertRaisesRegex(PreregistrationError, "NEW_RUN cannot accept"):
            preregister_model_run(
                request, observed_at_utc=self.now, mode=RUN_MODE_NEW,
                current_readback=initial_readback,
                expected_checkpoint_identity=manifest["checkpoint_identity_sha256"],
            )
        with self.assertRaisesRegex(PreregistrationError, "RESUME requires"):
            preregister_model_run(
                request, observed_at_utc=self.now, mode=RUN_MODE_RESUME,
                current_readback=initial_readback,
            )
        resume_time = self.now + timedelta(hours=2)
        fresh_readback = self.readback(
            request.baseline_audit,
            readback_at_utc=resume_time - timedelta(minutes=1),
        )
        resumed = preregister_model_run(
            request,
            observed_at_utc=resume_time,
            mode=RUN_MODE_RESUME,
            current_readback=fresh_readback,
            expected_checkpoint_identity=manifest["checkpoint_identity_sha256"],
            existing_manifest=manifest,
        )
        self.assertEqual(resumed, manifest)
        with self.assertRaisesRegex(PreregistrationError, "readback proof is stale"):
            preregister_model_run(
                request,
                observed_at_utc=resume_time,
                mode=RUN_MODE_RESUME,
                current_readback=initial_readback,
                expected_checkpoint_identity=manifest["checkpoint_identity_sha256"],
                existing_manifest=manifest,
            )
        changed = replace(request, run_id="stock-hierarchical-20260827-v2")
        with self.assertRaisesRegex(PreregistrationError, "differs from frozen"):
            preregister_model_run(
                changed,
                observed_at_utc=resume_time,
                mode=RUN_MODE_RESUME,
                current_readback=fresh_readback,
                expected_checkpoint_identity=manifest["checkpoint_identity_sha256"],
                existing_manifest=manifest,
            )

    def test_governed_geometry_cannot_be_reconfigured(self):
        cases = (
            ("minimum_fit_observations", 125),
            ("fold_count", 3),
            ("training_width_sessions", 288),
            ("test_width_sessions", 29),
            ("step_sessions", 29),
            ("purge_sessions", 6),
        )
        for field, value in cases:
            with self.subTest(field=field):
                model = self.model_config(**{field: value})
                with self.assertRaisesRegex(PreregistrationError, "governed geometry"):
                    self.new_manifest(self.request(model=model))

    def test_exact_walk_forward_geometry_is_enforced(self):
        request = self.request()
        bad_end = list(request.folds)
        bad_end[0] = replace(bad_end[0], test_end_ordinal=324)
        bad_step = list(request.folds)
        bad_step[1] = replace(bad_step[1], train_start_ordinal=31)
        bad_purge = list(request.folds)
        bad_purge[1] = replace(bad_purge[1], purge_sessions=6)
        cases = (
            (request.folds[:-1], "fold count"),
            (tuple(bad_end), "frozen geometry"),
            (tuple(bad_step), "frozen geometry"),
            (tuple(bad_purge), "configured purge"),
        )
        for folds, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(PreregistrationError, message):
                    self.new_manifest(replace(request, folds=folds))

    def test_primary_validators_reject_unsafe_requests(self):
        cases = (
            (self.request(model=self.model_config(topology="FORCED_5_TO_4_TO_3_CHAIN")), "forced-chain"),
            (self.request(model=self.model_config(claim_scope="CAUSAL_PROOF")), "not causal"),
            (self.request(output=replace(ProhibitedOutputIntent(), create_orders=True)), "prohibited downstream"),
            (self.request(audit=None), "missing"),
            (self.request(audit=self.audit(ticker_count=473)), "partial"),
            (self.request(audit=self.audit(side_effects={**self.audit().side_effects, "orders": 1})), "side effects"),
        )
        for request, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(PreregistrationError, message):
                    self.new_manifest(request)

    def test_current_readback_is_mandatory_fresh_and_lineage_matching(self):
        old_audit = self.audit(
            completed_at_utc=self.now - timedelta(hours=3),
            observed_at_utc=self.now - timedelta(hours=2, minutes=50),
        )
        request = self.request(audit=old_audit)
        cases = (
            (None, "required"),
            (self.readback(
                request.baseline_audit,
                readback_at_utc=self.now - timedelta(hours=2),
            ), "stale"),
            (self.readback(
                request.baseline_audit,
                baseline_audit_sha256="f" * 64,
            ), "lineage mismatch"),
            (self.readback(
                request.baseline_audit,
                ticker_count=473,
            ), "partial"),
        )
        for readback, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(PreregistrationError, message):
                    preregister_model_run(
                        request,
                        observed_at_utc=self.now,
                        mode=RUN_MODE_NEW,
                        current_readback=readback,
                    )

    def test_readback_cannot_fall_between_audit_completion_and_observation(self):
        audit = self.audit(
            completed_at_utc=self.now - timedelta(minutes=10),
            observed_at_utc=self.now - timedelta(minutes=5),
        )
        request = self.request(audit=audit)
        between = self.readback(
            audit, readback_at_utc=self.now - timedelta(minutes=7)
        )
        with self.assertRaisesRegex(PreregistrationError, "predates immutable evidence"):
            self.new_manifest(request, readback=between)

    def test_auditor_replays_every_semantic_validator_after_resigning(self):
        mutators = []

        def forced_chain(m):
            m["model_config"]["topology"] = "FORCED_5_TO_4_TO_3_CHAIN"
            self.rebind_config(m)
        mutators.append((forced_chain, "forced-chain"))

        def causal_claim(m):
            m["model_config"]["claim_scope"] = "CAUSAL_PROOF"
            self.rebind_config(m)
        mutators.append((causal_claim, "not causal"))

        mutators.append((lambda m: m["output_intent"].update(create_orders=True), "prohibited downstream"))

        def partial(m):
            m["baseline_audit"]["ticker_count"] = 473
            self.rebind_audit(m)
        mutators.append((partial, "partial"))

        def side_effect(m):
            m["baseline_audit"]["side_effects"]["orders"] = 1
            self.rebind_audit(m)
        mutators.append((side_effect, "side effects"))

        mutators.extend((
            (lambda m: m["lineage"].update(config_sha256="f" * 64), "configuration lineage mismatch"),
            (lambda m: m["lineage"].update(sampler_sha256="f" * 64), "sampler configuration lineage mismatch"),
            (lambda m: m["folds"][1].update(test_start_ordinal=327), "frozen geometry"),
            (lambda m: m["execution"].update(model_fit_started=True), "downstream outputs"),
        ))

        def fully_rebound_calendar(start):
            def mutate(m):
                delta = start
                calendar = tuple(range(start, start + 416))
                m["session_calendar_ordinals"] = calendar
                m["lineage"]["session_calendar_sha256"] = canonical_sha(list(calendar))
                m["model_config"]["calendar_start_ordinal"] = calendar[0]
                m["model_config"]["calendar_end_ordinal"] = calendar[-1]
                self.rebind_config(m)
                for fold in m["folds"]:
                    for field in (
                        "train_start_ordinal", "train_end_ordinal",
                        "test_start_ordinal", "test_end_ordinal",
                    ):
                        fold[field] += delta
            return mutate

        mutators.append((fully_rebound_calendar(100), "governed ordinals"))
        mutators.append((fully_rebound_calendar(-100), "governed ordinals"))

        def overlapping_outer_test(m):
            m["folds"][1]["test_start_ordinal"] = m["folds"][0]["test_start_ordinal"]
            m["folds"][1]["test_end_ordinal"] = m["folds"][0]["test_end_ordinal"]
        mutators.append((overlapping_outer_test, "frozen geometry"))
        for mutate, message in mutators:
            with self.subTest(message=message):
                manifest = self.new_manifest()
                mutate(manifest)
                self.resign(manifest)
                with self.assertRaisesRegex(PreregistrationError, message):
                    self.independent_audit(manifest)

    def test_auditor_recomputes_baseline_digest_not_just_digest_syntax(self):
        manifest = self.new_manifest()
        manifest["baseline_audit"]["ticker_count"] = 473
        self.resign(manifest)
        with self.assertRaisesRegex(PreregistrationError, "evidence digest mismatch"):
            self.independent_audit(manifest)

    def test_auditor_rejects_preflight_bypasses_even_when_resigned(self):
        cases = (
            ("model_fit_authorized", True),
            ("fixture_only", False),
            ("status", "SKIPPED"),
            ("registration_mode", "RESUME"),
            ("semantic_validators", ("lineage",)),
            ("semantic_validators", 1),
        )
        for field, value in cases:
            with self.subTest(field=field):
                manifest = self.new_manifest()
                manifest["preflight"][field] = value
                self.resign(manifest)
                with self.assertRaisesRegex(PreregistrationError, "preflight evidence"):
                    self.independent_audit(manifest)

    def test_every_prohibited_output_flag_is_rejected(self):
        for field in (
            "persist_predictions", "create_recommendations", "create_orders",
            "create_etf_outputs", "activate_trading",
        ):
            with self.subTest(field=field):
                output = replace(ProhibitedOutputIntent(), **{field: True})
                with self.assertRaisesRegex(PreregistrationError, "prohibited downstream"):
                    self.new_manifest(self.request(output=output))

    def test_calendar_ordinal_list_is_semantically_hashed_and_canonical(self):
        request = self.request()
        changed_calendar = tuple(range(1, 417))
        with self.assertRaisesRegex(PreregistrationError, "governed ordinals"):
            self.new_manifest(replace(request, session_calendar_ordinals=changed_calendar))
        for changed_calendar in (tuple(range(100, 516)), tuple(range(-100, 316))):
            with self.subTest(calendar_start=changed_calendar[0]):
                rebound_shift = replace(
                    request,
                    session_calendar_ordinals=changed_calendar,
                    lineage=replace(
                        request.lineage,
                        session_calendar_sha256=canonical_sha(list(changed_calendar)),
                    ),
                    model_config=replace(
                        request.model_config,
                        calendar_start_ordinal=changed_calendar[0],
                        calendar_end_ordinal=changed_calendar[-1],
                    ),
                )
                rebound_shift = replace(
                    rebound_shift,
                    lineage=replace(
                        rebound_shift.lineage,
                        config_sha256=canonical_sha(rebound_shift.model_config.__dict__),
                    ),
                    folds=self.folds_for(rebound_shift.model_config),
                )
                with self.assertRaisesRegex(PreregistrationError, "governed ordinals"):
                    self.new_manifest(rebound_shift)
        noncontiguous_calendar = list(request.session_calendar_ordinals)
        noncontiguous_calendar[100] = 102
        noncontiguous_calendar = tuple(noncontiguous_calendar)
        rebound = replace(
            request,
            session_calendar_ordinals=noncontiguous_calendar,
            lineage=replace(
                request.lineage,
                session_calendar_sha256=canonical_sha(list(noncontiguous_calendar)),
            ),
        )
        with self.assertRaisesRegex(PreregistrationError, "not contiguous"):
            self.new_manifest(rebound)

    def test_integer_fields_reject_bool_and_float_values(self):
        model_cases = (
            self.model_config(minimum_fit_observations=True),
            self.model_config(test_width_sessions=30.0),
            self.model_config(candidate_lags=(*range(1, 7), True)),
            self.model_config(candidate_depths=(1, 2, 3, 4, 5.0)),
        )
        for model in model_cases:
            with self.subTest(model=model):
                with self.assertRaises(PreregistrationError):
                    self.new_manifest(self.request(model=model))

        request = self.request()
        bad_folds = list(request.folds)
        bad_folds[0] = replace(bad_folds[0], fit_observations=289.0)
        with self.assertRaisesRegex(PreregistrationError, "must be an integer"):
            self.new_manifest(replace(request, folds=tuple(bad_folds)))
        with self.assertRaisesRegex(PreregistrationError, "must be an integer"):
            self.new_manifest(self.request(sampler=replace(self.sampler_config(), chains=4.0)))
        with self.assertRaisesRegex(PreregistrationError, "must be an integer"):
            self.new_manifest(self.request(audit=self.audit(ticker_count=True)))
        with self.assertRaisesRegex(PreregistrationError, "must be an integer"):
            self.new_manifest(self.request(audit=self.audit(
                side_effects={**self.audit().side_effects, "orders": False}
            )))

    def test_nonfinite_values_and_boolean_zero_bypasses_fail_closed(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(PreregistrationError, "unsupported value"):
                    canonical_sha({"value": value})
                with self.assertRaisesRegex(PreregistrationError, "unsupported value"):
                    self.request(
                        sampler=replace(self.sampler_config(), target_accept=value)
                    )
        manifest = self.new_manifest()
        manifest["execution"]["predictions_created"] = False
        self.resign(manifest)
        with self.assertRaisesRegex(PreregistrationError, "downstream outputs"):
            self.independent_audit(manifest)

    def test_independent_auditor_requires_explicit_current_time_and_readback(self):
        manifest = self.new_manifest()
        with self.assertRaises(TypeError):
            audit_preregistration_manifest(manifest)
        with self.assertRaisesRegex(PreregistrationError, "readback proof is required"):
            audit_preregistration_manifest(
                manifest, observed_at_utc=self.now, current_readback=None
            )

    def test_module_inspection_is_cwd_independent_and_has_no_runtime_io(self):
        source = Path(__file__).resolve().with_name(
            "stock_model_preregistration.py"
        ).read_text(encoding="utf-8").lower()
        for forbidden in (
            "turso", "sqlite", "requests", "urllib", "subprocess", "pymc",
            "fit_hierarchical", "prediction_evidence", "recommendation(", "order(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
