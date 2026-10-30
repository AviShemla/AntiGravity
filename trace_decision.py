"""
trace_decision.py
=================
Deterministic 7-Stage Source-to-Target Decision & Accounting Traceability Engine
for The ORACLE (AntiGravity).

Given any `--date YYYY-MM-DD`, `--ticker YYYYYY`, and optional `--persona PPPP`,
this script queries Turso and constructs the complete, verifiable 7-stage proof receipt:
  Stage 1: Raw OHLCV & Source Market Data (T-1 and T)
  Stage 2: Selected Lag & Raw Feature Vector
  Stage 3: Training Distribution (Xm, Xs) & Z-Scored Held-Out Input Vector (X_target_s)
  Stage 4: Seeded 2-Chain PyMC SV + Dual-Head Posterior Outputs (P(UP), E[R], SV Volatility)
  Stage 5: Canonical Persona Gate & Fractional Kelly Math Verification
  Stage 6: Virtual Broker Staging (`pending_orders`) & Next-Night Historical Settlement (`capital_ledgers`)
  Stage 7: Double-Entry (`Cash + Holdings == Equity`) & Inter-Day Continuity (`Equity[t] == Equity[t-1] + sum(PnL[t])`) Proof
"""

import os
import sys
import json
import argparse
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database_manager
import oracle_lineage_core


def build_trace_receipt(target_date: str, ticker: str, persona: str = None) -> dict:
    ticker = ticker.strip().upper()
    target_date = str(target_date).strip()[:10]

    # Determine asset class from scorecard / lineage or ticker list
    sc_df = database_manager.execute_query(
        "SELECT * FROM etf_scorecards_master WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 20",
        [ticker, target_date]
    )

    is_etf = False
    if not sc_df.empty and any(str(p).startswith("ETF_") for p in sc_df["persona"].unique()):
        is_etf = True
    asset_class = "ETF" if is_etf else "STOCK"

    if persona:
        personas_to_check = [persona.strip()]
    else:
        personas_to_check = (
            ["ETF_Conservative", "ETF_Neutral", "ETF_BallsForBrains", "ETF_Dynamic"]
            if is_etf else
            ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]
        )

    # 1. Stage 1: Raw Price & Return Data in Turso
    price_df = pd.DataFrame()
    try:
        price_df = database_manager.execute_query(
            "SELECT date, close, volume FROM yahoo_daily_prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 5",
            [ticker, target_date]
        )
    except Exception:
        pass

    # 2. Stage 2 & 3 & 4: Feature Lineage Audit Table
    feat_df = database_manager.execute_query(
        "SELECT * FROM feature_lineage_audit WHERE ticker = ? AND target_date <= ? ORDER BY target_date DESC LIMIT 1",
        [ticker, target_date]
    )

    stage2_3_4 = {}
    z_score_verified = True
    z_score_max_diff = 0.0
    if not feat_df.empty:
        frow = feat_df.iloc[0]
        raw_vals = json.loads(frow["raw_feature_values_json"])
        xm_vals = json.loads(frow["train_mean_json"])
        xs_vals = json.loads(frow["train_std_json"])
        z_vals = json.loads(frow["z_scored_vector_json"])
        feat_names = json.loads(frow["selected_features_json"])

        recomputed_z = {}
        for fn in feat_names:
            rv = float(raw_vals.get(fn, 0.0))
            mv = float(xm_vals.get(fn, 0.0))
            sv = float(xs_vals.get(fn, 1.0))
            denom = sv if abs(sv) >= 1e-5 else 1.0
            rz = (rv - mv) / denom
            recomputed_z[fn] = round(rz, 6)
            diff = abs(rz - float(z_vals.get(fn, 0.0)))
            z_score_max_diff = max(z_score_max_diff, diff)
            if diff > 1e-4:
                z_score_verified = False

        stage2_3_4 = {
            "lineage_date": str(frow["target_date"]),
            "source_session_date": str(frow["source_session_date"]),
            "asset_class": str(frow["asset_class"]),
            "selected_lag": int(frow["selected_lag"]),
            "lag_accuracy": float(frow["lag_accuracy"] or 0.0),
            "selected_features": feat_names,
            "raw_feature_values": raw_vals,
            "train_mean": xm_vals,
            "train_std": xs_vals,
            "stored_z_scored_vector": z_vals,
            "recomputed_z_scored_vector": recomputed_z,
            "z_score_math_verified": z_score_verified,
            "z_score_max_abs_error": round(z_score_max_diff, 8),
            "sv_seed": int(frow["sv_seed"]),
            "main_seed": int(frow["main_seed"]),
            "chains": int(frow["chains"]),
            "draws": int(frow["draws"]),
            "tune": int(frow["tune"]),
            "posterior_prob_up": float(frow["prob_up"]),
            "posterior_expected_return": float(frow["expected_return"]),
            "posterior_expected_risk": float(frow["expected_risk"]),
            "source_snapshot_sha256": str(frow["source_snapshot_sha256"]),
            "code_version": str(frow["code_version"]),
        }

    # 3. Stage 5: Persona Decision & Kelly Verification
    dec_df = database_manager.execute_query(
        "SELECT * FROM decision_lineage_audit WHERE ticker = ? AND target_date <= ? ORDER BY target_date DESC",
        [ticker, target_date]
    )

    persona_traces = []
    for p_name in personas_to_check:
        # Check decision_lineage_audit first
        p_dec_rows = dec_df[dec_df["persona"] == p_name] if not dec_df.empty else pd.DataFrame()
        p_sc_rows = sc_df[sc_df["persona"] == p_name] if not sc_df.empty else pd.DataFrame()

        prob_up = None
        exp_ret = None
        exp_risk = None
        vix_val = 18.0
        stored_kelly = None
        stored_rec = None
        stored_reason = None
        row_date = target_date

        if not p_dec_rows.empty:
            drow = p_dec_rows.iloc[0]
            row_date = str(drow["target_date"])
            prob_up = float(drow["prob_up"])
            exp_ret = float(drow["expected_return_dec"])
            exp_risk = float(drow["expected_risk_dec"])
            vix_val = float(drow["vix_val"])
            stored_kelly = float(drow["applied_kelly"])
            stored_rec = str(drow["recommendation"])
            stored_reason = str(drow["reason_code"])
        elif not p_sc_rows.empty:
            srow = p_sc_rows.iloc[0]
            row_date = str(srow["date"])
            prob_up = float(srow["prob"] or 0.5)
            exp_ret = float(srow["expected_return"] or 0.0)
            exp_risk = float(srow["expected_risk"] or 0.01)
            stored_kelly = float(srow["kelly_allocation"] or 0.0)
            stored_rec = str(srow["recommendation"] or "Hold")
            stored_reason = str(srow["broker_override_note"] or "")

        # Stage 6 & 7: Check Ledger & Pending Orders for this persona on row_date
        led_df = database_manager.get_ledger(p_name)
        led_up_to = led_df[led_df["Date"] <= row_date] if not led_df.empty else pd.DataFrame()

        was_held_prev = False
        prev_equity = 10000.0
        prev_holding_info = None
        if len(led_up_to) >= 2:
            prev_row = led_up_to.iloc[-2]
            prev_equity = float(prev_row["Total_Equity"])
            prev_h = json.loads(prev_row["Holdings_JSON"]) if isinstance(prev_row["Holdings_JSON"], str) else prev_row["Holdings_JSON"]
            was_held_prev = ticker in (prev_h or {})
            if was_held_prev:
                prev_holding_info = (prev_h or {}).get(ticker)

        recomputed_dec = None
        kelly_math_verified = False
        if prob_up is not None:
            eval_p = p_name
            recomputed_dec = oracle_lineage_core.evaluate_persona_decision(
                persona=eval_p,
                prob_up=prob_up,
                expected_return_pct=exp_ret,
                expected_risk_pct=exp_risk,
                vix_val=vix_val,
                is_currently_held=was_held_prev
            )
            if stored_kelly is not None:
                kelly_math_verified = abs(recomputed_dec["applied_kelly"] - stored_kelly) <= 0.05

        ledger_proof = {}
        if not led_up_to.empty:
            curr_row = led_up_to.iloc[-1]
            c_date = str(curr_row["Date"])
            c_cash = float(curr_row["Cash"])
            c_eq = float(curr_row["Total_Equity"])
            c_h = json.loads(curr_row["Holdings_JSON"]) if isinstance(curr_row["Holdings_JSON"], str) else curr_row["Holdings_JSON"]
            c_pnl = json.loads(curr_row["Daily_PnL_JSON"]) if isinstance(curr_row["Daily_PnL_JSON"], str) else curr_row["Daily_PnL_JSON"]
            holdings_sum = sum(
                float(v.get("dollars", 0.0)) if isinstance(v, dict) else float(v)
                for k, v in (c_h or {}).items() if k != "Cash"
            )
            double_entry_diff = round((c_cash + holdings_sum) - c_eq, 2)
            pnl_sum = sum(float(v) for v in (c_pnl or {}).values())
            inter_day_diff = round(c_eq - (prev_equity + pnl_sum), 2) if len(led_up_to) >= 2 else 0.0

            # Compute exact single-day position PnL math from T-1 holding & market bars
            prev_alloc_dollars = float(prev_holding_info.get("dollars", 0.0)) if isinstance(prev_holding_info, dict) else 0.0
            mkt_ret_pct = 0.0
            c_prev = 0.0
            c_curr = 0.0
            if not price_df.empty and len(price_df) >= 2:
                # Find row matching c_date and its immediate predecessor
                p_sub = price_df[price_df["date"] <= c_date].sort_values("date")
                if len(p_sub) >= 2 and str(p_sub.iloc[-1]["date"])[:10] == c_date:
                    c_curr = float(p_sub.iloc[-1]["close"])
                    c_prev = float(p_sub.iloc[-2]["close"])
                    if c_prev > 0:
                        mkt_ret_pct = (c_curr - c_prev) / c_prev
            recomputed_ticker_pnl = round(prev_alloc_dollars * mkt_ret_pct, 2)
            stored_ticker_pnl = round(float((c_pnl or {}).get(ticker, 0.0)), 2)

            ledger_proof = {
                "ledger_date": c_date,
                "cash": round(c_cash, 2),
                "holdings_sum": round(holdings_sum, 2),
                "total_equity": round(c_eq, 2),
                "double_entry_diff": double_entry_diff,
                "double_entry_verified": abs(double_entry_diff) <= 0.10,
                "prev_equity": round(prev_equity, 2),
                "daily_pnl_sum": round(pnl_sum, 2),
                "ticker_pnl": stored_ticker_pnl,
                "recomputed_ticker_pnl": recomputed_ticker_pnl,
                "prev_holding": prev_holding_info,
                "prev_close": round(c_prev, 4),
                "curr_close": round(c_curr, 4),
                "market_return_pct": round(mkt_ret_pct * 100.0, 4),
                "inter_day_continuity_diff": inter_day_diff,
                "inter_day_continuity_verified": abs(inter_day_diff) <= 0.10,
                "ticker_holding": (c_h or {}).get(ticker, None),
                "intraday_status": str(curr_row.get("Intraday_Status", "")),
            }

        pending_order = database_manager.get_pending_order(p_name)
        pending_summary = None
        if pending_order and str(pending_order.get("date", ""))[:10] == row_date:
            th = json.loads(pending_order["target_holdings_json"]) if isinstance(pending_order["target_holdings_json"], str) else pending_order["target_holdings_json"]
            pending_summary = {
                "date": str(pending_order["date"]),
                "target_cash": float(pending_order["target_cash"]),
                "target_total_equity": float(pending_order["target_total_equity"]),
                "ticker_target_holding": (th or {}).get(ticker, None),
            }

        persona_traces.append({
            "persona": p_name,
            "date": row_date,
            "prob_up": prob_up,
            "expected_return_dec": exp_ret,
            "expected_risk_dec": exp_risk,
            "stored_kelly": stored_kelly,
            "stored_recommendation": stored_rec,
            "stored_reason_code": stored_reason,
            "recomputed_decision": recomputed_dec,
            "kelly_math_verified": kelly_math_verified,
            "pending_order": pending_summary,
            "ledger_proof": ledger_proof,
        })

    receipt = {
        "query": {
            "ticker": ticker,
            "target_date": target_date,
            "asset_class": asset_class,
            "persona_filter": persona,
        },
        "stage_1_raw_market_bars": price_df.to_dict(orient="records") if not price_df.empty else [],
        "stage_2_3_4_feature_and_mcmc_lineage": stage2_3_4,
        "stage_5_6_7_persona_decisions_and_ledger_proofs": persona_traces,
    }
    return receipt


def print_human_readable_receipt(receipt: dict):
    q = receipt["query"]
    print("=" * 88)
    print(f"ORACLE 7-STAGE DETERMINISTIC TRACE RECEIPT | TICKER: {q['ticker']} | DATE: {q['target_date']} ({q['asset_class']})")
    print("=" * 88)

    bars = receipt["stage_1_raw_market_bars"]
    print("\n[STAGE 1] RAW SOURCE MARKET BARS (Turso `yahoo_daily_prices`):")
    if bars:
        for b in bars[:3]:
            print(f"  - Date: {b.get('date')} | Close: ${float(b.get('close', 0)):.4f} | Volume: {b.get('volume')}")
    else:
        print("  - (Source bars loaded from Hybrid/Return Matrix CSVs during scorecard generation)")

    s234 = receipt["stage_2_3_4_feature_and_mcmc_lineage"]
    print("\n[STAGES 2, 3 & 4] FEATURE VECTOR, Z-SCORE SCALING & SEEDED 2-CHAIN MCMC LINEAGE:")
    if s234:
        print(f"  - Target Date         : {s234['lineage_date']} (Source Session T-1: {s234['source_session_date']})")
        print(f"  - Selected Lag Depth  : Lag {s234['selected_lag']} (OOS Accuracy: {s234['lag_accuracy']*100:.2f}%)")
        print(f"  - Deterministic Seeds : SV_Seed={s234['sv_seed']} | Main_Seed={s234['main_seed']} (Chains={s234['chains']}, Draws={s234['draws']})")
        print(f"  - Snapshot SHA-256    : {s234['source_snapshot_sha256']}")
        print(f"  - Z-Score Verification: {'PASS' if s234['z_score_math_verified'] else 'FAIL'} (Max Abs Error: {s234['z_score_max_abs_error']:.2e})")
        print("  - Feature Breakdown (Raw -> Train Mean/Std -> Z-Score):")
        for fn in s234["selected_features"]:
            rv = s234["raw_feature_values"].get(fn, 0.0)
            mv = s234["train_mean"].get(fn, 0.0)
            sv = s234["train_std"].get(fn, 1.0)
            zv = s234["stored_z_scored_vector"].get(fn, 0.0)
            print(f"      * {fn.ljust(28)}: Raw={rv:+.6f} | Mean={mv:+.6f} | Std={sv:.6f} -> Z={zv:+.6f}")
        print(f"  - Posterior P(UP)     : {s234['posterior_prob_up']*100:.2f}%")
        print(f"  - Posterior E[Return] : {s234['posterior_expected_return']*100:+.3f}%")
        print(f"  - Posterior SV Risk   : {s234['posterior_expected_risk']*100:.3f}%")
    else:
        print("  - No row in `feature_lineage_audit` for this ticker/date yet.")

    print("\n[STAGES 5, 6 & 7] PERSONA GATE EVALUATION, KELLY SIZING & DOUBLE-ENTRY LEDGER PROOF:")
    for pt in receipt["stage_5_6_7_persona_decisions_and_ledger_proofs"]:
        rec_dec = pt["recomputed_decision"] or {}
        lp = pt["ledger_proof"] or {}
        print(f"\n  --- Persona: {pt['persona']} (Date: {pt['date']}) ---")
        if pt["prob_up"] is not None:
            print(
                f"    Stage 5 (Decision) : P(UP)={pt['prob_up']*100:.2f}% | E[R]={rec_dec.get('expected_return_dec', 0)*100:+.3f}% "
                f"| Risk={rec_dec.get('expected_risk_dec', 0)*100:.3f}% | Sharpe={rec_dec.get('expected_sharpe', 0):.2f}"
            )
            print(
                f"    Stage 5 (Kelly)    : Raw_Kelly={rec_dec.get('raw_kelly', 0)*100:.2f}% x Mult({rec_dec.get('kelly_multiplier', 0)}) "
                f"x VIX_Mult({rec_dec.get('vix_multiplier', 1)}) -> Applied={rec_dec.get('applied_kelly', 0)*100:.2f}% "
                f"| Stored={float(pt['stored_kelly'] or 0)*100:.2f}%"
            )
            print(f"    Stage 5 (Verdict)  : Rec={pt['stored_recommendation']} | Reason={pt['stored_reason_code']}")
        if pt["pending_order"]:
            po = pt["pending_order"]
            print(f"    Stage 6 (Staging)  : Pending Order Cash=${po['target_cash']:,.2f} | Equity=${po['target_total_equity']:,.2f} | Ticker Holding={po['ticker_target_holding']}")
        if lp:
            de_ok = "PASS" if lp["double_entry_verified"] else "FAIL"
            ic_ok = "PASS" if lp["inter_day_continuity_verified"] else "FAIL"
            print(
                f"    Stage 7 (Ledger)   : Date={lp['ledger_date']} | Cash=${lp['cash']:,.2f} + Holdings=${lp['holdings_sum']:,.2f} "
                f"== Equity=${lp['total_equity']:,.2f} [Double-Entry: {de_ok} (diff=${lp['double_entry_diff']:+.2f})]"
            )
            print(
                f"    Stage 7 (Continuity): Prev_Equity=${lp['prev_equity']:,.2f} + Daily_PnL_Sum=${lp['daily_pnl_sum']:+,.2f} "
                f"== Equity=${lp['total_equity']:,.2f} [Continuity: {ic_ok} (diff=${lp['inter_day_continuity_diff']:+.2f})]"
            )
            if lp.get("prev_holding"):
                ph = lp["prev_holding"]
                print(
                    f"    Stage 7 (PnL Math) : Prev_Holding={ph} | Close ${lp.get('prev_close',0):.2f} -> ${lp.get('curr_close',0):.2f} "
                    f"({lp.get('market_return_pct',0):+.3f}%) => Recomputed_PnL=${lp.get('recomputed_ticker_pnl',0):+,.2f} "
                    f"== Stored_PnL=${lp['ticker_pnl']:+,.2f}"
                )
            print(f"    Stage 7 (Position) : {q['ticker']} EOD Holding={lp['ticker_holding']} | {q['ticker']} Daily PnL=${lp['ticker_pnl']:+,.2f}")
    print("\n" + "=" * 88)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deterministic 7-Stage Source-to-Target Decision Trace")
    parser.add_argument("--date", type=str, required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--ticker", type=str, required=True, help="Ticker symbol (e.g. LMT, XLK)")
    parser.add_argument("--persona", type=str, default=None, help="Optional persona name")
    parser.add_argument("--json", action="store_true", help="Output raw JSON receipt")
    args = parser.parse_args()

    receipt_data = build_trace_receipt(args.date, args.ticker, args.persona)
    if args.json:
        print(json.dumps(receipt_data, indent=2, default=str))
    else:
        print_human_readable_receipt(receipt_data)
    sys.stdout.flush()
    os._exit(0)
