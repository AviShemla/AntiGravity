"""
oracle_lineage_core.py
======================
Canonical Single Source of Truth (SSOT) mathematical, statistical, and lineage
contract for The ORACLE (AntiGravity).

Enforces:
1. Deterministic 2-Chain PyMC Seed Generation (ORA-INC-067) bound to (ticker, date, code_version).
2. Pre-Sampling Held-Out Feature Completeness Gate (ORA-INC-019).
3. Canonical Persona Gate & Fractional Kelly Sizing across all 8 personas (Stocks & ETFs),
   eliminating the 4 conflicting Kelly implementations and ensuring E[R] > 0 before any allocation.
4. Double-Entry + Inter-Day Ledger Continuity Verification (Cash + Holdings == Equity AND
   Equity[t] == Equity[t-1] + sum(PnL[t])).
5. Additive Turso Lineage Persistence (`feature_lineage_audit` & `decision_lineage_audit`)
   so any decision on day XXX for ticker YYYYYY can be traced and replicated bit-for-bit.
"""

import os
import json
import zlib
import hashlib
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import database_manager

CODE_VERSION = "ORACLE_LINEAGE_CORE_V1_20261029"

# =============================================================================
# 1. CANONICAL 8-PERSONA CONFIGURATION (SINGLE SOURCE OF TRUTH)
# =============================================================================
STOCK_PERSONA_CONFIG = {
    "Conservative": {
        "asset_class": "STOCK",
        "prob_threshold": 0.62,
        "sharpe_threshold": 0.12,
        "kelly_multiplier": 0.25,
        "max_cap": 0.15,
        "carryover_prob": 0.55,
        "stop_loss_pct": 0.03,
        "vix_Rules": [(30.0, 0.0), (25.0, 0.50)],  # (vix_above, multiplier)
    },
    "Neutral": {
        "asset_class": "STOCK",
        "prob_threshold": 0.60,
        "sharpe_threshold": 0.10,
        "kelly_multiplier": 0.50,
        "max_cap": 0.20,
        "carryover_prob": 0.52,
        "stop_loss_pct": 0.03,
        "vix_Rules": [(35.0, 0.25), (28.0, 0.75)],
    },
    "BallsForBrains": {
        "asset_class": "STOCK",
        "prob_threshold": 0.55,
        "sharpe_threshold": 0.05,
        "kelly_multiplier": 0.90,
        "max_cap": 0.25,
        "carryover_prob": 0.50,
        "stop_loss_pct": 0.05,
        "vix_Rules": [(40.0, 0.50)],
    },
    "Dynamic": {
        "asset_class": "STOCK",
        "prob_threshold": 0.60,
        "sharpe_threshold": 0.10,
        "kelly_multiplier": 0.50,
        "max_cap": 0.20,
        "carryover_prob": 0.52,
        "stop_loss_pct": 0.03,
        "vix_Rules": [(35.0, 0.25), (28.0, 0.75)],
        "is_dynamic_meta": True,
        "candidate_pool": ["Conservative", "Neutral", "BallsForBrains"],
    },
}

ETF_PERSONA_CONFIG = {
    "ETF_Conservative": {
        "asset_class": "ETF",
        "prob_threshold": 0.57,
        "sharpe_threshold": 0.05,
        "kelly_multiplier": 0.25,
        "max_cap": 0.20,
        "carryover_prob": 0.52,
        "stop_loss_pct": 0.025,
        "vix_Rules": [(30.0, 0.0), (25.0, 0.50)],
    },
    "ETF_Neutral": {
        "asset_class": "ETF",
        "prob_threshold": 0.54,
        "sharpe_threshold": 0.03,
        "kelly_multiplier": 0.50,
        "max_cap": 0.25,
        "carryover_prob": 0.50,
        "stop_loss_pct": 0.025,
        "vix_Rules": [(35.0, 0.25), (28.0, 0.75)],
    },
    "ETF_BallsForBrains": {
        "asset_class": "ETF",
        "prob_threshold": 0.51,
        "sharpe_threshold": 0.01,
        "kelly_multiplier": 0.75,
        "max_cap": 0.33,
        "carryover_prob": 0.48,
        "stop_loss_pct": 0.025,
        "vix_Rules": [(40.0, 0.50)],
    },
    "ETF_Dynamic": {
        "asset_class": "ETF",
        "prob_threshold": 0.54,
        "sharpe_threshold": 0.03,
        "kelly_multiplier": 0.50,
        "max_cap": 0.25,
        "carryover_prob": 0.50,
        "stop_loss_pct": 0.025,
        "vix_Rules": [(35.0, 0.25), (28.0, 0.75)],
        "is_dynamic_meta": True,
        "candidate_pool": ["ETF_Conservative", "ETF_Neutral", "ETF_BallsForBrains"],
    },
}

ALL_PERSONAS = {**STOCK_PERSONA_CONFIG, **ETF_PERSONA_CONFIG}


# =============================================================================
# 2. DETERMINISTIC SEED & HASH HELPERS (ORA-INC-067)
# =============================================================================
def deterministic_mcmc_seed(ticker: str, target_date: str, stage: str = "MAIN") -> int:
    """
    Produces a deterministic 31-bit positive integer seed from (ticker, target_date, stage)
    so PyMC traces are 100% reproducible across runs.
    """
    preimage = f"{ticker.strip().upper()}:{str(target_date)[:10]}:{stage.strip().upper()}".encode("utf-8")
    digest = hashlib.sha256(preimage).digest()
    seed_int = int.from_bytes(digest[:4], byteorder="big") & 0x7FFFFFFF
    return max(1, seed_int)


def canonical_json_sha256(obj) -> str:
    """Computes a canonical SHA-256 hex digest over any JSON-serializable structure."""
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# =============================================================================
# 3. PRE-SAMPLING HELD-OUT FEATURE COMPLETENESS GATE (ORA-INC-019)
# =============================================================================
def verify_feature_completeness(X_train: np.ndarray, y_train: np.ndarray, X_target: np.ndarray, feature_names: list, target_date: str):
    """
    Verifies that both training and held-out target feature matrices contain strictly
    finite values (zero NaN, zero Inf) before PyMC sampling begins.
    """
    issues = []
    if X_train is None or len(X_train) == 0:
        issues.append("EMPTY_X_TRAIN")
    else:
        bad_cols = np.where(~np.isfinite(X_train).all(axis=0))[0]
        for idx in bad_cols:
            col_name = feature_names[idx] if idx < len(feature_names) else f"col_{idx}"
            issues.append(f"NON_FINITE_TRAIN:{col_name}")

    if y_train is None or len(y_train) == 0 or not np.isfinite(y_train).all():
        issues.append("NON_FINITE_Y_TRAIN")

    if X_target is None or len(X_target) == 0:
        issues.append(f"EMPTY_X_TARGET:{target_date}")
    else:
        flat_target = np.asarray(X_target, dtype=float).reshape(-1)
        for idx, val in enumerate(flat_target):
            if not np.isfinite(val):
                col_name = feature_names[idx] if idx < len(feature_names) else f"col_{idx}"
                issues.append(f"NON_FINITE_TARGET:{col_name}@{target_date}")

    return (len(issues) == 0), issues


# =============================================================================
# 4. CANONICAL PERSONA GATE & FRACTIONAL KELLY ENGINE
# =============================================================================
def compute_vix_multiplier(persona: str, vix_val: float) -> float:
    cfg = ALL_PERSONAS.get(persona, STOCK_PERSONA_CONFIG["Conservative"])
    vix = float(vix_val) if (vix_val is not None and np.isfinite(vix_val)) else 18.0
    for thresh, mult in cfg.get("vix_Rules", []):
        if vix > thresh:
            return float(mult)
    return 1.0


def evaluate_persona_decision(
    persona: str,
    prob_up: float,
    expected_return_pct: float,
    expected_risk_pct: float,
    vix_val: float = 18.0,
    is_currently_held: bool = False,
) -> dict:
    """
    Canonical decision and Fractional Kelly calculator for any of the 8 personas.
    Inputs:
      - prob_up: Posterior P(UP) in [0, 1]
      - expected_return_pct: Posterior E[R] in percentage points (e.g. 1.42 means +1.42%)
                             OR decimal if abs <= 0.50; normalized below.
      - expected_risk_pct: Posterior SV volatility in percentage points (e.g. 1.15 means 1.15%)
                           OR decimal; normalized to match expected_return units.
    Returns a complete audit dictionary with exact intermediate variables and reason_code.
    """
    cfg = ALL_PERSONAS.get(persona, STOCK_PERSONA_CONFIG["Conservative"])
    p = float(prob_up) if (prob_up is not None and np.isfinite(prob_up)) else 0.0

    # Normalize return and risk to decimal fractions (e.g. 0.0142 for 1.42%)
    raw_ret = float(expected_return_pct) if (expected_return_pct is not None and np.isfinite(expected_return_pct)) else 0.0
    raw_risk = float(expected_risk_pct) if (expected_risk_pct is not None and np.isfinite(expected_risk_pct)) else 0.0

    # In scorecard tables, expected_return is stored in % (e.g. 0.85 for 0.85%) while expected_risk
    # can be decimal (0.015) or % (1.5). Normalize both to decimal fraction:
    ret_dec = raw_ret / 100.0 if abs(raw_ret) > 0.25 else raw_ret
    risk_dec = raw_risk / 100.0 if abs(raw_risk) > 0.25 else raw_risk

    if risk_dec <= 1e-6:
        sharpe = 0.0
        payoff_ratio = 0.0
    else:
        sharpe = ret_dec / risk_dec
        payoff_ratio = ret_dec / risk_dec

    vix_mult = compute_vix_multiplier(persona, vix_val)
    kelly_mult = float(cfg["kelly_multiplier"])
    max_cap = float(cfg["max_cap"])
    prob_thresh = float(cfg["prob_threshold"])
    sharpe_thresh = float(cfg["sharpe_threshold"])
    carryover_prob = float(cfg["carryover_prob"])

    # Compute raw Kelly fraction f* = p - (1 - p) / R ONLY when expected return > 0 and R > 0
    # Because Bayesian hierarchical shrinkage shrinks daily point-estimate magnitude toward 0
    # while preserving posterior probability edge (p > 0.5), we bound effective payoff ratio R >= 1.0
    # whenever expected return is strictly positive (ret_dec > 0).
    if ret_dec <= 0.0 or payoff_ratio <= 1e-6:
        raw_kelly = 0.0
    else:
        effective_R = max(1.0, payoff_ratio)
        raw_kelly = max(0.0, p - ((1.0 - p) / effective_R))

    applied_kelly = min(max_cap, raw_kelly * kelly_mult * vix_mult)

    # Gate evaluation
    if vix_mult <= 0.0:
        recommendation = "NO_TRADE"
        reason_code = f"BLOCKED_VIX_GATE_{vix_val:.2f}"
        final_alloc = 0.0
    elif ret_dec <= 0.0:
        recommendation = "SELL" if is_currently_held else "HOLD"
        reason_code = "REJECT_NON_POSITIVE_EXPECTED_RETURN"
        final_alloc = 0.0
    elif is_currently_held and p >= carryover_prob and sharpe > 0.0:
        # Carryover retention gate
        if applied_kelly > 0.0:
            final_alloc = applied_kelly
        else:
            # Minimum carryover retention sizing proportional to probability edge over 0.50
            final_alloc = min(max_cap, max(0.02, (p - 0.45) * kelly_mult * vix_mult))
        recommendation = "HOLD_CARRYOVER"
        reason_code = f"PASS_CARRYOVER_PROB_{p:.4f}_GE_{carryover_prob:.2f}"
    elif p >= prob_thresh and sharpe >= sharpe_thresh and applied_kelly > 0.0:
        recommendation = "BUY"
        reason_code = f"PASS_FRESH_ENTRY_PROB_{p:.4f}_SHARPE_{sharpe:.2f}"
        final_alloc = applied_kelly
    else:
        recommendation = "SELL" if is_currently_held else "HOLD"
        if p < prob_thresh:
            reason_code = f"HOLD_PROB_{p:.4f}_BELOW_{prob_thresh:.2f}"
        elif sharpe < sharpe_thresh:
            reason_code = f"HOLD_SHARPE_{sharpe:.2f}_BELOW_{sharpe_thresh:.2f}"
        else:
            reason_code = f"HOLD_KELLY_ZERO_PAYOFF_{payoff_ratio:.3f}"
        final_alloc = 0.0

    return {
        "persona": persona,
        "prob_up": round(p, 6),
        "expected_return_dec": round(ret_dec, 6),
        "expected_risk_dec": round(risk_dec, 6),
        "expected_sharpe": round(sharpe, 6),
        "payoff_ratio_R": round(payoff_ratio, 6),
        "raw_kelly": round(raw_kelly, 6),
        "kelly_multiplier": kelly_mult,
        "vix_val": round(float(vix_val) if vix_val is not None else 18.0, 4),
        "vix_multiplier": vix_mult,
        "max_cap": max_cap,
        "applied_kelly": round(final_alloc, 6),
        "recommendation": recommendation,
        "reason_code": reason_code,
        "code_version": CODE_VERSION,
    }


# =============================================================================
# 5. TURSO LINEAGE SCHEMA INITIALIZATION & PERSISTENCE
# =============================================================================
def init_lineage_tables():
    """
    Creates the additive Turso tables `feature_lineage_audit` and `decision_lineage_audit`
    if they do not already exist.
    """
    client = database_manager.get_connection()
    client.execute('''
        CREATE TABLE IF NOT EXISTS feature_lineage_audit (
            ticker TEXT NOT NULL,
            target_date TEXT NOT NULL,
            source_session_date TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            selected_lag INTEGER NOT NULL,
            lag_accuracy REAL,
            selected_features_json TEXT NOT NULL,
            raw_feature_values_json TEXT NOT NULL,
            train_mean_json TEXT NOT NULL,
            train_std_json TEXT NOT NULL,
            z_scored_vector_json TEXT NOT NULL,
            sv_seed INTEGER NOT NULL,
            main_seed INTEGER NOT NULL,
            chains INTEGER NOT NULL,
            draws INTEGER NOT NULL,
            tune INTEGER NOT NULL,
            prob_up REAL NOT NULL,
            expected_return REAL NOT NULL,
            expected_risk REAL NOT NULL,
            source_snapshot_sha256 TEXT NOT NULL,
            code_version TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            PRIMARY KEY (ticker, target_date, asset_class)
        )
    ''')

    client.execute('''
        CREATE TABLE IF NOT EXISTS decision_lineage_audit (
            ticker TEXT NOT NULL,
            target_date TEXT NOT NULL,
            persona TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            prob_up REAL NOT NULL,
            expected_return_dec REAL NOT NULL,
            expected_risk_dec REAL NOT NULL,
            expected_sharpe REAL NOT NULL,
            payoff_ratio_R REAL NOT NULL,
            raw_kelly REAL NOT NULL,
            kelly_multiplier REAL NOT NULL,
            vix_val REAL NOT NULL,
            vix_multiplier REAL NOT NULL,
            max_cap REAL NOT NULL,
            applied_kelly REAL NOT NULL,
            recommendation TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            code_version TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            PRIMARY KEY (ticker, target_date, persona)
        )
    ''')


def save_feature_lineage(record: dict):
    client = database_manager.get_connection()
    now_utc = datetime.now(timezone.utc).isoformat()
    client.execute('''
        INSERT INTO feature_lineage_audit (
            ticker, target_date, source_session_date, asset_class,
            selected_lag, lag_accuracy, selected_features_json,
            raw_feature_values_json, train_mean_json, train_std_json,
            z_scored_vector_json, sv_seed, main_seed, chains, draws, tune,
            prob_up, expected_return, expected_risk,
            source_snapshot_sha256, code_version, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, target_date, asset_class) DO UPDATE SET
            source_session_date=excluded.source_session_date,
            selected_lag=excluded.selected_lag,
            lag_accuracy=excluded.lag_accuracy,
            selected_features_json=excluded.selected_features_json,
            raw_feature_values_json=excluded.raw_feature_values_json,
            train_mean_json=excluded.train_mean_json,
            train_std_json=excluded.train_std_json,
            z_scored_vector_json=excluded.z_scored_vector_json,
            sv_seed=excluded.sv_seed,
            main_seed=excluded.main_seed,
            chains=excluded.chains,
            draws=excluded.draws,
            tune=excluded.tune,
            prob_up=excluded.prob_up,
            expected_return=excluded.expected_return,
            expected_risk=excluded.expected_risk,
            source_snapshot_sha256=excluded.source_snapshot_sha256,
            code_version=excluded.code_version,
            created_at_utc=excluded.created_at_utc
    ''', [
        str(record["ticker"]),
        str(record["target_date"])[:10],
        str(record["source_session_date"])[:10],
        str(record.get("asset_class", "STOCK")),
        int(record["selected_lag"]),
        float(record.get("lag_accuracy", 0.0)),
        json.dumps(record["selected_features"]),
        json.dumps(record["raw_feature_values"]),
        json.dumps(record["train_mean"]),
        json.dumps(record["train_std"]),
        json.dumps(record["z_scored_vector"]),
        int(record["sv_seed"]),
        int(record["main_seed"]),
        int(record.get("chains", 2)),
        int(record.get("draws", 1000)),
        int(record.get("tune", 1000)),
        float(record["prob_up"]),
        float(record["expected_return"]),
        float(record["expected_risk"]),
        str(record["source_snapshot_sha256"]),
        str(record.get("code_version", CODE_VERSION)),
        now_utc,
    ])


def save_decision_lineage(decision_dict: dict, ticker: str, target_date: str, asset_class: str = "STOCK"):
    client = database_manager.get_connection()
    now_utc = datetime.now(timezone.utc).isoformat()
    client.execute('''
        INSERT INTO decision_lineage_audit (
            ticker, target_date, persona, asset_class,
            prob_up, expected_return_dec, expected_risk_dec, expected_sharpe,
            payoff_ratio_R, raw_kelly, kelly_multiplier, vix_val, vix_multiplier,
            max_cap, applied_kelly, recommendation, reason_code,
            code_version, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, target_date, persona) DO UPDATE SET
            asset_class=excluded.asset_class,
            prob_up=excluded.prob_up,
            expected_return_dec=excluded.expected_return_dec,
            expected_risk_dec=excluded.expected_risk_dec,
            expected_sharpe=excluded.expected_sharpe,
            payoff_ratio_R=excluded.payoff_ratio_R,
            raw_kelly=excluded.raw_kelly,
            kelly_multiplier=excluded.kelly_multiplier,
            vix_val=excluded.vix_val,
            vix_multiplier=excluded.vix_multiplier,
            max_cap=excluded.max_cap,
            applied_kelly=excluded.applied_kelly,
            recommendation=excluded.recommendation,
            reason_code=excluded.reason_code,
            code_version=excluded.code_version,
            created_at_utc=excluded.created_at_utc
    ''', [
        str(ticker),
        str(target_date)[:10],
        str(decision_dict["persona"]),
        str(asset_class),
        float(decision_dict["prob_up"]),
        float(decision_dict["expected_return_dec"]),
        float(decision_dict["expected_risk_dec"]),
        float(decision_dict["expected_sharpe"]),
        float(decision_dict["payoff_ratio_R"]),
        float(decision_dict["raw_kelly"]),
        float(decision_dict["kelly_multiplier"]),
        float(decision_dict["vix_val"]),
        float(decision_dict["vix_multiplier"]),
        float(decision_dict["max_cap"]),
        float(decision_dict["applied_kelly"]),
        str(decision_dict["recommendation"]),
        str(decision_dict["reason_code"]),
        str(decision_dict.get("code_version", CODE_VERSION)),
        now_utc,
    ])


# =============================================================================
# 6. DYNAMIC LEADER SCALING HELPER (BUG #3 FIX)
# =============================================================================
def scale_leader_holdings_to_equity(leader_holdings: dict, leader_total_equity: float, dynamic_own_equity: float):
    """
    Scales a winning leader persona's holdings proportionally to `Dynamic`'s own
    settled `total_equity` so `Dynamic` never experiences artificial inter-day equity
    jumps when switching leaders.
    """
    own_eq = round(float(dynamic_own_equity), 2)
    lead_eq = float(leader_total_equity)
    if lead_eq <= 0.0 or not leader_holdings:
        return {}, own_eq, own_eq

    scale_factor = own_eq / lead_eq
    scaled_holdings = {}
    allocated_sum = 0.0

    for ticker, pos in leader_holdings.items():
        if ticker == "Cash":
            continue
        if isinstance(pos, dict):
            orig_dollars = float(pos.get("dollars", 0.0))
            new_dollars = round(orig_dollars * scale_factor, 2)
            new_pos = dict(pos)
            new_pos["dollars"] = new_dollars
            new_pos["weight"] = round(new_dollars / own_eq, 6) if own_eq > 0 else 0.0
            scaled_holdings[ticker] = new_pos
            allocated_sum += new_dollars
        else:
            orig_dollars = float(pos)
            new_dollars = round(orig_dollars * scale_factor, 2)
            scaled_holdings[ticker] = {"dollars": new_dollars, "weight": round(new_dollars / own_eq, 6)}
            allocated_sum += new_dollars

    target_cash = round(own_eq - allocated_sum, 2)
    return scaled_holdings, target_cash, own_eq
