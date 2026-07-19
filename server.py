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

def get_asset_breakdown(df):
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
            if asset not in stats:
                stats[asset] = {'Total Realized PnL ($)': 0.0, 'Trades Executed': 0, 'Wins': 0}
            
            try:
                pnl_val = float(pnl)
                if np.isnan(pnl_val): pnl_val = 0.0
            except:
                pnl_val = 0.0
            stats[asset]['Total Realized PnL ($)'] += pnl_val
            stats[asset]['Trades Executed'] += 1
            if pnl_val > 0:
                stats[asset]['Wins'] += 1
                
    try:
        last_holdings = json.loads(str(df.iloc[-1]['Holdings_JSON']))
    except:
        last_holdings = {}
        
    for asset in last_holdings:
        if asset != 'Cash' and asset not in stats:
            stats[asset] = {'Total Realized PnL ($)': 0.0, 'Trades Executed': 0, 'Wins': 0}
        
    res = []
    for asset, data in stats.items():
        win_rate = (data['Wins'] / data['Trades Executed']) * 100 if data['Trades Executed'] > 0 else 0
        currently_holding = "Yes" if asset in last_holdings else "No"
        
        holding_val = last_holdings.get(asset, 0.0)
        if isinstance(holding_val, dict):
            deployed_cap = holding_val.get('dollars', 0.0)
        else:
            try:
                deployed_cap = float(holding_val)
            except:
                deployed_cap = 0.0
                
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
    p_name = persona if mode == "Single" else f"ETF_{persona}"
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
        if pending and pending.get('date') > str(last_row['Date']):
            cash = float(pending['target_cash'])
            holdings = json.loads(pending['target_holdings_json'])
            is_pending = True
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
    dates = df['Date'].tolist()
    equity_curve = df['Total_Equity'].tolist()
    
    # Get Asset Breakdown Table
    breakdown = get_asset_breakdown(df)
            
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
            eq_col = 'Total_Equity' if 'Total_Equity' in df_p.columns else f'{p}_Total_Equity'
            if 'Date' in df_p.columns and eq_col in df_p.columns:
                df_p['Date'] = pd.to_datetime(df_p['Date'])
                df_p = df_p[['Date', eq_col]].rename(columns={eq_col: p})
                all_ledgers.append(df_p.set_index('Date'))
                
    if not all_ledgers:
        raise HTTPException(status_code=404, detail="No ledger data available")
        
    plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()
    
    # Filter to last 35 days for performance
    plot_df = plot_df[plot_df.index >= (pd.Timestamp.now() - pd.Timedelta(days=35))]
    
    series_data = {}
    for col in plot_df.columns:
        series_data[col] = {
            "dates": plot_df.index.strftime('%Y-%m-%d').tolist(),
            "values": plot_df[col].replace({np.nan: None}).tolist()
        }
        
    try:
        # spy = yf.download('SPY', start=plot_df.index.min(), end=plot_df.index.max() + pd.Timedelta(days=1), progress=False)
        spy = pd.DataFrame() # Disabled to prevent Uvicorn connection pool deadlocks
        if not spy.empty and len(plot_df.columns) > 0:
            start_eq = 10000.0
            if isinstance(spy.columns, pd.MultiIndex):
                spy_close = spy['Close']['SPY']
            else:
                spy_close = spy['Close']
            norm_spy = spy_close / spy_close.iloc[0] * start_eq
            norm_spy = norm_spy.reindex(plot_df.index).ffill().bfill()
            series_data["SPY"] = {
                "dates": norm_spy.index.strftime('%Y-%m-%d').tolist(),
                "values": norm_spy.replace({np.nan: None}).tolist()
            }
    except:
        pass
        
    return series_data

@app.get("/api/dropdown")
def get_dropdown_options(persona: str = "BallsForBrains", mode: str = "Single"):
    options = ["Portfolio Overview"]
    scorecard_path = os.path.join(BASE_DIR, 'Top5_Bayesian_Scorecard_Formatted.xlsx' if mode == 'Single' else 'All_ETFs_Scorecard.xlsx')
    if os.path.exists(scorecard_path):
        try:
            xls = pd.ExcelFile(scorecard_path)
            tickers = [t for t in xls.sheet_names if t != "Sheet1"]
            options.extend(tickers)
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
    scorecard_path = os.path.join(BASE_DIR, 'Top5_Bayesian_Scorecard_Formatted.xlsx' if mode == 'Single' else 'All_ETFs_Scorecard.xlsx')
    
    if not os.path.exists(scorecard_path):
        raise HTTPException(status_code=404, detail="Scorecard not found")
        
    try:
        xls = pd.ExcelFile(scorecard_path)
        if ticker not in xls.sheet_names:
            raise HTTPException(status_code=404, detail="Ticker not found in scorecard")
            
        df = pd.read_excel(xls, sheet_name=ticker, skiprows=2)
        if df.empty:
            raise HTTPException(status_code=404, detail="Ticker scorecard is empty")
            
        latest = df.iloc[-1].fillna("")
        
        mu = float(latest.get('Expected Return %', 0))
        sigma = float(latest.get('Expected Risk (Volatility) %', 1))
        exp_sharpe = (mu / sigma) if sigma and sigma != 0 else 0
        
        # Historical Predictions vs Actual Returns
        history = []
        if 'date' in df.columns and 'Expected Return %' in df.columns and 'actual value daily return %' in df.columns:
            df_hist = df[['date', 'Expected Return %', 'actual value daily return %']].copy().dropna()
            df_hist['date'] = pd.to_datetime(df_hist['date']).dt.strftime('%Y-%m-%d')
            df_hist = df_hist.rename(columns={'date': 'Date', 'actual value daily return %': 'Actual Daily Return %'})
            history = df_hist.to_dict('records')
            
        # Get AI Ledger
        df_ai = format_df_for_display(df.tail(30).iloc[::-1]).reset_index()
        df_ai = df_ai.rename(columns={'index': ''})
        ai_ledger = df_ai.fillna("").to_dict('records')
        
        # Get Broker Trial Ledger and Logs from SQL DB
        broker_ledger = []
        recent_log = []
        
        p_name = persona if mode == "Single" else f"ETF_{persona}"
        
        try:
            df_trial = database_manager.get_ledger(p_name)
            if not df_trial.empty:
                p_cols = ['Date', 'Total_Equity', 'Cash', 'Daily_PnL_JSON', 'Holdings_JSON', 'Intraday_Status']
                avail_cols = [c for c in p_cols if c in df_trial.columns]
                broker_ledger = format_df_for_display(df_trial[avail_cols].iloc[::-1]).fillna("").to_dict('records')
                
                recent_trades = get_recent_trades(df_trial, p_name)
                if recent_trades:
                    recent_log = recent_trades
        except:
            pass

        # Race PnL for single ticker
        race_pnl = {"Conservative": {"dates": [], "values": []}, "Neutral": {"dates": [], "values": []}, "BallsForBrains": {"dates": [], "values": []}}
        for p in ["Conservative", "Neutral", "BallsForBrains"]:
            p_name = p if mode == "Single" else f"ETF_{p}"
            df_p = database_manager.get_ledger(p_name)
            if not df_p.empty:
                if 'Date' in df_p.columns and 'Daily_PnL_JSON' in df_p.columns:
                    df_p['Date'] = pd.to_datetime(df_p['Date'])
                    df_p = df_p[df_p['Date'] >= (pd.Timestamp.now() - pd.Timedelta(days=35))]
                    
                    vals = []
                    for _, row in df_p.iterrows():
                        v = 0.0
                        try:
                            j = json.loads(row['Daily_PnL_JSON'])
                            v = float(j.get(ticker, 0.0))
                        except: pass
                        vals.append(v)
                        
                    cum_vals = pd.Series(vals).cumsum()
                    race_pnl[p]["dates"] = df_p['Date'].dt.strftime('%Y-%m-%d').tolist()
                    race_pnl[p]["values"] = cum_vals.tolist()

        rec_col = 'recommendation based on integrated model\n(e.g. "Buy", "Sell", "Hold")'
        rec_val = latest.get(rec_col, latest.get('Recommendation', 'N/A'))

        return {
            "recommendation": str(rec_val),
            "probability_up": float(latest.get('Bayesian Probability P(UP)', 0)),
            "expected_return": mu,
            "expected_risk": sigma,
            "expected_sharpe": exp_sharpe,
            "kelly_allocation": float(latest.get('Kelly Optimal Allocation %', 0)),
            "broker_note": str(latest.get('Broker Override Note', '')),
            "history": history,
            "ai_ledger": ai_ledger,
            "broker_ledger": broker_ledger,
            "recent_log": recent_log,
            "race_pnl": race_pnl
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/olympic")
def get_olympic_data():
    merged_path = os.path.join(BASE_DIR, 'financial_data', 'Olympic_Shootout_Results_MASTER.csv')
    
    if not os.path.exists(merged_path):
        raise HTTPException(status_code=404, detail="Olympic backtest results not found")
        
    try:
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
        
        metrics = {
            "EL_CAP": {"return": r_c, "dd": d_c, "rank": int(ranks['EL_CAP (70% Liquidity)'])},
            "EL_VOLTI": {"return": r_v, "dd": d_v, "rank": int(ranks['EL_VOLTI (70% Stability)'])},
            "CHAMPION": {"return": r_ch, "dd": d_ch, "rank": int(ranks['CHAMPION (Live VIP)'])}
        }
        
        table_data = format_df_for_display(df_merged.iloc[::-1]).fillna("").to_dict('records')
        
        chart_data = {
            "dates": df_merged['Date'].tolist(),
            "EL_CAP": df_merged['EL_CAP (70% Liquidity)'].tolist(),
            "EL_VOLTI": df_merged['EL_VOLTI (70% Stability)'].tolist(),
            "CHAMPION": df_merged['CHAMPION (Live VIP)'].tolist()
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
    csv_path = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data'), 'Prod_vs_Shadow_Results_MASTER.csv')
    if not os.path.exists(csv_path): return {'dates': [], 'prod': [], 'trans': [], 'v1': [], 'table': []}
    df = pd.read_csv(csv_path)
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date')
        df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
    df = df.ffill().fillna(10000.0)
    return {
        'dates': df['Date'].tolist(),
        'prod': df['Prod'].tolist(),
        'trans': df['Shadow_Transformer'].tolist(),
        'v1': df['Sandbox_V1'].tolist(),
        'lstm': df.get('Shadow_LSTM', pd.Series([10000.0]*len(df))).tolist(),
        'table': df.iloc[::-1].to_dict('records')
    }

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
