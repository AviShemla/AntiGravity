import os
import sys
import time
import json
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf
from etf_whale_extractor import get_60_percent_whales
import database_manager

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
DEFAULT_ETFS = ['XLK', 'XLV', 'XLY', 'XLF', 'XLC', 'XLI', 'XLE', 'XLP', 'XLU', 'XLRE', 'XLB']

def calculate_fundamental_score(info):
    """
    Calculates a score between -1.0 (Terrible) and 1.0 (Excellent)
    Based on Profitability, Growth, Debt, and Analyst Consensus.
    """
    score = 0.0

    # 1. Profitability (Net Margin)
    margin = info.get('profitMargins', 0)
    if margin is None:
        margin = 0
    if margin > 0.20:
        score += 0.4
    elif margin > 0.10:
        score += 0.2
    elif margin < 0:
        score -= 0.4

    # 2. Financial Health (Debt to Equity)
    dte = info.get('debtToEquity', 100)
    if dte is None:
        dte = 100
    if dte < 50:
        score += 0.3
    elif dte > 200:
        score -= 0.3

    # 3. Valuation/Growth (Trailing EPS)
    eps = info.get('trailingEps', 0)
    if eps is None:
        eps = 0
    if eps > 5.0:
        score += 0.2
    elif eps > 0:
        score += 0.1
    elif eps < 0:
        score -= 0.2

    # 4. Analyst Consensus (1.0=Strong Buy, 5.0=Strong Sell)
    rec = info.get('recommendationMean')
    if rec is not None:
        if rec <= 2.0:
            score += 0.2
        elif rec >= 3.0:
            score -= 0.2

    # 5. Analyst Upside Potential
    target = info.get('targetMeanPrice')
    price = info.get('currentPrice')
    if target is not None and price is not None and price > 0:
        upside = (target / price) - 1.0
        if upside > 0.20:
            score += 0.3
        elif upside > 0.10:
            score += 0.1
        elif upside < 0:
            score -= 0.3

    return round(max(-1.0, min(1.0, score)), 4)


def extract_fundamentals(only_missing=False):
    print("=== EXTRACTING FUNDAMENTAL DATA (100% TURSO SSOT: sp500_fundamentals_score) ===")
    database_manager.init_db()

    tickers = set()
    # 1. Active Portfolio Chains & Lags from Turso
    try:
        df_apc = database_manager.execute_query("SELECT * FROM active_portfolio_chains")
        if not df_apc.empty:
            for col in df_apc.columns:
                if col == 'ticker' or col.startswith('lag'):
                    for val in df_apc[col].dropna().tolist():
                        v_str = str(val).strip().upper()
                        if v_str and '-' not in v_str and v_str.isalpha():
                            tickers.add(v_str)
    except Exception as e_apc:
        print(f"  [WARNING] Could not read active_portfolio_chains from Turso: {e_apc}")

    # 2. Currently Held Stock Tickers from Turso capital_ledgers
    try:
        df_led = database_manager.execute_query("SELECT holdings_json FROM capital_ledgers WHERE persona NOT LIKE 'ETF_%'")
        if not df_led.empty:
            for h_str in df_led['holdings_json'].tail(20):
                try:
                    h_dict = json.loads(h_str) if isinstance(h_str, str) else {}
                    for tk in h_dict.keys():
                        if tk != 'Cash':
                            tickers.add(str(tk).strip().upper())
                except Exception:
                    pass
    except Exception:
        pass

    # 3. ETF Whales from Dynamic_Target_ETFs.json + Sector ETFs
    etfs_to_scan = list(DEFAULT_ETFS)
    dyn_etf_path = os.path.join(BASE_DIR, 'Dynamic_Target_ETFs.json')
    if os.path.exists(dyn_etf_path):
        try:
            with open(dyn_etf_path, 'r') as f:
                for e in json.load(f):
                    if e not in etfs_to_scan:
                        etfs_to_scan.append(e)
        except Exception:
            pass

    print("Extracting ETF Whales to add to fundamental scan...")
    for etf in etfs_to_scan:
        try:
            whales = get_60_percent_whales(etf)
            if whales:
                tickers.update([str(w).strip().upper() for w in whales if str(w).strip()])
        except Exception:
            pass

    if not tickers:
        tickers.update(['AAPL', 'MSFT', 'NVDA', 'MU', 'TSLA'])

    if only_missing:
        try:
            df_existing = database_manager.execute_query("SELECT ticker FROM sp500_fundamentals_score")
            existing_set = set(df_existing['ticker'].astype(str).str.upper().tolist()) if not df_existing.empty else set()
            tickers = tickers - existing_set
            if not tickers:
                print("All active portfolio & ETF whale tickers already present in Turso `sp500_fundamentals_score`.")
                return
        except Exception:
            pass

    tickers = sorted(list(tickers))
    print(f"Total unique companies to scan into Turso `sp500_fundamentals_score`: {len(tickers)}")

    now_utc = datetime.now(timezone.utc).isoformat()
    upserted = 0

    for i, ticker in enumerate(tickers):
        print(f"[{i+1}/{len(tickers)}] Pulling institutional fundamentals for {ticker}...")
        try:
            t = yf.Ticker(ticker.replace('.', '-'))
            info = t.info or {}
            score = calculate_fundamental_score(info)
            margin = float(info.get('profitMargins') or 0.0)
            dte = float(info.get('debtToEquity') or 0.0)
            eps = float(info.get('trailingEps') or 0.0)
            rec = str(info.get('recommendationMean', 'N/A'))
            target = str(info.get('targetMeanPrice', 'N/A'))
        except Exception as e:
            print(f"  Error pulling {ticker}: {e}")
            score = 0.0
            margin, dte, eps, rec, target = 0.0, 0.0, 0.0, 'N/A', 'N/A'

        database_manager.execute_write(
            """INSERT INTO sp500_fundamentals_score
               (ticker, profit_margin, debt_to_equity, trailing_eps, analyst_rec, analyst_target, fundamental_score, updated_at_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(ticker) DO UPDATE SET
                   profit_margin=excluded.profit_margin,
                   debt_to_equity=excluded.debt_to_equity,
                   trailing_eps=excluded.trailing_eps,
                   analyst_rec=excluded.analyst_rec,
                   analyst_target=excluded.analyst_target,
                   fundamental_score=excluded.fundamental_score,
                   updated_at_utc=excluded.updated_at_utc""",
            [ticker, margin, dte, eps, rec, target, float(score), now_utc]
        )
        upserted += 1
        time.sleep(0.5)

    print(f"\n[TURSO SSOT] Upserted {upserted} rows into Turso `sp500_fundamentals_score`!")


if __name__ == '__main__':
    only_missing_flag = '--only-missing' in sys.argv
    extract_fundamentals(only_missing=only_missing_flag)
    sys.stdout.flush()
    os._exit(0)
