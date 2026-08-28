from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import ast
import hashlib
import json
from pathlib import Path
import unittest

from oracle_research_dataset_serializers import (
    MARKET_DAILY_FEATURE_COLUMNS, MarketDatasetStreamingDigester,
)
from research_contracts.fold_selection_approval import s08_signal_panel_materializer_v2 as v2
from research_contracts.fold_selection_approval.training_fold_selection_approval_v6 import (
    ProposalInputs, build_proposal,
)
from research_contracts.fold_selection_approval.s08_signal_panel_materializer import (
    FrozenMarketBinding, ImportedSerializerBinding, S07SignalBinding,
    TrustedReadbackBinding, binding_artifact_sha256,
    canonical_session_dates_sha256, canonical_ticker_list_sha256,
    trusted_readback_artifact_sha256,
)


def sha_json(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode()).hexdigest()


def fixture():
    sessions = tuple((date(2025, 1, 1) + timedelta(days=index)).isoformat()
                     for index in range(417))
    tickers = tuple(sorted(("FISV", "SNDK", *(f"T{index:03d}" for index in range(472)))))
    rows = []
    for ticker_index, ticker in enumerate(tickers):
        start = 1 if ticker == "FISV" else 59 if ticker == "SNDK" else 0
        for session_index, session in enumerate(sessions[start:], start):
            row = [None] * len(MARKET_DAILY_FEATURE_COLUMNS)
            row[0:3] = ["snapshot-v2", ticker, session]
            price = 50.0 + ticker_index / 1000 + session_index / 100
            for field in ("open_price", "high_price", "low_price", "close_price",
                          "adjusted_close"):
                row[MARKET_DAILY_FEATURE_COLUMNS.index(field)] = price
            rows.append(tuple(row))
    rows = tuple(rows)
    digester = MarketDatasetStreamingDigester(MARKET_DAILY_FEATURE_COLUMNS)
    digester.update_rows(rows)
    content = digester.finalize()
    temporary_market = FrozenMarketBinding(
        dataset_version="dataset-v2", snapshot_id="snapshot-v2",
        content_sha256=content.content_sha256,
        ticker_universe_sha256=content.ticker_universe_sha256,
        row_count=content.row_count, ticker_count=content.ticker_count,
        full_session_dates=sessions,
        full_session_calendar_sha256=canonical_session_dates_sha256(sessions),
        upstream_imputation_count=0, binding_artifact_sha256="0" * 64,
    )
    market = replace(temporary_market,
                     binding_artifact_sha256=binding_artifact_sha256(temporary_market))
    s07 = S07SignalBinding(
        s07_raw_sha256="1" * 64, frozen_content_sha256=content.content_sha256,
        model_session_dates=sessions[1:],
        model_session_dates_sha256=canonical_session_dates_sha256(sessions[1:]),
        tickers=tickers, ticker_list_sha256=canonical_ticker_list_sha256(tickers),
    )
    temporary_readback = TrustedReadbackBinding(
        dataset_version="dataset-v2", snapshot_id="snapshot-v2",
        frozen_content_sha256=content.content_sha256,
        readback_evidence_sha256="0" * 64,
    )
    readback = replace(
        temporary_readback,
        readback_evidence_sha256=trusted_readback_artifact_sha256(temporary_readback),
    )
    serializer = ImportedSerializerBinding(
        serializer_identity="serializer-v2", serializer_release_sha256="2" * 64,
        serializer_source_sha256="3" * 64,
        feature_columns_sha256=sha_json(list(MARKET_DAILY_FEATURE_COLUMNS)),
    )
    return rows, market, s07, readback, serializer


class CompleteCaseMaterializerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.market, cls.s07, cls.readback, cls.serializer = fixture()

    def build(self, rows=None, market=None, s07=None):
        return v2.materialize_complete_case_signal_panel(
            canonical_rows=self.rows if rows is None else rows,
            market_binding=self.market if market is None else market,
            s07_binding=self.s07 if s07 is None else s07,
            trusted_readback=self.readback,
            serializer_binding=self.serializer,
        )

    def test_exact_472_panel_and_zero_boundary(self):
        result = self.build()
        self.assertEqual(result.shape, (472, 416))
        self.assertNotIn("FISV", result.eligible_tickers)
        self.assertNotIn("SNDK", result.eligible_tickers)
        self.assertEqual([(x.ticker, x.observed_session_count)
                          for x in result.complete_case_audit.exclusions],
                         [("FISV", 416), ("SNDK", 358)])
        self.assertEqual(result.panel_sha256, result.panel.sha256)
        self.assertFalse(result.execution_authorized)
        self.assertEqual((result.imputation_count, result.database_writes,
                          result.selections, result.model_runs,
                          result.predictions, result.downstream_outputs),
                         (0, 0, 0, 0, 0, 0))

    def test_presence_evidence_is_byte_identical_to_v6_proposal_input(self):
        result = self.build()
        audit = result.complete_case_audit
        proposal = build_proposal(ProposalInputs(
            upstream_tickers=audit.upstream_tickers,
            presence_mask_bytes=audit.presence_mask_bytes,
            upstream_universe_sha256=audit.upstream_universe_sha256,
            presence_mask_sha256=audit.presence_mask_sha256,
            eligible_universe_sha256=audit.eligible_universe_sha256,
            prior_preregistration_sha256="a" * 64,
        ))
        self.assertEqual(proposal.status, "APPROVAL_REQUIRED")
        self.assertEqual(proposal.selections, ())
        self.assertEqual(
            hashlib.sha256(audit.presence_mask_bytes).hexdigest(),
            audit.presence_mask_sha256,
        )

    def test_price_permutation_cannot_change_eligibility_evidence(self):
        original = self.build()
        adjusted = MARKET_DAILY_FEATURE_COLUMNS.index("adjusted_close")
        changed = []
        for row in self.rows:
            copy = list(row)
            copy[adjusted] = float(copy[adjusted]) * 1.01
            changed.append(tuple(copy))
        changed = tuple(changed)
        digester = MarketDatasetStreamingDigester(MARKET_DAILY_FEATURE_COLUMNS)
        digester.update_rows(changed)
        digest = digester.finalize()
        temporary = replace(
            self.market, content_sha256=digest.content_sha256,
            ticker_universe_sha256=digest.ticker_universe_sha256,
            row_count=digest.row_count, ticker_count=digest.ticker_count,
            binding_artifact_sha256="0" * 64,
        )
        market = replace(temporary, binding_artifact_sha256=binding_artifact_sha256(temporary))
        s07 = replace(self.s07, frozen_content_sha256=digest.content_sha256)
        readback0 = replace(self.readback, frozen_content_sha256=digest.content_sha256,
                            readback_evidence_sha256="0" * 64)
        readback = replace(readback0,
                           readback_evidence_sha256=trusted_readback_artifact_sha256(readback0))
        changed_result = v2.materialize_complete_case_signal_panel(
            canonical_rows=changed, market_binding=market, s07_binding=s07,
            trusted_readback=readback, serializer_binding=self.serializer,
        )
        self.assertEqual(original.presence_mask_sha256,
                         changed_result.presence_mask_sha256)
        self.assertEqual(original.eligible_universe_sha256,
                         changed_result.eligible_universe_sha256)
        self.assertNotEqual(original.panel_sha256, changed_result.panel_sha256)

    def test_one_missing_eligible_row_fails_closed(self):
        rows = tuple(row for row in self.rows
                     if not (row[1] == "T000" and row[2] == self.s07.model_session_dates[0]))
        digester = MarketDatasetStreamingDigester(MARKET_DAILY_FEATURE_COLUMNS)
        digester.update_rows(rows)
        digest = digester.finalize()
        temporary = replace(
            self.market, content_sha256=digest.content_sha256,
            ticker_universe_sha256=digest.ticker_universe_sha256,
            row_count=digest.row_count, ticker_count=digest.ticker_count,
            binding_artifact_sha256="0" * 64,
        )
        market = replace(temporary, binding_artifact_sha256=binding_artifact_sha256(temporary))
        s07 = replace(self.s07, frozen_content_sha256=digest.content_sha256)
        readback0 = replace(self.readback, frozen_content_sha256=digest.content_sha256,
                            readback_evidence_sha256="0" * 64)
        readback = replace(readback0,
                           readback_evidence_sha256=trusted_readback_artifact_sha256(readback0))
        with self.assertRaisesRegex(Exception, "exclusions/counts"):
            v2.materialize_complete_case_signal_panel(
                canonical_rows=rows, market_binding=market, s07_binding=s07,
                trusted_readback=readback, serializer_binding=self.serializer,
            )

    def test_no_io_or_operational_surface(self):
        tree = ast.parse(Path(v2.__file__).read_text(encoding="utf-8"))
        imports = set()
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
        self.assertTrue(imports.isdisjoint({"subprocess", "socket", "requests", "pymc"}))
        self.assertTrue(calls.isdisjoint({"execute", "system", "popen", "write", "unlink"}))


if __name__ == "__main__":
    unittest.main()
