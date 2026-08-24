"""Run evidence-only, DB-backed predictive screening.

This script does not create a stock universe, recommendation, pending order, or
ledger entry. It writes only append-only screening evidence to Turso.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model_input_reader import select_validated_snapshot
from model_lineage import LineageError
from predictive_screener import FeatureSpec, ScreeningConfig, evaluate_ticker
from screening_input_reader import build_return_matrix, build_target_features, load_screening_frame
from screening_evidence_writer import ScreeningEvidenceWriter
from turso_read_pipeline import TursoReadPipeline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-session-date", required=True)
    parser.add_argument("--cutoff-utc", required=True)
    parser.add_argument("--tickers", help="Comma-separated controlled scope; default is all snapshot tickers.")
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--min-depth", type=int, default=3)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--min-train-sessions", type=int, default=504)
    parser.add_argument(
        "--training-window-sessions",
        type=int,
        help="Use only this many trailing sessions in each training fold; omit for expanding history.",
    )
    parser.add_argument("--test-sessions", type=int, default=63)
    parser.add_argument("--outer-folds", type=int, default=4)
    parser.add_argument("--min-oos-sessions", type=int, default=200)
    parser.add_argument("--min-fit-observations", type=int, default=100)
    parser.add_argument(
        "--model-family",
        choices=("selected_chain", "fixed_macro_baseline"),
        default="selected_chain",
        help="Pre-registered evaluation family; both are evidence-only.",
    )
    args = parser.parse_args()
    source_session = date.fromisoformat(args.source_session_date)
    cutoff = datetime.fromisoformat(args.cutoff_utc.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        raise SystemExit("--cutoff-utc must be timezone-aware.")

    load_dotenv(ROOT / ".env")
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise SystemExit("Turso environment variables are unavailable.")
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    reader = TursoReadPipeline(endpoint, token, timeout_seconds=30.0)
    snapshot = select_validated_snapshot(
        reader,
        dataset_type="MARKET_FEATURES",
        source_session_date=source_session,
        cutoff_utc=cutoff,
    )
    print(f"Reading narrow validated Turso screening snapshot {snapshot.snapshot_id}...", flush=True)
    frame = load_screening_frame(reader, snapshot)
    returns = build_return_matrix(frame)
    requested = None
    if args.tickers:
        requested = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
        missing = sorted(set(requested).difference(frame["ticker"].unique()))
        if missing:
            raise SystemExit(f"Requested tickers absent from validated snapshot: {', '.join(missing)}")
    tickers = requested or sorted(frame["ticker"].unique())
    snapshot_id = snapshot.snapshot_id
    if not snapshot_id:
        raise SystemExit("Validated market frame is missing snapshot lineage.")

    config = ScreeningConfig(
        min_train_sessions=args.min_train_sessions,
        training_window_sessions=args.training_window_sessions,
        test_sessions=args.test_sessions,
        outer_folds=args.outer_folds,
        min_oos_sessions=args.min_oos_sessions,
        min_depth=args.min_depth,
        max_depth=args.max_depth,
        min_fit_observations=args.min_fit_observations,
        eligibility_hypotheses=len(tickers),
    )
    config.validate()
    run_id = f"predictive_screening_{source_session.isoformat()}_{uuid.uuid4().hex[:12]}"
    config_payload = {
        **asdict(config),
        "requested_tickers": tickers,
        "model_family": args.model_family,
        "terminology": "predictive_lead_lag_not_causal_identification",
    }
    writer = ScreeningEvidenceWriter(endpoint, token, timeout_seconds=30.0)
    writer.start_run(
        screening_run_id=run_id,
        market_snapshot_id=snapshot_id,
        source_session_date=source_session.isoformat(),
        cutoff_utc=cutoff.isoformat(),
        code_version=args.code_version,
        config_json=json.dumps(config_payload, sort_keys=True, separators=(",", ":")),
    )
    eligible = 0
    try:
        for position, ticker in enumerate(tickers, start=1):
            predictors = build_target_features(frame, ticker, return_index=returns.index)
            fixed_spec = None
            if args.model_family == "fixed_macro_baseline":
                predictors = predictors.copy()
                # The validated stock snapshot intentionally contains no ETF
                # proxy such as SPY.  Use the same-session equal-weight return
                # of the complete validated stock universe, shifted by the
                # design builder before fitting, as the DB-backed market input.
                predictors["MARKET_RETURN"] = returns.mean(axis=1, skipna=True)
                fixed_spec = FeatureSpec(
                    depth=1,
                    lag_tickers=(ticker,),
                    technical_features=(
                        "MARKET_RETURN",
                        "VIX_CLOSE",
                        "TNX_TREND_5D",
                        f"{ticker}_SEC_MOM",
                        f"{ticker}_SEC_REG",
                    ),
                )
            try:
                evaluation = evaluate_ticker(
                    ticker=ticker,
                    returns=returns,
                    technical_features=predictors,
                    config=config,
                    fixed_spec=fixed_spec,
                )
            except LineageError as exc:
                writer.record_rejection(run_id, ticker, f"STATISTICAL_REJECTION: {exc}")
                print(
                    f"screened={position}/{len(tickers)} ticker={ticker} eligible=False "
                    f"reason={exc}",
                    flush=True,
                )
                continue
            writer.record_evaluation(run_id, evaluation)
            eligible += int(evaluation.eligible)
            print(
                f"screened={position}/{len(tickers)} ticker={ticker} eligible={evaluation.eligible} "
                f"accuracy={evaluation.model_metrics.accuracy:.4f} "
                f"brier={evaluation.model_metrics.brier:.4f}",
                flush=True,
            )
        writer.finish_run(
            run_id,
            expected_tickers=len(tickers),
            evidence=(
                f"Evidence-only nested purged walk-forward run completed for {len(tickers)} "
                f"tickers; eligible={eligible}; creates no recommendations or orders."
            ),
        )
    except Exception as exc:
        try:
            writer.fail_run(run_id, f"{type(exc).__name__}: {exc}")
        except Exception:
            pass
        raise
    print(f"VALIDATED_EVIDENCE_ONLY screening_run_id={run_id} tickers={len(tickers)} eligible={eligible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
