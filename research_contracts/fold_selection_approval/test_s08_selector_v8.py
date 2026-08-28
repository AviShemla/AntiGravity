import dataclasses
import inspect
import math
import unittest
from datetime import date, timedelta

from research_contracts.fold_selection_approval import s08_selector_v8 as m


def fixture():
    excluded = {"FISV", "SNDK"}
    tickers = tuple(
        ticker for ticker in (f"T{index:03d}" for index in range(474))
        if ticker not in excluded
    )
    # Synthetic names above do not include the real exclusions; use a 474-name
    # source family that does, then apply the exact symmetric exclusion.
    source = [f"T{index:03d}" for index in range(472)] + ["FISV", "SNDK"]
    tickers = tuple(sorted(set(source) - excluded))
    dates = tuple(
        (date(2020, 1, 1) + timedelta(days=index)).isoformat()
        for index in range(416)
    )
    values = {
        ticker: [math.sin(index / 3 + (rank % 7)) for index in range(416)]
        for rank, ticker in enumerate(tickers)
    }
    panel = m.build_signal_panel(tickers, dates, values)
    calendar_sha = m._sha(m._cj(list(dates)))
    lineage = m.Lineage(
        dataset_version="ds",
        snapshot_sha256="1" * 64,
        frozen_dataset_sha256="2" * 64,
        frozen_content_sha256="3" * 64,
        readback_sha256="4" * 64,
        calendar_sha256=calendar_sha,
        signal_panel_sha256=panel.sha256,
        eligible_universe_sha256=m._eligible_universe_sha256(tickers),
        presence_mask_sha256="5" * 64,
        exclusion_manifest_sha256=m._sha(m._EXCLUSION_MANIFEST_BYTES),
        preregistration_sha256="6" * 64,
        policy_sha256="7" * 64,
        selector_code_sha256="8" * 64,
        selector_release_sha256="9" * 64,
        dependency_closure_sha256="a" * 64,
        materializer_release_sha256="b" * 64,
        materializer_evidence_sha256="c" * 64,
        independent_review_event_sha256="d" * 64,
    )
    evidence = m.evaluate_candidate(
        outer_fold=1, source_rank=1, source=tickers[1], target_rank=0,
        target=tickers[0], lag=1, panel=panel, lineage=lineage,
    )
    return panel, lineage, evidence


class SelectorV8Tests(unittest.TestCase):
    def test_exact_counts_and_scientific_boundaries(self):
        self.assertEqual(m._PER_FOLD, 1_556_184)
        self.assertEqual(m._TOTAL, 6_224_736)
        self.assertEqual(m._GROUPS, 1_888)
        self.assertEqual(m._OOS_OBSERVATIONS, 56_640)
        contract = m.SCIENTIFIC_CONTRACT_BYTES.decode()
        for required in (
            "S08_NESTED_PREDICTIVE_SELECTION_V8", "FISV", "SNDK",
            "presence-only symmetric complete case", "lags allowed",
            "NO_MULTIPLICITY_CONTROL_NO_FDR_CLAIM", "ZERO model fits",
            "6224736-candidate global closure",
        ):
            self.assertIn(required, contract)
        self.assertNotIn(b'"status":"AUTHORIZED"', m.SCIENTIFIC_CONTRACT_BYTES)

    def test_public_surface_has_no_execution_authorization_or_database_api(self):
        source = inspect.getsource(m)
        self.assertNotIn("s08_selector_v7", source)
        self.assertFalse(any(
            token in name.lower() for name in m.__all__
            for token in ("authoriz", "execute", "database", "predict", "write")
        ))
        self.assertNotIn("import sqlite", source.lower())
        self.assertNotIn("import turso", source.lower())

    def test_panel_and_evidence_replay(self):
        panel, lineage, evidence = fixture()
        m.audit_signal_panel(panel)
        m.audit_evidence(evidence, panel)
        self.assertEqual(evidence.lineage_fingerprint, lineage.fingerprint())

    def test_exhaustive_per_fold_ordinal_bijection(self):
        ordinal = 0
        for target_rank in range(472):
            for source_rank in range(472):
                if source_rank == target_rank:
                    continue
                for lag in range(1, 8):
                    self.assertEqual(m._ord(target_rank, source_rank, lag), ordinal)
                    self.assertEqual(
                        m._coordinates(ordinal),
                        (target_rank, source_rank, lag),
                    )
                    ordinal += 1
        self.assertEqual(ordinal, m._PER_FOLD)

    def test_ordinal_boundaries_and_invalid_coordinates_fail_closed(self):
        self.assertEqual(m._coordinates(0), (0, 1, 1))
        self.assertEqual(m._coordinates(m._PER_FOLD - 1), (471, 470, 7))
        for ordinal in (-1, m._PER_FOLD, True, 1.5):
            with self.assertRaises(m.ContractError):
                m._coordinates(ordinal)
        for values in ((-1, 1, 1), (0, 0, 1), (0, 472, 1), (0, 1, 0), (0, 1, 8)):
            with self.assertRaises(m.ContractError):
                m._ord(*values)

    def test_exact_symmetric_universe_rejects_exclusions_and_wrong_counts(self):
        panel, _, _ = fixture()
        values = dict(zip(panel.tickers, panel.rows))
        for excluded in ("FISV", "SNDK"):
            changed = tuple(sorted(panel.tickers[:-1] + (excluded,)))
            changed_values = {ticker: values.get(ticker, panel.rows[0]) for ticker in changed}
            with self.assertRaisesRegex(m.ContractError, "472-ticker"):
                m.build_signal_panel(changed, panel.session_dates, changed_values)
        with self.assertRaisesRegex(m.ContractError, "472-ticker"):
            m.build_signal_panel(panel.tickers[:-1], panel.session_dates, {
                ticker: values[ticker] for ticker in panel.tickers[:-1]
            })

    def test_eligibility_presence_and_exclusion_hashes_are_required(self):
        panel, lineage, _ = fixture()
        for field in (
            "eligible_universe_sha256", "presence_mask_sha256",
            "exclusion_manifest_sha256",
        ):
            changed = dataclasses.replace(lineage, **{field: "f" * 64})
            if field == "presence_mask_sha256":
                # The selector binds the independently produced mask identity;
                # it cannot reconstruct raw presence rows from a return panel.
                self.assertNotEqual(changed.fingerprint(), lineage.fingerprint())
                continue
            with self.assertRaisesRegex(m.ContractError, "eligibility"):
                m.evaluate_candidate(
                    outer_fold=1, source_rank=1, source=panel.tickers[1],
                    target_rank=0, target=panel.tickers[0], lag=1,
                    panel=panel, lineage=changed,
                )

    def test_presence_identity_changes_replay_identity(self):
        panel, lineage, evidence = fixture()
        changed = dataclasses.replace(lineage, presence_mask_sha256="e" * 64)
        changed_evidence = m.evaluate_candidate(
            outer_fold=1, source_rank=1, source=panel.tickers[1],
            target_rank=0, target=panel.tickers[0], lag=1,
            panel=panel, lineage=changed,
        )
        self.assertNotEqual(evidence.evidence_sha256, changed_evidence.evidence_sha256)
        self.assertNotEqual(evidence.lineage_fingerprint, changed_evidence.lineage_fingerprint)

    def test_panel_disconnect_and_rehash_still_fails(self):
        panel, _, evidence = fixture()
        replay = evidence.replay[0]
        raw = bytearray.fromhex(replay.train_x_hex)
        raw[0] ^= 1
        changed_replay = dataclasses.replace(replay, train_x_hex=raw.hex())
        changed = dataclasses.replace(
            evidence, replay=(changed_replay,) + evidence.replay[1:],
            evidence_sha256="",
        )
        changed = dataclasses.replace(
            changed, evidence_sha256=m._sha(m._cj(changed._payload())),
        )
        with self.assertRaises(m.ContractError):
            m.audit_evidence(changed, panel)

    def test_missing_duplicate_global_stream_never_returns(self):
        panel, _, evidence = fixture()
        with self.assertRaisesRegex(m.ContractError, "incomplete"):
            m.select_complete_run([], panel)
        with self.assertRaisesRegex(m.ContractError, "noncanonical"):
            m.select_complete_run([evidence, evidence], panel)

    def test_wrong_calendar_imputation_domain_and_bool_fail_closed(self):
        panel, _, _ = fixture()
        values = {ticker: list(row) for ticker, row in zip(panel.tickers, panel.rows)}
        with self.assertRaisesRegex(m.ContractError, "416"):
            m.build_signal_panel(
                panel.tickers, panel.session_dates + ("2030-01-01",),
                {ticker: row + [0.0] for ticker, row in values.items()},
            )
        for invalid in (-1.0, -1.01, float("nan"), True):
            changed = {ticker: list(row) for ticker, row in values.items()}
            changed[panel.tickers[0]][0] = invalid
            with self.assertRaisesRegex(m.ContractError, "panel row"):
                m.build_signal_panel(panel.tickers, panel.session_dates, changed)

    def test_terminal_schema_uses_v8_counts_and_requires_source_replay(self):
        panel, lineage, _ = fixture()
        core = {
            "candidate_count": m._TOTAL,
            "group_count": m._GROUPS,
            "selection_count": 0,
            "stream_sha256": "1" * 64,
            "selection_manifest_sha256": m._sha(m._cj([])),
            "panel_sha256": panel.sha256,
            "lineage_fingerprint": lineage.fingerprint(),
            "scientific_contract_sha256": m._sha(m.SCIENTIFIC_CONTRACT_BYTES),
        }
        terminal = m._Terminal(**core, terminal_sha256=m._sha(m._cj(core)))
        result = m.CompleteRunResult(terminal, ())
        with self.assertRaisesRegex(m.ContractError, "incomplete"):
            m.audit_complete_run_result(result, [], panel)


if __name__ == "__main__":
    unittest.main()
