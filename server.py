from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import pandas as pd
import numpy as np
import json
import ast
import os
import datetime
import database_manager

app = FastAPI(title="AntiGravity Backend API")
@app.middleware("http")
async def add_no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')

def calculate_metrics(df, persona):
    if 'Total_Equity' in df.columns:
        eq_col = 'Total_Equity'
        pct_returns = df['Total_Equity'].pct_change().dropna()
    else:
        eq_col = f'{persona}_Total_Equity'
        if f'{persona}_Daily_Profit_%' in df.columns:
            pct_returns = df[f'{persona}_Daily_Profit_%'].dropna() / 100
        else:
            pct_returns = pd.Series(dtype=float)
            
    if eq_col not in df.columns or df.empty:
        return 0, 0, 0, 0
        
    equity = df[eq_col].dropna()
    if len(equity) > 0:
        roll_max = equity.cummax()
        drawdown = (equity - roll_max) / roll_max
        max_dd = drawdown.min() * 100
        total_return = ((equity.iloc[-1] - 10000.0) / 10000.0) * 100
    else:
        max_dd, total_return = 0, 0
        
    if len(pct_returns) > 1 and pct_returns.std() > 0:
        sharpe = (pct_returns.mean() / pct_returns.std()) * np.sqrt(252)
    else:
        sharpe = 0
        
    active_days = pct_returns[pct_returns != 0]
    if len(active_days) > 0:
        win_rate = (len(active_days[active_days > 0]) / len(active_days)) * 100
    else:
        win_rate = 0
        
    def clean(v):
        try:
            f = float(v)
            if np.isnan(f) or np.isinf(f): return 0.0
            return f
        except: return 0.0
        
    return clean(max_dd), clean(sharpe), clean(win_rate), clean(total_return)

def format_df_for_display(df_in):
    d = df_in.copy()
    if isinstance(d.index, pd.DatetimeIndex):
        d.index = d.index.strftime('%Y-%m-%d')
        
    d = d.fillna(0)
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime('%Y-%m-%d')
        elif d[c].dtype == object or pd.api.types.is_string_dtype(d[c]):
            d[c] = d[c].astype(str).str.replace(' 00:00:00', '')
        elif 'Total_Equity' in c or 'Loss' in c or 'Cash' in c or 'PnL' in c or 'Profit' in c or 'diff' in c or 'value' in c or 'Liquidity' in c or 'Stability' in c or 'VIP' in c or 'Capital' in c:
            d[c] = d[c].apply(lambda x: f"${float(x):,.2f}" if pd.notnull(x) and not isinstance(x, str) else x)
        elif 'Return' in c or 'Probability' in c or '%' in c or 'Win Rate' in c or 'Drawdown' in c or 'Risk' in c:
            d[c] = d[c].apply(lambda x: f"{float(x):.2%}" if pd.notnull(x) and not isinstance(x, str) else x)
        elif d[c].dtype == bool or 'SV Engine' in c:
            d[c] = d[c].apply(lambda x: 'CHECKBOX_TRUE' if x in [True, 'true', 'True', 1, '1'] else 'CHECKBOX_FALSE')
    return d

def get_recent_trades(df, persona, limit=5):
    h_col = 'Holdings_JSON' if 'Holdings_JSON' in df.columns else f'{persona}_Holdings'
    if h_col not in df.columns or len(df) < 2:
        return []
    
    raw_trades = []
    recent_df = df.dropna(subset=[h_col]).tail(limit + 1)
    if len(recent_df) < 2:
        return []
        
    dates = recent_df['Date'].tolist()
    holdings_raw = recent_df[h_col].tolist()
    
    parsed_holdings = []
    for h in holdings_raw:
        try:
            parsed_holdings.append(ast.literal_eval(h))
        except:
            try:
                parsed_holdings.append(json.loads(h))
            except:
                parsed_holdings.append({})
                
    for i in range(1, len(parsed_holdings)):
        prev = parsed_holdings[i-1]
        curr = parsed_holdings[i]
        date_str = pd.to_datetime(dates[i]).strftime('%b %d')
        
        all_assets = set(prev.keys()).union(set(curr.keys()))
        all_assets.discard('Cash')
        
        for asset in all_assets:
            p_val = prev.get(asset, 0)
            c_val = curr.get(asset, 0)
            if isinstance(p_val, dict): p_val = p_val.get('dollars', 0)
            if isinstance(c_val, dict): c_val = c_val.get('dollars', 0)
            
            p_val = float(p_val)
            c_val = float(c_val)
            
            diff = c_val - p_val
            if diff > 100 or diff < -100:
                raw_trades.append({
                    'asset': asset,
                    'date_obj': pd.to_datetime(dates[i]),
                    'date_str': date_str,
                    'diff': diff
                })
                
    raw_trades.sort(key=lambda x: (x['asset'], x['date_obj']))
    
    trades = []
    for rt in raw_trades:
        if rt['diff'] > 100:
            trades.append(f"[{rt['date_str']}] 🟩 BOUGHT {rt['asset']} (${rt['diff']:,.0f})")
        else:
            trades.append(f"[{rt['date_str']}] 🟥 SOLD {rt['asset']} (${abs(rt['diff']):,.0f})")
            
    return trades[:limit]

def get_asset_breakdown(df, active_holdings):
    if df.empty:
        return []
    
    stats = {}
    for _, row in df.iterrows():
        try:
            pnl_dict = ast.literal_eval(str(row['Daily_PnL_JSON']))
        except:
            try:
                pnl_dict = json.loads(str(row['Daily_PnL_JSON']))
            except:
                pnl_dict = {}
                
        for asset, pnl in pnl_dict.items():
            if asset == 'Cash': continue
            if asset not in stats:
                stats[asset] = {'Total Realized PnL ($)': 0.0, 'Trades Executed': 0, 'Wins': 0}
            
            pnl_val = float(pnl) if not isinstance(pnl, dict) else float(pnl.get('dollars', 0.0))
            if pnl_val == 0.0:
                pnl_val = 0.0
            stats[asset]['Total Realized PnL ($)'] += pnl_val
            stats[asset]['Trades Executed'] += 1
            if pnl_val > 0:
                stats[asset]['Wins'] += 1
                
    for asset in active_holdings:
        if asset != 'Cash' and asset not in stats:
            stats[asset] = {'Total Realized PnL ($)': 0.0, 'Trades Executed': 0, 'Wins': 0}
        
    res = []
    for asset, data in stats.items():
        win_rate = (data['Wins'] / data['Trades Executed']) * 100 if data['Trades Executed'] > 0 else 0
        holding_val = active_holdings.get(asset, 0.0)
        if isinstance(holding_val, dict):
            deployed_cap = holding_val.get('dollars', 0.0)
        else:
            try:
                deployed_cap = float(holding_val)
            except:
                deployed_cap = 0.0
                
        currently_holding = "Yes" if deployed_cap > 1.0 else "No"
                
        res.append({
            'Asset': asset,
            'Total Realized PnL ($)': round(data['Total Realized PnL ($)'], 2),
            'Deployed Capital ($)': round(deployed_cap, 2),
            'Closed Trades': data['Trades Executed'],
            'Win Rate': f"{win_rate:.1f}%",
            'Currently Holding': currently_holding
        })
        
    if not res:
        return []
        
    res.sort(key=lambda x: x['Total Realized PnL ($)'], reverse=True)
    
    total_pnl = sum(r['Total Realized PnL ($)'] for r in res)
    total_trades = sum(r['Closed Trades'] for r in res)
    total_wins = sum(data['Wins'] for data in stats.values())
    total_win_rate = (total_wins / total_trades) * 100 if total_trades > 0 else 0
    
    res.append({
        'Asset': 'TOTAL PnL',
        'Total Realized PnL ($)': round(total_pnl, 2),
        'Deployed Capital ($)': '',
        'Closed Trades': total_trades,
        'Win Rate': f"{total_win_rate:.1f}%",
        'Currently Holding': ''
    })
    return res

@app.get("/api/holdings")
def get_holdings(persona: str = "BallsForBrains", mode: str = "Single"):
    clean_p = persona.replace(" ", "").replace("_", "")
    if clean_p.lower().startswith("etf"):
        clean_p = clean_p[3:]
        
    if clean_p.lower() in ["ballsforbrain", "ballsforbrains"]:
        base_persona = "BallsForBrains"
    else:
        base_persona = clean_p.capitalize()
        
    if mode == "Single":
        p_name = base_persona
    else:
        p_name = f"ETF_{base_persona}"
            
    df = database_manager.get_ledger(p_name)
    if df.empty:
        raise HTTPException(status_code=404, detail="Ledger not found")
    if df.empty:
        raise HTTPException(status_code=404, detail="Ledger is empty")
        
    last_row = df.iloc[-1]
    cash = float(last_row['Cash'])
    total_eq = float(last_row['Total_Equity'])
    holdings = json.loads(last_row['Holdings_JSON'])
    
    is_pending = False
    try:
        pending = database_manager.get_pending_order(p_name)
        if pending and pending.get('date')[:10] >= str(last_row['Date'])[:10]:
            cash = float(pending['target_cash'])
            target_holdings = json.loads(pending['target_holdings_json'])
            
            # Compare target_holdings with last_row['Holdings_JSON'] to see if trades are actually pending
            last_holdings = json.loads(last_row['Holdings_JSON'])
            
            has_changes = False
            if abs(cash - float(last_row['Cash'])) > 1.0:
                has_changes = True
            else:
                for t, d in target_holdings.items():
                    target_val = float(d.get('dollars', 0.0)) if isinstance(d, dict) else float(d)
                    last_val = last_holdings.get(t, 0.0)
                    last_val = float(last_val.get('dollars', 0.0)) if isinstance(last_val, dict) else float(last_val)
                    if abs(target_val - last_val) > 1.0:
                        has_changes = True
                        break
                        
                if not has_changes:
                    for t, d in last_holdings.items():
                        if t == 'Cash': continue
                        last_val = float(d.get('dollars', 0.0)) if isinstance(d, dict) else float(d)
                        target_val = target_holdings.get(t, 0.0)
                        target_val = float(target_val.get('dollars', 0.0)) if isinstance(target_val, dict) else float(target_val)
                        if abs(target_val - last_val) > 1.0:
                            has_changes = True
                            break
                        
                if not has_changes:
                    for t, d in last_holdings.items():
                        if t == 'Cash': continue
                        last_val = float(d.get('dollars', 0.0)) if isinstance(d, dict) else float(d)
                        target_val = target_holdings.get(t, 0.0)
                        target_val = float(target_val.get('dollars', 0.0)) if isinstance(target_val, dict) else float(target_val)
                        if abs(target_val - last_val) > 1.0:
                            has_changes = True
                            break
            
            holdings = target_holdings
            
            if has_changes:
                is_pending = "PRE-MARKET (PENDING)"
            else:
                is_pending = "Only HOLD for today"
    except Exception as e:
        print(f"Error fetching pending orders: {e}")
    
    allocations = {'Cash': cash}
    for ticker, data in holdings.items():
        if isinstance(data, dict):
            allocations[ticker] = float(data.get('dollars', 0.0))
        else:
            allocations[ticker] = float(data)
            
    labels = list(allocations.keys())
    values = list(allocations.values())
    
    max_dd, sharpe, win_rate, total_return = calculate_metrics(df, persona)
    
    # Calculate Equity Curve
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date').reindex(pd.date_range(start=df['Date'].min(), end=max(df['Date'].max(), pd.Timestamp.now().normalize() - pd.offsets.BDay(1)), freq='B')).ffill().reset_index().rename(columns={'index': 'Date'})
    dates = df['Date'].dt.strftime('%Y-%m-%d').tolist()
    equity_curve = df['Total_Equity'].tolist()
    
    # Get Asset Breakdown Table
    breakdown = get_asset_breakdown(df, holdings)
            
    return {
        "total_equity": total_eq,
        "total_return": total_return,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "allocations": allocations,
        "chart_data": {
            "labels": labels,
            "values": values
        },
        "equity_curve": {
            "dates": dates,
            "equity": equity_curve
        },
        "breakdown": breakdown,
        "is_pending": is_pending
    }

@app.get("/api/race")
def get_race_data(mode: str = "Single"):
    all_ledgers = []
    import yfinance as yf
    
    for p in ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]:
        p_name = p if mode == "Single" else f"ETF_{p}"
        df_p = database_manager.get_ledger(p_name)
        if not df_p.empty:
            date_col = 'date' if 'date' in df_p.columns else 'Date'
            eq_col = 'total_equity' if 'total_equity' in df_p.columns else ('Total_Equity' if 'Total_Equity' in df_p.columns else f'{p}_Total_Equity')
            if date_col in df_p.columns and eq_col in df_p.columns:
                df_p['Date'] = pd.to_datetime(df_p[date_col])
                df_p = df_p[['Date', eq_col]].rename(columns={eq_col: p})
                all_ledgers.append(df_p.set_index('Date'))
                
    if not all_ledgers:
        raise HTTPException(status_code=404, detail="No ledger data available")
        
    plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()
    plot_df.index = pd.to_datetime(plot_df.index)
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=35)
    plot_df = plot_df[plot_df.index >= cutoff]
    
    series_data = {}
    for col in plot_df.columns:
        series_data[col] = {
            "dates": plot_df.index.strftime('%Y-%m-%d').tolist(),
            "values": plot_df[col].replace({np.nan: None}).tolist()
        }
        
    try:
        min_date_str = plot_df.index.min().strftime('%Y-%m-%d')
        import yfinance as yf
        yf_df = yf.download('SPY', start=min_date_str, progress=False)
        if not yf_df.empty:
            c_col = ('Close', 'SPY') if isinstance(yf_df.columns, pd.MultiIndex) else 'Close'
            spy_close = yf_df[c_col]
            start_val = float(spy_close.dropna().iloc[0])
            if start_val > 0:
                norm_spy = (spy_close / start_val) * 10000.0
                norm_spy = norm_spy.reindex(plot_df.index).ffill().bfill()
                series_data["S&P 500 (SPY)"] = {
                    "dates": norm_spy.index.strftime('%Y-%m-%d').tolist(),
                    "values": [round(float(v), 2) if v is not None and not np.isnan(v) else None for v in norm_spy.tolist()]
                }
    except Exception as e:
        print(f"[RACE] SPY Benchmark error: {e}")
        
    return series_data

@app.get("/api/dropdown")
def get_dropdown_options(persona: str = "BallsForBrains", mode: str = "Single"):
    options = ["Portfolio Overview"]
    # SOURCE OF TRUTH: Turso DB etf_scorecards_master
    try:
        p_name = persona if mode == "Single" else f"ETF_{persona}"
        df_tickers = database_manager.execute_query(
            "SELECT DISTINCT ticker FROM etf_scorecards_master WHERE persona=? ORDER BY ticker",
            [p_name]
        )
        if not df_tickers.empty:
            options.extend(df_tickers['ticker'].tolist())
    except:
        pass
            
    p_name = persona if mode == "Single" else f"ETF_{persona}"
    try:
        df = database_manager.get_ledger(p_name)
        if not df.empty:
            breakdown = get_asset_breakdown(df)
            for item in breakdown:
                asset = item['Asset']
                if asset not in ['TOTAL PnL', 'AVAILABLE CASH', 'CURRENT EQUITY'] and asset not in options:
                    options.append(asset)
    except:
        pass
            
    return options

@app.get("/api/bayesian")
def get_bayesian_data(ticker: str, persona: str = "BallsForBrains", mode: str = "Single"):
    # SOURCE OF TRUTH: Turso DB etf_scorecards_master (with column-safe fallbacks)
    try:
        p_name = persona if mode == "Single" else f"ETF_{persona}"

        # Use only guaranteed-base columns in SELECT to avoid schema mismatch errors
        df = database_manager.execute_query("""
            SELECT date, prob, score,
                   expected_return, expected_risk, kelly_allocation,
                   actual_return, recommendation, broker_override_note,
                   retraining_status, sv_engine_used, predicted_direction,
                   actual_direction, model_hit
            FROM etf_scorecards_master
            WHERE ticker=? AND persona=?
            ORDER BY date ASC
        """, [ticker, p_name])

        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No scorecard data in DB for {ticker}/{p_name}")

        latest = df.iloc[-1]

        # Use .get() with safe fallbacks — handles missing columns gracefully
        import math
        
        def safe_float(v, default=0.0):
            try:
                fv = float(v)
                return default if math.isnan(fv) else fv
            except:
                return default

        mu = safe_float(latest.get('expected_return') or latest.get('score'))
        sigma = safe_float(latest.get('expected_risk'), 0.01)
        if sigma == 0:
            sigma = 0.01
        exp_sharpe = mu / sigma

        # Historical chart data
        history = []
        try:
            df_hist = df[['date', 'expected_return', 'actual_return']].copy()
            df_hist = df_hist.dropna(subset=['actual_return'])
            df_hist = df_hist.rename(columns={
                'expected_return': 'Expected Return %',
                'actual_return': 'Actual Daily Return %',
                'date': 'Date'
            })
            df_hist = df_hist.fillna(0.0)
            history = df_hist.to_dict('records')
        except Exception:
            pass

        # AI Ledger — only include columns that actually exist in df
        ai_col_map = {
            'date': 'Date', 'prob': 'P(UP)', 'expected_return': 'Exp. Return',
            'expected_risk': 'Exp. Risk', 'kelly_allocation': 'Kelly',
            'recommendation': 'Rec', 'broker_override_note': 'Override Note',
            'retraining_status': 'Status'
        }
        avail_ai = {k: v for k, v in ai_col_map.items() if k in df.columns}
        df_ai = df[list(avail_ai.keys())].tail(30).iloc[::-1].fillna("").rename(columns=avail_ai)
        ai_ledger = df_ai.to_dict('records')

        # Broker Trial Ledger
        broker_ledger = []
        recent_log = []
        try:
            df_trial = database_manager.get_ledger(p_name)
            if not df_trial.empty:
                p_cols = ['Date', 'Total_Equity', 'Cash', 'Daily_PnL_JSON', 'Holdings_JSON', 'Intraday_Status']
                avail_cols = [c for c in p_cols if c in df_trial.columns]
                broker_ledger = format_df_for_display(df_trial[avail_cols].iloc[::-1]).fillna("").to_dict('records')
                recent_trades = get_recent_trades(df_trial, p_name)
                if recent_trades:
                    recent_log = recent_trades
        except Exception:
            pass

        # Race PnL
        race_pnl = {"Conservative": {"dates": [], "values": []}, "Neutral": {"dates": [], "values": []}, "BallsForBrains": {"dates": [], "values": []}}
        for p in ["Conservative", "Neutral", "BallsForBrains"]:
            p_ledger_name = p if mode == "Single" else f"ETF_{p}"
            try:
                df_p = database_manager.get_ledger(p_ledger_name)
                if not df_p.empty and 'Date' in df_p.columns and 'Daily_PnL_JSON' in df_p.columns:
                    df_p['Date'] = pd.to_datetime(df_p['Date'])
                    df_p = df_p[df_p['Date'] >= (pd.Timestamp.now() - pd.Timedelta(days=35))]
                    vals = []
                    for _, row in df_p.iterrows():
                        v = 0.0
                        try:
                            j = json.loads(row['Daily_PnL_JSON'])
                            v = float(j.get(ticker, 0.0))
                        except Exception:
                            pass
                        vals.append(v)
                    cum_vals = pd.Series(vals).cumsum()
                    race_pnl[p]["dates"] = df_p['Date'].dt.strftime('%Y-%m-%d').tolist()
                    race_pnl[p]["values"] = cum_vals.tolist()
            except Exception:
                pass

        return {
            "recommendation": str(latest.get('recommendation') or 'N/A'),
            "probability_up": safe_float(latest.get('prob')),
            "expected_return": mu,
            "expected_risk": sigma,
            "expected_sharpe": exp_sharpe,
            "kelly_allocation": safe_float(latest.get('kelly_allocation')),
            "broker_note": str(latest.get('broker_override_note') or ''),
            "history": history,
            "ai_ledger": ai_ledger,
            "broker_ledger": broker_ledger,
            "recent_log": recent_log,
            "race_pnl": race_pnl
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/api/olympic")

def get_olympic_data():
    try:
        df_db = database_manager.execute_query("SELECT date as Date, model_name, total_equity FROM olympic_shootout_master ORDER BY date ASC")
        if not df_db.empty:
            df_merged = df_db.pivot(index='Date', columns='model_name', values='total_equity').reset_index()
        else:
            merged_path = os.path.join(BASE_DIR, 'financial_data', 'Olympic_Shootout_Results_MASTER.csv')
            if not os.path.exists(merged_path):
                merged_path = os.path.join(BASE_DIR, 'Olympic_Shootout_Results_MASTER.csv')
            df_merged = pd.read_csv(merged_path)

        df_merged['Date'] = pd.to_datetime(df_merged['Date']).dt.strftime('%Y-%m-%d')
        
        final_eq = df_merged.iloc[-1][['EL_CAP (70% Liquidity)', 'EL_VOLTI (70% Stability)', 'CHAMPION (Live VIP)']]
        ranks = final_eq.rank(method='min', ascending=False).to_dict()
        
        def calc_o_metrics(df, col):
            eq = df[col].values
            ret = (eq[-1] - eq[0]) / eq[0] * 100
            peak = pd.Series(eq).cummax()
            dd = (pd.Series(eq) - peak) / peak * 100
            return float(ret), float(dd.min())
            
        r_c, d_c = calc_o_metrics(df_merged, 'EL_CAP (70% Liquidity)')
        r_v, d_v = calc_o_metrics(df_merged, 'EL_VOLTI (70% Stability)')
        r_ch, d_ch = calc_o_metrics(df_merged, 'CHAMPION (Live VIP)')
        
        is_pending = False
        try:
            df_trial = database_manager.get_ledger('BallsForBrains')
            pending = database_manager.get_pending_order('BallsForBrains')
            if pending and not df_trial.empty and pending.get('date')[:10] >= str(df_trial.iloc[-1]['Date'])[:10]:
                target_holdings = json.loads(pending['target_holdings_json'])
                last_row = df_trial.iloc[-1]
                cash = float(pending['target_cash'])
                last_holdings = json.loads(last_row['Holdings_JSON'])
                
                has_changes = False
                if abs(cash - float(last_row['Cash'])) > 1.0:
                    has_changes = True
                else:
                    for t, d in target_holdings.items():
                        target_val = float(d.get('dollars', 0.0)) if isinstance(d, dict) else float(d)
                        last_val = last_holdings.get(t, 0.0)
                        last_val = float(last_val.get('dollars', 0.0)) if isinstance(last_val, dict) else float(last_val)
                        if abs(target_val - last_val) > 1.0:
                            has_changes = True
                            break
                            
                    if not has_changes:
                        for t, d in last_holdings.items():
                            if t == 'Cash': continue
                            last_val = float(d.get('dollars', 0.0)) if isinstance(d, dict) else float(d)
                            target_val = target_holdings.get(t, 0.0)
                            target_val = float(target_val.get('dollars', 0.0)) if isinstance(target_val, dict) else float(target_val)
                            if abs(target_val - last_val) > 1.0:
                                has_changes = True
                                break
                            
                if has_changes:
                    is_pending = "PRE-MARKET (PENDING)"
                else:
                    is_pending = "Only HOLD for today"
        except:
            pass
        
        def safe_int_rank(val):
            return int(val) if pd.notnull(val) and not np.isnan(val) else 0

        def safe_float(val):
            return float(val) if pd.notnull(val) and not np.isnan(val) else 0.0

        metrics = {
            "EL_CAP": {"return": safe_float(r_c), "dd": safe_float(d_c), "rank": safe_int_rank(ranks.get('EL_CAP (70% Liquidity)', 0))},
            "EL_VOLTI": {"return": safe_float(r_v), "dd": safe_float(d_v), "rank": safe_int_rank(ranks.get('EL_VOLTI (70% Stability)', 0))},
            "CHAMPION": {"return": safe_float(r_ch), "dd": safe_float(d_ch), "rank": safe_int_rank(ranks.get('CHAMPION (Live VIP)', 0))}
        }
        
        table_data = format_df_for_display(df_merged.iloc[::-1]).fillna("").to_dict('records')
        
        # Fetch S&P 500 (SPY) benchmark starting at $10,000 for Olympic chart
        spy_olympic = [10000.0] * len(df_merged)
        try:
            min_date_str = str(df_merged['Date'].min())[:10]
            import yfinance as yf
            yf_df = yf.download('SPY', start=min_date_str, progress=False)
            if not yf_df.empty:
                c_col = ('Close', 'SPY') if isinstance(yf_df.columns, pd.MultiIndex) else 'Close'
                yf_series = yf_df[c_col]
                yf_map = dict(zip(yf_series.index.strftime('%Y-%m-%d'), yf_series.values))
                spy_close = df_merged['Date'].str[:10].map(yf_map).ffill().bfill()
                first_spy_val = float(spy_close.dropna().iloc[0])
                if first_spy_val > 0:
                    spy_olympic = [round(float((v / first_spy_val) * 10000.0), 2) if pd.notnull(v) else 10000.0 for v in spy_close]
        except Exception as e_spy:
            print(f"[OLYMPIC] SPY benchmark error: {e_spy}")

        chart_data = {
            "dates": df_merged['Date'].fillna("").tolist(),
            "EL_CAP": df_merged['EL_CAP (70% Liquidity)'].fillna(0).tolist(),
            "EL_VOLTI": df_merged['EL_VOLTI (70% Stability)'].fillna(0).tolist(),
            "CHAMPION": df_merged['CHAMPION (Live VIP)'].fillna(0).tolist(),
            "SPY": spy_olympic
        }
        
        now = datetime.datetime.now()
        expected_finish = now.replace(hour=1, minute=0, second=0, microsecond=0)
        if expected_finish <= now:
            expected_finish += datetime.timedelta(days=1)
            
        return {
            "metrics": metrics,
            "chart_data": chart_data,
            "table_data": table_data,
            "eta_timestamp": expected_finish.isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/autopsy")
def get_autopsy_data():
    def process_ledger(persona_id):
        df = database_manager.get_ledger(persona_id)
        if df.empty:
            return {"serial_offenders": [], "day_vulnerability": [], "forensic_ledger": []}
        if df.empty or 'Daily_PnL_JSON' not in df.columns or 'Date' not in df.columns:
            return {"serial_offenders": [], "day_vulnerability": [], "forensic_ledger": []}
            
        df['Date'] = pd.to_datetime(df['Date'])
        losses = []
        for idx, row in df.iterrows():
            try:
                pnl = json.loads(row['Daily_PnL_JSON'])
                for ticker, profit in pnl.items():
                    if float(profit) < 0:
                        losses.append({
                            "Date": row['Date'].strftime('%Y-%m-%d'),
                            "DayOfWeek": row['Date'].strftime('%A'),
                            "Ticker": ticker,
                            "Loss_Amount": float(profit)
                        })
            except:
                pass
                
        df_loss = pd.DataFrame(losses)
        if df_loss.empty:
            return {"serial_offenders": [], "day_vulnerability": [], "forensic_ledger": []}
            
        offenders = df_loss.groupby('Ticker')['Loss_Amount'].sum().sort_values().head(10)
        serial = [{"Ticker": k, "Loss": float(v)} for k, v in offenders.items()]
        
        day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        day_vuln = df_loss.groupby('DayOfWeek')['Loss_Amount'].sum().reindex(day_order).fillna(0)
        days = [{"Day": k, "Loss": float(v)} for k, v in day_vuln.items()]
        
        # We skip the complex cross-reference for brevity, just returning the core ledger
        df_loss['Loss_Amount'] = df_loss['Loss_Amount'].apply(lambda x: f"${x:,.2f}")
        df_loss = df_loss.sort_values('Date', ascending=False)
        ledger = df_loss.to_dict('records')
        
        return {
            "serial_offenders": serial,
            "day_vulnerability": days,
            "forensic_ledger": ledger
        }

    try:
        stock_data = process_ledger("BallsForBrains")
        etf_data = process_ledger("ETF_BallsForBrains")
        
        return {
            "stock": stock_data,
            "etf": etf_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/api/prod_shadow')
def get_prod_shadow():
    try:
        csv_path = os.path.join(BASE_DIR, 'financial_data', 'Prod_vs_Shadow_Results_MASTER.csv')
        if not os.path.exists(csv_path):
            csv_path = os.path.join(BASE_DIR, 'Prod_vs_Shadow_Results_MASTER.csv')
        df = pd.read_csv(csv_path)
        
        # Ensure all columns exist
        for col in ['Prod', 'Shadow_Transformer', 'Sandbox_V1', 'Shadow_LSTM']:
            if col not in df.columns:
                df[col] = 10000.0
                
        # Attach S&P 500 (SPY) Benchmark starting at $10,000
        try:
            min_date_str = str(df['Date'].min())[:10]
            import yfinance as yf
            yf_df = yf.download('SPY', start=min_date_str, progress=False)
            if not yf_df.empty:
                c_col = ('Close', 'SPY') if isinstance(yf_df.columns, pd.MultiIndex) else 'Close'
                yf_series = yf_df[c_col]
                yf_map = dict(zip(yf_series.index.strftime('%Y-%m-%d'), yf_series.values))
                spy_close = df['Date'].astype(str).str[:10].map(yf_map).ffill().bfill()
                first_spy_val = float(spy_close.dropna().iloc[0])
                if first_spy_val > 0:
                    df['SPY'] = (spy_close.astype(float) / first_spy_val) * 10000.0
                else:
                    df['SPY'] = 10000.0
            else:
                df['SPY'] = 10000.0
        except Exception as e_spy:
            print(f"[PROD_SHADOW] SPY fetch error: {e_spy}")
            df['SPY'] = 10000.0
    except Exception as e_csv:
        return {'dates': [], 'prod': [], 'trans': [], 'v1': [], 'lstm': [], 'spy': [], 'table': [], 'is_pending': False, 'error': str(e_csv)}

    is_pending = False
    try:
        df_trial = database_manager.get_ledger('BallsForBrains')
        pending = database_manager.get_pending_order('BallsForBrains')
        if pending and not df_trial.empty and pending.get('date')[:10] >= str(df_trial.iloc[-1]['Date'])[:10]:
            target_holdings = json.loads(pending['target_holdings_json'])
            last_holdings = json.loads(df_trial.iloc[-1]['Holdings_JSON'])
            
            has_changes = False
            if abs(float(pending['target_cash']) - float(df_trial.iloc[-1]['Cash'])) > 1.0:
                has_changes = True
            else:
                for t, d in target_holdings.items():
                    target_val = float(d.get('dollars', 0.0)) if isinstance(d, dict) else float(d)
                    last_val = last_holdings.get(t, 0.0)
                    last_val = float(last_val.get('dollars', 0.0)) if isinstance(last_val, dict) else float(last_val)
                    if abs(target_val - last_val) > 1.0:
                        has_changes = True
                        break
                        
            if has_changes:
                is_pending = "PRE-MARKET (PENDING)"
            else:
                is_pending = "Only HOLD for today"
    except:
        pass
        
    def safe_tolist(col_data):
        res = []
        for v in (col_data.tolist() if hasattr(col_data, 'tolist') else list(col_data)):
            try:
                fv = float(v)
                res.append(round(fv, 2) if not np.isnan(fv) else None)
            except:
                res.append(str(v)[:10])
        return res

    # Ensure Date column formatted as ISO string before converting to dict
    df_table = df.copy()
    df_table['Date'] = df_table['Date'].astype(str).str[:10]

    return {
        'dates': [str(v)[:10] for v in df['Date'].tolist()],
        'prod': safe_tolist(df['Prod']) if 'Prod' in df.columns else [10000.0]*len(df),
        'trans': safe_tolist(df['Shadow_Transformer']) if 'Shadow_Transformer' in df.columns else [10000.0]*len(df),
        'v1': safe_tolist(df['Sandbox_V1']) if 'Sandbox_V1' in df.columns else [10000.0]*len(df),
        'lstm': safe_tolist(df['Shadow_LSTM']) if 'Shadow_LSTM' in df.columns else [10000.0]*len(df),
        'spy': safe_tolist(df['SPY']) if 'SPY' in df.columns else [10000.0]*len(df),
        'table': df_table.iloc[::-1].to_dict('records'),
        'is_pending': is_pending
    }

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
