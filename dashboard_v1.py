import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import scipy.stats as stats
import plotly.graph_objects as go
import ast

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

st.set_page_config(page_title="AntiGravity Dashboard", layout="wide", page_icon="🌌")

st.markdown("""<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap");
html, body, [class*="css"], [class*="st-"], p, div, h1, h2, h3, h4, h5, h6, span {
    font-family: "Inter", sans-serif !important;
}
</style>""", unsafe_allow_html=True)


st.markdown("""
    <style>
    /* Aggressively increase font size of main tabs */
    button[data-baseweb="tab"],
    button[data-baseweb="tab"] * {
        font-size: 24px !important;
    }
    
    /* Aggressively increase font size of Metric Headers & Dropdown Labels (+25% over default 14px) */
    [data-testid="stMetricLabel"], 
    [data-testid="stMetricLabel"] *,
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] label *,
    .stMetric label,
    .stMetric label *,
    [data-testid="stWidgetLabel"],
    [data-testid="stWidgetLabel"] * {
        font-size: 18px !important;
    }
    </style>
""", unsafe_allow_html=True)

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'

# --- DATA LOADERS ---
@st.cache_data(ttl=60) # cache for 60 seconds
def get_latest_holdings(persona="BallsForBrains", mode="Single"):
    import sys
    sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
    import database_manager
    if mode == "Single":
        df = database_manager.get_ledger(persona)
    else:
        df = database_manager.get_ledger(f"ETF_{persona}")
    if df.empty:
        return None, None
    if df.empty:
        return None, None
        
    last_row = df.iloc[-1]
    cash = float(last_row['Cash'])
    total_eq = float(last_row['Total_Equity'])
    holdings = json.loads(last_row['Holdings_JSON'])
    
    allocations = {'Cash': cash}
    for ticker, data in holdings.items():
        if isinstance(data, dict):
            allocations[ticker] = float(data.get('dollars', 0.0))
        else:
            allocations[ticker] = float(data)
            
    return allocations, total_eq

STD_LAYOUT = dict(
    plot_bgcolor='rgba(0,0,0,0)', 
    paper_bgcolor='rgba(0,0,0,0)',
    font=dict(color='white', size=14),
    margin=dict(t=60, b=20, l=20, r=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    hoverlabel=dict(bgcolor="#2A2A2A", font_size=14, font_family="sans-serif", font_color="white")
)

def plot_bayesian_curve(mu, sigma, ticker):
    if pd.isna(mu) or pd.isna(sigma) or sigma <= 0:
        return None
        
    x = np.linspace(mu - 4*sigma, mu + 4*sigma, 500)
    y = stats.norm.pdf(x, mu, sigma)
    
    fig = go.Figure()
    
    # Fill below 0 (Loss)
    x_loss = x[x <= 0]
    y_loss = y[x <= 0]
    if len(x_loss) > 0:
        fig.add_trace(go.Scatter(x=x_loss, y=y_loss, fill='tozeroy', mode='none', fillcolor='rgba(255, 65, 54, 0.5)', name='Loss Region'))
        
    # Fill above 0 (Win)
    x_win = x[x >= 0]
    y_win = y[x >= 0]
    if len(x_win) > 0:
        fig.add_trace(go.Scatter(x=x_win, y=y_win, fill='tozeroy', mode='none', fillcolor='rgba(46, 204, 64, 0.5)', name='Win Region'))
        
    fig.add_trace(go.Scatter(x=x, y=y, mode='lines', line=dict(color='white', width=2), showlegend=False))
    fig.add_vline(x=0, line_width=2, line_dash="dash", line_color="yellow")
    
    y_max = max(y) if len(y) > 0 else 1
    fig.update_layout(
        **STD_LAYOUT,
        title=f"Bayesian Expected Return Distribution: {ticker}",
        xaxis_title="Expected Return %",
        yaxis_title="Probability Density",
        xaxis=dict(tickformat=".2%"),
        yaxis=dict(range=[0, y_max * 1.20]),
        height=450
    )
    return fig

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
        
    # Max Drawdown & Total Return
    equity = df[eq_col].dropna()
    if len(equity) > 0:
        roll_max = equity.cummax()
        drawdown = (equity - roll_max) / roll_max
        max_dd = drawdown.min() * 100
        total_return = ((equity.iloc[-1] - 10000.0) / 10000.0) * 100
    else:
        max_dd = 0
        total_return = 0
        
    # Sharpe Ratio
    if len(pct_returns) > 1 and pct_returns.std() > 0:
        sharpe = (pct_returns.mean() / pct_returns.std()) * np.sqrt(252)
    else:
        sharpe = 0
        
    # Win Rate
    active_days = pct_returns[pct_returns != 0]
    if len(active_days) > 0:
        win_rate = (len(active_days[active_days > 0]) / len(active_days)) * 100
    else:
        win_rate = 0
        
    return max_dd, sharpe, win_rate, total_return

def format_df_for_display(df_in):
    d = df_in.copy()
    # Format index if it's datetime
    if isinstance(d.index, pd.DatetimeIndex):
        d.index = d.index.strftime('%Y-%m-%d')
        
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime('%Y-%m-%d')
        elif d[c].dtype == object or pd.api.types.is_string_dtype(d[c]):
            d[c] = d[c].astype(str).str.replace(' 00:00:00', '')
    return d

def get_recent_trades(df, persona, limit=5):
    h_col = 'Holdings_JSON' if 'Holdings_JSON' in df.columns else f'{persona}_Holdings'
    if h_col not in df.columns or len(df) < 2:
        return []
    
    raw_trades = []
    # Parse last limit+1 days to get limit days of diff
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

def get_asset_breakdown(persona, mode):
    import sys
    sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
    import database_manager
    if mode == "Single":
        df = database_manager.get_ledger(persona)
    else:
        df = database_manager.get_ledger(f"ETF_{persona}")
    if df.empty:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
        
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
            
            pnl_val = float(pnl)
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
        return pd.DataFrame()
        
    out_df = pd.DataFrame(res)
    out_df = out_df.sort_values(by='Total Realized PnL ($)', ascending=False)
    
    # Calculate totals
    total_pnl = out_df['Total Realized PnL ($)'].sum()
    total_trades = out_df['Closed Trades'].sum()
    total_wins = sum(data['Wins'] for data in stats.values())
    total_win_rate = (total_wins / total_trades) * 100 if total_trades > 0 else 0
    
    total_row = pd.DataFrame([{
        'Asset': 'TOTAL PnL',
        'Total Realized PnL ($)': round(total_pnl, 2),
        'Deployed Capital ($)': '',
        'Closed Trades': total_trades,
        'Win Rate': f"{total_win_rate:.1f}%",
        'Currently Holding': ''
    }])
    
    try:
        last_total_equity = float(df.iloc[-1]['Total_Equity'])
    except:
        last_total_equity = 10000.0
        
    out_df = pd.concat([out_df, total_row], ignore_index=True)
    return out_df

def get_losing_trades(persona, mode):
    try:
        import sys
        if BASE_DIR not in sys.path:
            sys.path.append(BASE_DIR)
        from blacklist_engine import get_blacklisted_tickers
        blacklisted_set = get_blacklisted_tickers(persona="BallsForBrains")
    except:
        blacklisted_set = set()

    import sys
    sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
    import database_manager
    if mode == "Single":
        ledger = database_manager.get_ledger(persona)
        scorecard_path = os.path.join(BASE_DIR, 'Top5_Bayesian_Scorecard_Formatted.xlsx')
    else:
        ledger = database_manager.get_ledger(f"ETF_{persona}")
        scorecard_path = os.path.join(BASE_DIR, 'All_ETFs_Scorecard.xlsx')
    if ledger.empty:
        return pd.DataFrame(), pd.DataFrame()
    if ledger.empty:
        return pd.DataFrame(), pd.DataFrame()
        
    try:
        xls = pd.ExcelFile(scorecard_path)
    except:
        xls = None

    losing_trades = []
    serial_offenders = {}
    
    for _, row in ledger.iterrows():
        date_str = str(row['Date'])
        try:
            import json
            pnl_dict = json.loads(str(row['Daily_PnL_JSON']))
        except:
            pnl_dict = {}
            
        for asset, pnl in pnl_dict.items():
            pnl_val = float(pnl)
            if pnl_val < -1.0:  # Meaningful loss > $1
                if asset not in serial_offenders:
                    serial_offenders[asset] = 0.0
                serial_offenders[asset] += pnl_val
                
                prob, exp_ret, exp_vol, kelly, note = None, None, None, None, None
                if xls and asset in xls.sheet_names:
                    try:
                        df_sc = pd.read_excel(xls, sheet_name=asset, skiprows=2)
                        date_col = 'date' if 'date' in df_sc.columns else 'Date'
                        df_sc[date_col] = pd.to_datetime(df_sc[date_col]).dt.strftime('%Y-%m-%d')
                        
                        match = df_sc[df_sc[date_col] == date_str]
                        if not match.empty:
                            m_row = match.iloc[0]
                            prob = m_row.get('Bayesian Probability P(UP)')
                            exp_ret = m_row.get('Expected Return %')
                            exp_vol = m_row.get('Expected Risk (Volatility) %')
                            kelly = m_row.get('Kelly Optimal Allocation %')
                            note = m_row.get('Broker Override Note')
                    except:
                        pass
                        
                blacklist_status = "Blacklisted (≥3 Strikes)" if asset in blacklisted_set else "OK"
                losing_trades.append({
                    'Date': date_str,
                    'Asset': asset,
                    'Realized Loss ($)': round(pnl_val, 2),
                    'Day of Week': pd.to_datetime(date_str).day_name(),
                    'Bayesian Prob P(UP)': f"{prob*100:.1f}%" if pd.notna(prob) else "N/A",
                    'Exp Return': f"{exp_ret*100:.1f}%" if pd.notna(exp_ret) else "N/A",
                    'Exp Volatility': f"{exp_vol*100:.1f}%" if pd.notna(exp_vol) else "N/A",
                    'Kelly Sizing': f"{kelly*100:.1f}%" if pd.notna(kelly) else "N/A",
                    'Override Note': str(note) if pd.notna(note) and str(note).strip() != "nan" and str(note).strip() != "" else "None",
                    'Blacklist Status': blacklist_status
                })
                
    offenders_df = pd.DataFrame([{'Asset': k, 'Cumulative Loss ($)': v} for k, v in serial_offenders.items()])
    if not offenders_df.empty:
        offenders_df = offenders_df.sort_values(by='Cumulative Loss ($)', ascending=True)
        
    trades_df = pd.DataFrame(losing_trades)
    if not trades_df.empty:
        trades_df = trades_df.sort_values(by='Realized Loss ($)', ascending=True)
        
    return trades_df, offenders_df
        
    equity_row = pd.DataFrame([{
        'Asset': 'CURRENT EQUITY',
        'Total Realized PnL ($)': round(last_total_equity, 2),
        'Deployed Capital ($)': None,
        'Closed Trades': None,
        'Win Rate': '',
        'Currently Holding': ''
    }])
    
    try:
        cash_val = float(df.iloc[-1]['Cash'])
    except:
        cash_val = 0.0
        
    cash_row = pd.DataFrame([{
        'Asset': 'AVAILABLE CASH',
        'Total Realized PnL ($)': None,
        'Deployed Capital ($)': round(cash_val, 2),
        'Closed Trades': None,
        'Win Rate': '',
        'Currently Holding': ''
    }])
    
    out_df = pd.concat([out_df, total_row, cash_row, equity_row], ignore_index=True)
    
    return out_df

# --- UI RENDERING ---
import base64
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

try:
    img_base64 = get_base64_of_bin_file(os.path.join(BASE_DIR.replace("financial_data", ""), "oracle_logo.png"))
    st.markdown(
        f'''
        <div style="display: flex; justify-content: center; align-items: center; margin-bottom: 20px;">
            <img src="data:image/png;base64,{img_base64}" width="210">
        </div>
        ''',
        unsafe_allow_html=True
    )
except:
    pass

eye_base64 = get_base64_of_bin_file(os.path.join(BASE_DIR.replace("financial_data", ""), "oracle_eye.png"))
st.markdown(
    f'''
    <h1 style="display: flex; align-items: center; gap: 15px;">
        <img src="data:image/png;base64,{eye_base64}" height="45" style="border-radius: 10px;">
        The Oracle Command Center
    </h1>
    ''',
    unsafe_allow_html=True
)
st.markdown("Read-Only Bayesian Live Web Dashboard")

tab1, tab2, tab3, tab4 = st.tabs(["📈 Active Portfolio (Stocks)", "🌐 Multi-Sector ETFs", "🏆 Ticker Population Olympic", "🏥 Trade Autopsy"])

# --- VIEW 1: SINGLE STOCKS ---
with tab1:
    # 1. Donut at top center
    c_p1, c_p2, c_p3 = st.columns([1, 2, 1])
    with c_p2:
        persona_s_ui = st.selectbox("Select Broker Persona", ["Conservative", "Neutral", "Balls For Brain", "Dynamic Sharpe"], index=3, key="persona_s")
        if persona_s_ui == "Balls For Brain":
            persona_s = "BallsForBrains"
        elif persona_s_ui == "Dynamic Sharpe":
            persona_s = "Dynamic"
        else:
            persona_s = persona_s_ui
    
    st.markdown(f"<h3 style='text-align: center;'>{persona_s_ui} Live Holdings</h3>", unsafe_allow_html=True)
    c_don1, c_don2, c_don3 = st.columns([1, 4, 1])
    with c_don2:
        allocs, total_eq = get_latest_holdings(persona=persona_s, mode="Single")
        if allocs:
            max_dd, sharpe, win_rate, total_return = 0, 0, 0, 0
            import sys
            sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
            import database_manager
            df_trial = database_manager.get_ledger(persona_s)
            if not df_trial.empty:
                max_dd, sharpe, win_rate, total_return = calculate_metrics(df_trial, persona_s_ui)

            col_met1, col_met2, col_met3, col_met4, col_met5 = st.columns(5)
            col_met1.metric("Total Equity", f"${total_eq:,.2f}")
            col_met2.metric("Total Return", f"{total_return:+.2f}%")
            col_met3.metric("Max Drawdown", f"{max_dd:.2f}%")
            col_met4.metric("Sharpe Ratio", f"{sharpe:.2f}")
            col_met5.metric("Daily Win Rate", f"{win_rate:.1f}%")
            labels = list(allocs.keys())
            values = list(allocs.values())
            c_pal = ['#00E5FF', '#FF851B', '#B10DC9', '#FFDC00', '#FF4136', '#39CCCC']
            c_map = [ '#4CAF50' if l == 'Cash' else c_pal[i % len(c_pal)] for i, l in enumerate(labels) ]
            fig_pie = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.5, textposition='outside', textfont=dict(size=14), texttemplate='<b>%{label}</b><br>$%{value:,.0f} (%{percent})',
                             marker=dict(colors=c_map))])
            fig_pie.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='white', size=18), legend=dict(font=dict(size=24)), margin=dict(t=30, b=40, l=120, r=10), height=400)
            st.plotly_chart(fig_pie, use_container_width=True, key="pie_single")
        else:
            st.info("No ledger data available.")

    st.markdown("---")
    
    scorecard_path = os.path.join(BASE_DIR, 'Top5_Bayesian_Scorecard_Formatted.xlsx')
    if os.path.exists(scorecard_path):
        xls = pd.ExcelFile(scorecard_path)
        tickers = [t for t in xls.sheet_names if t != "Sheet1"]
        
        options = ["Portfolio Overview"] + tickers
        
        breakdown_df = get_asset_breakdown(persona_s, "Single")
        if not breakdown_df.empty:
            for holding in breakdown_df['Asset']:
                if holding not in ['TOTAL PnL', 'AVAILABLE CASH', 'CURRENT EQUITY'] and holding not in options:
                    options.append(holding)
                    
        selected_ticker = st.selectbox("Select View", options, key="single_ticker")
        
        if selected_ticker == "Portfolio Overview":
            st.markdown("### 📊 Live Portfolio Overview")
            allocs, _ = get_latest_holdings(persona=persona_s, mode="Single")
            if allocs:
                cols = st.columns(len(allocs))
                for i, (asset, amount) in enumerate(allocs.items()):
                    cols[i].metric(asset, f"${amount:,.2f}")
            else:
                st.info("No active holdings found.")
                
            st.markdown("<br>### 🧱 Asset Breakdown (Since Inception)", unsafe_allow_html=True)
            breakdown_df = get_asset_breakdown(persona_s, "Single")
            if not breakdown_df.empty:
                st.table(breakdown_df.style.format({'Total Realized PnL ($)': lambda x: '${:,.2f}'.format(x) if isinstance(x, (int, float)) else x, 'Deployed Capital ($)': lambda x: '${:,.2f}'.format(x) if isinstance(x, (int, float)) else x}).map(lambda x: 'color: #33CC33' if isinstance(x, (int, float)) and x > 0 else ('color: #FF0000' if isinstance(x, (int, float)) and x < 0 else ''), subset=['Total Realized PnL ($)']).set_properties(**{'font-size': '24px'}))
            else:
                st.info("No trading history available yet to break down.")
                
            st.markdown("---")
            st.markdown("### 🏎️ 30-Day Multi-Broker Portfolio Race")
            all_ledgers = []
            for p in ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]:
                import sys
                sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
                import database_manager
                df_p = database_manager.get_ledger(p)
                if not df_p.empty:
                    if 'Date' in df_p.columns and 'Total_Equity' in df_p.columns:
                        df_p['Date'] = pd.to_datetime(df_p['Date'])
                        df_p = df_p[['Date', 'Total_Equity']].rename(columns={'Total_Equity': f'{p}'})
                        all_ledgers.append(df_p.set_index('Date'))
            
            if all_ledgers:
                plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()
                plot_df = plot_df[plot_df.index >= (pd.Timestamp.now() - pd.Timedelta(days=35))]
                
                fig_pnl = go.Figure()
                for col in plot_df.columns:
                    line_style = dict(width=2)
                    if 'Conservative' in col:
                        line_style['dash'] = 'dot'
                        line_style['color'] = '#FF851B'
                        line_style['width'] = 4
                    elif 'Neutral' in col:
                        line_style['dash'] = 'dash'
                        line_style['color'] = '#2ECC40'
                        line_style['width'] = 4
                    elif 'Balls' in col:
                        line_style['color'] = '#00E5FF'
                        line_style['width'] = 2
                    
                    fig_pnl.add_trace(go.Scatter(x=plot_df.index, y=plot_df[col], mode='lines+markers', name=col, line=line_style, marker=dict(size=8 if 'Conservative' in col else 6), hovertemplate=f"<b>{col}</b><br>%{{x|%b %d, %Y}}<br>$%{{y:,.2f}}<extra></extra>"))
                    
                if HAS_YF and len(plot_df) > 0:
                    try:
                        spy = yf.download('SPY', start=plot_df.index.min(), end=plot_df.index.max() + pd.Timedelta(days=1), progress=False)
                        if not spy.empty and len(plot_df.columns) > 0:
                            start_eq = plot_df.iloc[0, 0]
                            if isinstance(spy.columns, pd.MultiIndex):
                                spy_close = spy['Close']['SPY']
                            else:
                                spy_close = spy['Close']
                            norm_spy = spy_close / spy_close.iloc[0] * start_eq
                            norm_spy = norm_spy.reindex(plot_df.index).ffill().bfill()
                            fig_pnl.add_trace(go.Scatter(x=norm_spy.index, y=norm_spy, mode='lines+markers', name='S&P 500 (SPY)', line=dict(color='white', width=2, dash='solid'), hovertemplate="<b>S&P 500 (SPY)</b><br>%{x|%b %d, %Y}<br>$%{y:,.2f}<extra></extra>"))
                    except: pass
                        
                # --- Dynamic Y-Axis Padding ---
                y_min = plot_df.min().min()
                y_max = plot_df.max().max()
                
                if HAS_YF and 'norm_spy' in locals():
                    try:
                        y_min = min(y_min, norm_spy.min())
                        y_max = max(y_max, norm_spy.max())
                    except: pass
                    
                y_pad = (y_max - y_min) * 0.20 if (y_max - y_min) != 0 else abs(y_max) * 0.02
                
                # INVISIBLE ANCHORS TO FORCE Y-AXIS PADDING (Plotly rangeslider ignores layout.range)
                fig_pnl.add_trace(go.Scatter(x=[plot_df.index[0], plot_df.index[0]], y=[y_min - y_pad, y_max + y_pad], mode='markers', marker=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='skip'))
                
                fig_pnl.update_layout(
                    **STD_LAYOUT,
                    height=550,
                    xaxis=dict(rangeslider=dict(visible=True, thickness=0.08, bgcolor='#383838', bordercolor='#1E90FF', borderwidth=1)),
                    yaxis=dict(tickformat="$.2f")
                )
                st.plotly_chart(fig_pnl, use_container_width=True, key="pnl_portfolio_main")
        else:
            try:
                df = pd.read_excel(xls, sheet_name=selected_ticker, skiprows=2)
            except:
                df = pd.DataFrame()
                st.warning(f"⚠️ {selected_ticker} is not in today's Top 5 Bayesian Scorecard. Live prediction data is unavailable, but you can still view its historical Realized PnL below.")
                
            if not df.empty:
                latest = df.iloc[-1]
                rec = latest.get('recommendation based on integrated model\n(e.g. "Buy", "Sell", "Hold")', 'N/A')
                st.markdown(f"### Live Recommendation: **{rec}**")
                
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Probability P(UP)", f"{latest.get('Bayesian Probability P(UP)', 0)*100:.1f}%")
                
                mu = latest.get('Expected Return %', 0)
                sigma = latest.get('Expected Risk (Volatility) %', 1)
                exp_sharpe = (mu / sigma) if sigma and sigma != 0 else 0
                
                m2.metric("Expected Return", f"{mu*100:.2f}%")
                m3.metric("Expected Sharpe", f"{exp_sharpe:.2f}")
                m4.metric("Kelly Allocation", f"{latest.get('Kelly Optimal Allocation %', 0)*100:.1f}%")
                
                note = latest.get('Broker Override Note', '')
                if pd.notna(note) and note != "":
                    m5.error(note)
                else:
                    m5.success("Trade Cleared")
            
            
            if not df.empty and selected_ticker != "Portfolio Overview":
                # 2. Distribution side by side with the trend line
                c_fig1, c_fig2 = st.columns(2)
                with c_fig1:
                    mu = latest.get('Expected Return %', 0)
                    sigma = latest.get('Expected Risk (Volatility) %', 0)
                    fig = plot_bayesian_curve(mu, sigma, selected_ticker)
                    if fig:
                        st.plotly_chart(fig, use_container_width=True, key="dist_single")
                with c_fig2:
                    st.markdown("**Historical Predictions vs Actual Returns**")
                    try:
                        # Fix column name for Single Stocks
                        df_plot = df[['date', 'Expected Return %', 'actual value daily return %']].copy()
                        df_plot.rename(columns={'actual value daily return %': 'Actual Daily Return %', 'date': 'Date'}, inplace=True)
                        df_plot['Date'] = pd.to_datetime(df_plot['Date'])
                        
                        fig_line = go.Figure()
                        fig_line.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['Expected Return %'], mode='lines', line=dict(color='#FF851B', width=2), name='Expected (Orange)'))
                        # Darker blue for Actual
                        fig_line.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['Actual Daily Return %'], mode='lines', line=dict(color='#1E90FF', width=2), name='Actual (Blue)'))
                        
                        y_min = min(df_plot['Expected Return %'].min(), df_plot['Actual Daily Return %'].min())
                        y_max = max(df_plot['Expected Return %'].max(), df_plot['Actual Daily Return %'].max())
                        y_pad = (y_max - y_min) * 0.20 if (y_max - y_min) != 0 else abs(y_max) * 0.02 if y_max != 0 else 0.02
                        
                        # INVISIBLE ANCHORS TO FORCE Y-AXIS PADDING
                        fig_line.add_trace(go.Scatter(x=[df_plot['Date'].iloc[0], df_plot['Date'].iloc[0]], y=[y_min - y_pad, y_max + y_pad], mode='markers', marker=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='skip'))
                        
                        fig_line.update_layout(
                            **STD_LAYOUT,
                            height=550,
                            yaxis=dict(tickformat=".2%"),
                            xaxis=dict(rangeslider=dict(visible=True, thickness=0.08, bgcolor='#383838', bordercolor='#1E90FF', borderwidth=1))
                        )
                        st.plotly_chart(fig_line, use_container_width=True, key="line_single")
                    except Exception as e:
                        pass
            
            # 3. Bottom Ledgers and PnL Race
            # df_trial already loaded above
                
            c_bot1, c_bot2 = st.columns([1.2, 1])
            with c_bot1:
                t_ai, t_br, t_log = st.tabs(["🤖 AI Mathematical Ledger", f"💼 {persona_s_ui} Trade Ledger", "📜 Recent Execution Log"])
                with t_ai:
                    if not df.empty:
                        disp_df = format_df_for_display(df.iloc[::-1])
                        st.dataframe(disp_df.style.format(na_rep=''), use_container_width=True, height=250)
                    else:
                        st.info(f"No Bayesian scorecard data available for {selected_ticker}.")
                with t_br:
                    if not df_trial.empty:
                        p_cols = ['Date', 'Total_Equity', 'Cash', 'Daily_PnL_JSON', 'Holdings_JSON']
                        avail_cols = [c for c in p_cols if c in df_trial.columns]
                        disp_trial = format_df_for_display(df_trial[avail_cols].iloc[::-1])
                        st.dataframe(disp_trial.style.format(na_rep=''), use_container_width=True, height=250)
                    else:
                        st.info("No broker trial data available.")
                with t_log:
                    if not df_trial.empty:
                        recent_trades = get_recent_trades(df_trial, persona_s_ui)
                        if recent_trades:
                            for trade in recent_trades:
                                st.markdown(f"**{trade}**")
                        else:
                            st.info("No recent trades detected.")
                    else:
                        st.info("No broker trial data available.")
                        
            with c_bot2:
                if selected_ticker == "Portfolio Overview":
                    st.markdown("**30-Day Multi-Broker Portfolio Race**")
                else:
                    st.markdown(f"**30-Day Multi-Broker Race: {selected_ticker} Realized PnL**")
                    
                all_ledgers = []
                for p in ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]:
                    import sys
                    sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
                    import database_manager
                    import json
                    df_p = database_manager.get_ledger(p)
                    if not df_p.empty:
                        if 'Date' in df_p.columns:
                            df_p['Date'] = pd.to_datetime(df_p['Date'])
                            if selected_ticker == "Portfolio Overview" and 'Total_Equity' in df_p.columns:
                                df_p = df_p[['Date', 'Total_Equity']].rename(columns={'Total_Equity': f'{p}'})
                                all_ledgers.append(df_p.set_index('Date'))
                            elif selected_ticker != "Portfolio Overview" and 'Daily_PnL_JSON' in df_p.columns:
                                vals = []
                                for _, row in df_p.iterrows():
                                    v = 0.0
                                    try:
                                        j = json.loads(row['Daily_PnL_JSON'])
                                        v = float(j.get(selected_ticker, 0.0))
                                    except: pass
                                    vals.append(v)
                                df_p[f'{p}'] = pd.Series(vals).cumsum()
                                df_p = df_p[['Date', f'{p}']]
                                all_ledgers.append(df_p.set_index('Date'))
                
                if all_ledgers:
                    plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()
                    plot_df = plot_df[plot_df.index >= (pd.Timestamp.now() - pd.Timedelta(days=35))]
                    
                    fig_pnl = go.Figure()
                    for col in plot_df.columns:
                        line_style = dict(width=2)
                        if 'Conservative' in col:
                            line_style['dash'] = 'dot'
                            line_style['color'] = '#FF851B'
                            line_style['width'] = 4
                        elif 'Neutral' in col:
                            line_style['dash'] = 'dash'
                            line_style['color'] = '#2ECC40'
                            line_style['width'] = 4
                        elif 'Balls' in col:
                            line_style['color'] = '#00E5FF'
                            line_style['width'] = 2
                        
                        # Plot with standard lines, not 'hv' so it's smooth!
                        fig_pnl.add_trace(go.Scatter(x=plot_df.index, y=plot_df[col], mode='lines+markers', name=col, line=line_style, marker=dict(size=8 if 'Conservative' in col else 6), hovertemplate=f"<b>{col}</b><br>%{{x|%b %d, %Y}}<br>$%{{y:,.2f}}<extra></extra>"))
                        
                    if selected_ticker == "Portfolio Overview" and HAS_YF and len(plot_df) > 0:
                        try:
                            spy = yf.download('SPY', start=plot_df.index.min(), end=plot_df.index.max() + pd.Timedelta(days=1), progress=False)
                            if not spy.empty and len(plot_df.columns) > 0:
                                start_eq = plot_df.iloc[0, 0]
                                if isinstance(spy.columns, pd.MultiIndex):
                                    spy_close = spy['Close']['SPY']
                                else:
                                    spy_close = spy['Close']
                                norm_spy = spy_close / spy_close.iloc[0] * start_eq
                                norm_spy = norm_spy.reindex(plot_df.index).ffill().bfill()
                                fig_pnl.add_trace(go.Scatter(x=norm_spy.index, y=norm_spy, mode='lines+markers', name='S&P 500 (SPY)', line=dict(color='white', width=2, dash='solid'), hovertemplate="<b>S&P 500 (SPY)</b><br>%{x|%b %d, %Y}<br>$%{y:,.2f}<extra></extra>"))
                        except: pass
                            
                    # --- Dynamic Y-Axis Padding ---
                    y_min = plot_df.min().min()
                    y_max = plot_df.max().max()
                    
                    if selected_ticker == "Portfolio Overview" and HAS_YF and 'norm_spy' in locals():
                        try:
                            y_min = min(y_min, norm_spy.min())
                            y_max = max(y_max, norm_spy.max())
                        except: pass
                        
                    y_pad = (y_max - y_min) * 0.20 if (y_max - y_min) != 0 else abs(y_max) * 0.02
                    
                    # INVISIBLE ANCHORS TO FORCE Y-AXIS PADDING
                    fig_pnl.add_trace(go.Scatter(x=[plot_df.index[0], plot_df.index[0]], y=[y_min - y_pad, y_max + y_pad], mode='markers', marker=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='skip'))
                    
                    fig_pnl.update_layout(
                        **STD_LAYOUT,
                        height=550,
                        xaxis=dict(rangeslider=dict(visible=True, thickness=0.08, bgcolor='#383838', bordercolor='#1E90FF', borderwidth=1)),
                        yaxis=dict(tickformat="$.2f")
                    )
                    st.plotly_chart(fig_pnl, use_container_width=True, key="pnl_single_multi")
    else:
        st.warning("Scorecard not found. Run the morning pipeline first.")

# --- VIEW 2: MULTI-SECTOR ETFs ---
with tab2:
    # 1. Donut at top center
    c_p1_e, c_p2_e, c_p3_e = st.columns([1, 2, 1])
    with c_p2_e:
        persona_e_ui = st.selectbox("Select Broker Persona", ["Conservative", "Neutral", "Balls For Brain", "Dynamic Sharpe"], index=3, key="persona_e")
        if persona_e_ui == "Balls For Brain":
            persona_e = "BallsForBrains"
        elif persona_e_ui == "Dynamic Sharpe":
            persona_e = "Dynamic"
        else:
            persona_e = persona_e_ui
        
    st.markdown(f"<h3 style='text-align: center;'>{persona_e_ui} ETF Holdings</h3>", unsafe_allow_html=True)
    c_don1_e, c_don2_e, c_don3_e = st.columns([1, 4, 1])
    with c_don2_e:
        allocs_e, total_eq_e = get_latest_holdings(persona=persona_e, mode="ETF")
        if allocs_e:
            etf_trial_path = os.path.join(BASE_DIR, 'ETF_Broker_30Day_Trial.xlsx')
            max_dd_e, sharpe_e, win_rate_e, total_return_e = 0, 0, 0, 0
            df_etf_trial = pd.DataFrame()
            if os.path.exists(etf_trial_path):
                df_etf_trial = pd.read_excel(etf_trial_path, sheet_name='Daily Tracking')
                max_dd_e, sharpe_e, win_rate_e, total_return_e = calculate_metrics(df_etf_trial, persona_e_ui)

            col_met1, col_met2, col_met3, col_met4, col_met5 = st.columns(5)
            col_met1.metric("Total Equity", f"${total_eq_e:,.2f}")
            col_met2.metric("Total Return", f"{total_return_e:+.2f}%")
            col_met3.metric("Max Drawdown", f"{max_dd_e:.2f}%")
            col_met4.metric("Sharpe Ratio", f"{sharpe_e:.2f}")
            col_met5.metric("Daily Win Rate", f"{win_rate_e:.1f}%")
            labels_e = list(allocs_e.keys())
            values_e = list(allocs_e.values())
            c_pal_e = ['#00E5FF', '#FF851B', '#B10DC9', '#FFDC00', '#FF4136', '#39CCCC']
            c_map_e = [ '#4CAF50' if l == 'Cash' else c_pal_e[i % len(c_pal_e)] for i, l in enumerate(labels_e) ]
            fig_pie_e = go.Figure(data=[go.Pie(labels=labels_e, values=values_e, hole=.5, textposition='outside', textfont=dict(size=14), texttemplate='<b>%{label}</b><br>$%{value:,.0f} (%{percent})',
                             marker=dict(colors=c_map_e))])
            fig_pie_e.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='white', size=18), legend=dict(font=dict(size=24)), margin=dict(t=30, b=40, l=120, r=10), height=400)
            st.plotly_chart(fig_pie_e, use_container_width=True, key="pie_etf")
        else:
            st.info("No ETF ledger data available.")

    st.markdown("---")
    
    etf_path = os.path.join(BASE_DIR, 'All_ETFs_Scorecard.xlsx')
    if os.path.exists(etf_path):
        xls_etf = pd.ExcelFile(etf_path)
        etfs = [t for t in xls_etf.sheet_names if t != "Sheet1"]
        
        options_e = ["Portfolio Overview"] + etfs
        selected_etf = st.selectbox("Select View", options_e, key="etf_ticker")
        
        if selected_etf == "Portfolio Overview":
            st.markdown("### 📊 Live ETF Portfolio Overview")
            allocs_e, _ = get_latest_holdings(persona=persona_e, mode="ETF")
            if allocs_e:
                cols_e = st.columns(len(allocs_e))
                for i, (asset, amount) in enumerate(allocs_e.items()):
                    cols_e[i].metric(asset, f"${amount:,.2f}")
            else:
                st.info("No active holdings found.")
                
            st.markdown("<br>### 🧱 ETF Asset Breakdown (Since Inception)", unsafe_allow_html=True)
            breakdown_df_e = get_asset_breakdown(persona_e, "ETF")
            if not breakdown_df_e.empty:
                st.table(breakdown_df_e.style.format({'Total Realized PnL ($)': lambda x: '${:,.2f}'.format(x) if isinstance(x, (int, float)) else x, 'Deployed Capital ($)': lambda x: '${:,.2f}'.format(x) if isinstance(x, (int, float)) else x}).map(lambda x: 'color: #33CC33' if isinstance(x, (int, float)) and x > 0 else ('color: #FF0000' if isinstance(x, (int, float)) and x < 0 else ''), subset=['Total Realized PnL ($)']).set_properties(**{'font-size': '24px'}))
            else:
                st.info("No ETF trading history available yet to break down.")
                
            st.markdown("---")
            st.markdown("### 🏎️ 30-Day Multi-Broker ETF Race")
            all_ledgers_e = []
            for p in ["Conservative", "Neutral", "BallsForBrains"]:
                import sys
                sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
                import database_manager
                df_p = database_manager.get_ledger(f"ETF_{p}")
                if not df_p.empty:
                    if 'Date' in df_p.columns and 'Total_Equity' in df_p.columns:
                        df_p['Date'] = pd.to_datetime(df_p['Date'])
                        df_p = df_p[['Date', 'Total_Equity']].rename(columns={'Total_Equity': f'{p}'})
                        all_ledgers_e.append(df_p.set_index('Date'))
            
            if all_ledgers_e:
                plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()
                plot_df_e = plot_df_e[plot_df_e.index >= (pd.Timestamp.now() - pd.Timedelta(days=35))]
                
                fig_pnl_e = go.Figure()
                for col in plot_df_e.columns:
                    line_style_e = dict(width=2)
                    if 'Conservative' in col:
                        line_style_e['dash'] = 'dot'
                        line_style_e['color'] = '#FF851B'
                        line_style_e['width'] = 4
                    elif 'Neutral' in col:
                        line_style_e['dash'] = 'dash'
                        line_style_e['color'] = '#2ECC40'
                        line_style_e['width'] = 4
                    elif 'Balls' in col:
                        line_style_e['color'] = '#00E5FF'
                        line_style_e['width'] = 2
                        
                    fig_pnl_e.add_trace(go.Scatter(x=plot_df_e.index, y=plot_df_e[col], mode='lines+markers', name=col, line=line_style_e, marker=dict(size=8 if 'Conservative' in col else 6), hovertemplate=f"<b>{col}</b><br>%{{x|%b %d, %Y}}<br>$%{{y:,.2f}}<extra></extra>"))
                    
                if HAS_YF and len(plot_df_e) > 0:
                    try:
                        spy_e = yf.download('SPY', start=plot_df_e.index.min(), end=plot_df_e.index.max() + pd.Timedelta(days=1), progress=False)
                        if not spy_e.empty and len(plot_df_e.columns) > 0:
                            start_eq_e = plot_df_e.iloc[0, 0]
                            if isinstance(spy_e.columns, pd.MultiIndex):
                                spy_close_e = spy_e['Close']['SPY']
                            else:
                                spy_close_e = spy_e['Close']
                            norm_spy_e = spy_close_e / spy_close_e.iloc[0] * start_eq_e
                            norm_spy_e = norm_spy_e.reindex(plot_df_e.index).ffill().bfill()
                            fig_pnl_e.add_trace(go.Scatter(x=norm_spy_e.index, y=norm_spy_e, mode='lines+markers', name='S&P 500 (SPY)', line=dict(color='white', width=2, dash='solid'), hovertemplate="<b>S&P 500 (SPY)</b><br>%{x|%b %d, %Y}<br>$%{y:,.2f}<extra></extra>"))
                    except: pass
                        
                # --- Dynamic Y-Axis Padding ---
                y_min_e = plot_df_e.min().min()
                y_max_e = plot_df_e.max().max()
                
                if HAS_YF and 'norm_spy_e' in locals():
                    try:
                        y_min_e = min(y_min_e, norm_spy_e.min())
                        y_max_e = max(y_max_e, norm_spy_e.max())
                    except: pass
                    
                y_pad_e = (y_max_e - y_min_e) * 0.20 if (y_max_e - y_min_e) != 0 else abs(y_max_e) * 0.02
                
                # INVISIBLE ANCHORS TO FORCE Y-AXIS PADDING
                fig_pnl_e.add_trace(go.Scatter(x=[plot_df_e.index[0], plot_df_e.index[0]], y=[y_min_e - y_pad_e, y_max_e + y_pad_e], mode='markers', marker=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='skip'))
                
                fig_pnl_e.update_layout(
                    **STD_LAYOUT,
                    height=550,
                    xaxis=dict(rangeslider=dict(visible=True, thickness=0.08, bgcolor='#383838', bordercolor='#1E90FF', borderwidth=1)),
                    yaxis=dict(tickformat="$.2f")
                )
                st.plotly_chart(fig_pnl_e, use_container_width=True, key="pnl_portfolio_etf")
        else:
            df_etf = pd.read_excel(xls_etf, sheet_name=selected_etf, skiprows=2)
            if not df_etf.empty:
                latest_e = df_etf.iloc[-1]
                rec_e = latest_e.get('Recommendation', 'N/A')
                st.markdown(f"### Live Recommendation: **{rec_e}**")
                
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Probability P(UP)", f"{latest_e.get('Bayesian Probability P(UP)', 0)*100:.1f}%")
                
                mu_e = latest_e.get('Expected Return %', 0)
                sigma_e = latest_e.get('Expected Risk (Volatility) %', 1)
                exp_sharpe_e = (mu_e / sigma_e) if sigma_e and sigma_e != 0 else 0
                
                m2.metric("Expected Return", f"{mu_e*100:.2f}%")
                m3.metric("Expected Sharpe", f"{exp_sharpe_e:.2f}")
                m4.metric("Kelly Allocation", f"{latest_e.get('Kelly Optimal Allocation %', 0)*100:.1f}%")
                
                note_e = latest_e.get('Broker Override Note', '')
                if pd.notna(note_e) and note_e != "":
                    m5.error(note_e)
                else:
                    m5.success("Trade Cleared")
            
            if selected_etf != "Portfolio Overview":
                # 2. Distribution side by side with the trend line
                c_fig1_e, c_fig2_e = st.columns(2)
                with c_fig1_e:
                    mu_e = latest_e.get('Expected Return %', 0)
                    sigma_e = latest_e.get('Expected Risk (Volatility) %', 0)
                    fig_e = plot_bayesian_curve(mu_e, sigma_e, selected_etf)
                    if fig_e:
                        st.plotly_chart(fig_e, use_container_width=True, key="dist_etf")
                with c_fig2_e:
                    st.markdown("**Historical Predictions vs Actual Returns**")
                    try:
                        df_plot_e = df_etf[['Date', 'Expected Return %', 'Actual Daily Return %']].copy()
                        df_plot_e['Date'] = pd.to_datetime(df_plot_e['Date'])
                        
                        fig_line_e = go.Figure()
                        fig_line_e.add_trace(go.Scatter(x=df_plot_e['Date'], y=df_plot_e['Expected Return %'], mode='lines', line=dict(color='#FF851B', width=2), name='Expected (Orange)'))
                        fig_line_e.add_trace(go.Scatter(x=df_plot_e['Date'], y=df_plot_e['Actual Daily Return %'], mode='lines', line=dict(color='#1E90FF', width=2), name='Actual (Blue)'))
                        
                        y_min_e = min(df_plot_e['Expected Return %'].min(), df_plot_e['Actual Daily Return %'].min())
                        y_max_e = max(df_plot_e['Expected Return %'].max(), df_plot_e['Actual Daily Return %'].max())
                        y_pad_e = (y_max_e - y_min_e) * 0.20 if (y_max_e - y_min_e) != 0 else 0.02
                        
                        fig_line_e.update_layout(
                            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='white'),
                            margin=dict(t=10, b=10, l=10, r=10), height=380,
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                            yaxis=dict(range=[y_min_e - y_pad_e, y_max_e + y_pad_e], tickformat=".2%"),
                            xaxis=dict(rangeslider=dict(visible=True, thickness=0.08, bgcolor='#383838', bordercolor='#1E90FF', borderwidth=1))
                        )
                        st.plotly_chart(fig_line_e, use_container_width=True, key="line_etf")
                    except Exception as e:
                        pass
            
            # 3. Bottom Ledgers and PnL Race
            c_bot1_e, c_bot2_e = st.columns([1.2, 1])
            with c_bot1_e:
                t_ai_e, t_br_e, t_log_e = st.tabs(["🤖 AI Mathematical Ledger", f"💼 {persona_e_ui} Trade Ledger", "📜 Recent Execution Log"])
                with t_ai_e:
                    if not df_etf.empty:
                        disp_df_e = format_df_for_display(df_etf.iloc[::-1])
                        st.dataframe(disp_df_e.style.format(na_rep=''), use_container_width=True, height=250)
                with t_br_e:
                    if not df_etf_trial.empty:
                        p_cols_e = ['Date', 'Total_Equity', 'Cash', 'Daily_PnL_JSON', 'Holdings_JSON']
                        avail_cols_e = [c for c in p_cols_e if c in df_etf_trial.columns]
                        disp_trial_e = format_df_for_display(df_etf_trial[avail_cols_e].iloc[::-1])
                        st.dataframe(disp_trial_e.style.format(na_rep=''), use_container_width=True, height=250)
                    else:
                        st.info("No ETF broker trial data available.")
                with t_log_e:
                    if not df_etf_trial.empty:
                        recent_trades_e = get_recent_trades(df_etf_trial, persona_e_ui)
                        if recent_trades_e:
                            for trade in recent_trades_e:
                                st.markdown(f"**{trade}**")
                        else:
                            st.info("No recent trades detected.")
                    else:
                        st.info("No ETF broker trial data available.")
                        
            with c_bot2_e:
                if selected_etf == "Portfolio Overview":
                    st.markdown("**30-Day Multi-Broker ETF Race**")
                else:
                    st.markdown(f"**30-Day Multi-Broker Race: {selected_etf} Realized PnL**")
                    
                all_ledgers_e = []
                for p in ["Conservative", "Neutral", "BallsForBrains"]:
                    import sys
                    sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
                    import database_manager
                    import json
                    df_p = database_manager.get_ledger(f"ETF_{p}")
                    if not df_p.empty:
                        if 'Date' in df_p.columns:
                            df_p['Date'] = pd.to_datetime(df_p['Date'])
                            if selected_etf == "Portfolio Overview" and 'Total_Equity' in df_p.columns:
                                df_p = df_p[['Date', 'Total_Equity']].rename(columns={'Total_Equity': f'{p}'})
                                all_ledgers_e.append(df_p.set_index('Date'))
                            elif selected_etf != "Portfolio Overview" and 'Daily_PnL_JSON' in df_p.columns:
                                vals = []
                                for _, row in df_p.iterrows():
                                    v = 0.0
                                    try:
                                        j = json.loads(row['Daily_PnL_JSON'])
                                        v = float(j.get(selected_etf, 0.0))
                                    except: pass
                                    vals.append(v)
                                df_p[f'{p}'] = pd.Series(vals).cumsum()
                                df_p = df_p[['Date', f'{p}']]
                                all_ledgers_e.append(df_p.set_index('Date'))
                
                if all_ledgers_e:
                    plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()
                    plot_df_e = plot_df_e[plot_df_e.index >= (pd.Timestamp.now() - pd.Timedelta(days=35))]
                    
                    fig_pnl_e = go.Figure()
                    for col in plot_df_e.columns:
                        line_style_e = dict(width=2)
                        if 'Conservative' in col:
                            line_style_e['dash'] = 'dot'
                            line_style_e['color'] = '#FF851B'
                            line_style_e['width'] = 4
                        elif 'Neutral' in col:
                            line_style_e['dash'] = 'dash'
                            line_style_e['color'] = '#2ECC40'
                            line_style_e['width'] = 4
                        elif 'Balls' in col:
                            line_style_e['color'] = '#00E5FF'
                            line_style_e['width'] = 2
                            
                        # Standard smooth lines!
                        fig_pnl_e.add_trace(go.Scatter(x=plot_df_e.index, y=plot_df_e[col], mode='lines+markers', name=col, line=line_style_e, marker=dict(size=8 if 'Conservative' in col else 6), hovertemplate=f"<b>{col}</b><br>%{{x|%b %d, %Y}}<br>$%{{y:,.2f}}<extra></extra>"))
                        
                    if selected_etf == "Portfolio Overview" and HAS_YF and len(plot_df_e) > 0:
                        try:
                            spy_e = yf.download('SPY', start=plot_df_e.index.min(), end=plot_df_e.index.max() + pd.Timedelta(days=1), progress=False)
                            if not spy_e.empty and len(plot_df_e.columns) > 0:
                                start_eq_e = plot_df_e.iloc[0, 0]
                                if isinstance(spy_e.columns, pd.MultiIndex):
                                    spy_close_e = spy_e['Close']['SPY']
                                else:
                                    spy_close_e = spy_e['Close']
                                norm_spy_e = spy_close_e / spy_close_e.iloc[0] * start_eq_e
                                norm_spy_e = norm_spy_e.reindex(plot_df_e.index).ffill().bfill()
                                fig_pnl_e.add_trace(go.Scatter(x=norm_spy_e.index, y=norm_spy_e, mode='lines+markers', name='S&P 500 (SPY)', line=dict(color='white', width=2, dash='solid'), hovertemplate="<b>S&P 500 (SPY)</b><br>%{x|%b %d, %Y}<br>$%{y:,.2f}<extra></extra>"))
                        except: pass
                            
                    fig_pnl_e.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='white'),
                        margin=dict(t=10, b=10, l=10, r=10), height=320,
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        xaxis=dict(rangeslider=dict(visible=True, thickness=0.08, bgcolor='#383838', bordercolor='#1E90FF', borderwidth=1)),
                        hoverlabel=dict(bgcolor="#2A2A2A", font_size=12, font_family="sans-serif", font_color="white")
                    )
                    st.plotly_chart(fig_pnl_e, use_container_width=True, key="pnl_etf_multi")
                else:
                    st.markdown(f"**30-Day {selected_etf} Realized PnL**")
                    if not df_etf_trial.empty and 'Daily_PnL_JSON' in df_etf_trial.columns and 'Date' in df_etf_trial.columns:
                        import json
                        df_etf_trial['Date'] = pd.to_datetime(df_etf_trial['Date'])
                        plot_df_e = df_etf_trial.copy()
                        plot_df_e = plot_df_e[plot_df_e['Date'] >= (pd.Timestamp.now() - pd.Timedelta(days=35))]
                        
                        etf_pnls = []
                        for _, row in plot_df_e.iterrows():
                            val = 0.0
                            try:
                                j = json.loads(row['Daily_PnL_JSON'])
                                val = float(j.get(selected_etf, 0.0))
                            except: pass
                            etf_pnls.append(val)
                            
                        plot_df_e['Stock_PnL'] = etf_pnls
                        plot_df_e['Cum_PnL'] = plot_df_e['Stock_PnL'].cumsum()
                        plot_df_e = plot_df_e.set_index('Date')
                        
                        fig_pnl_e = go.Figure()
                        fig_pnl_e.add_trace(go.Scatter(x=plot_df_e.index, y=plot_df_e['Stock_PnL'], mode='lines+markers', line=dict(color='#FFDC00', width=2), name='Daily PnL', marker=dict(size=6), hovertemplate="<b>Daily PnL</b><br>%{x|%b %d, %Y}<br>$%{y:,.2f}<extra></extra>"))
                        fig_pnl_e.add_trace(go.Scatter(x=plot_df_e.index, y=plot_df_e['Cum_PnL'], mode='lines+markers', line=dict(color='#B10DC9', width=4), name='Cumulative PnL', marker=dict(size=8), hovertemplate="<b>Cumulative PnL</b><br>%{x|%b %d, %Y}<br>$%{y:,.2f}<extra></extra>"))
                        
                        y_min_e = min(plot_df_e['Stock_PnL'].min(), plot_df_e['Cum_PnL'].min())
                        y_max_e = max(plot_df_e['Stock_PnL'].max(), plot_df_e['Cum_PnL'].max())
                        y_pad_e = (y_max_e - y_min_e) * 0.20 if (y_max_e - y_min_e) != 0 else abs(y_max_e) * 0.02
                        
                        # INVISIBLE ANCHORS TO FORCE Y-AXIS PADDING
                        fig_pnl_e.add_trace(go.Scatter(x=[plot_df_e.index[0], plot_df_e.index[0]], y=[y_min_e - y_pad_e, y_max_e + y_pad_e], mode='markers', marker=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='skip'))
                        
                        fig_pnl_e.update_layout(
                            **STD_LAYOUT,
                            height=550,
                            xaxis=dict(rangeslider=dict(visible=True, thickness=0.08, bgcolor='#383838', bordercolor='#1E90FF', borderwidth=1)),
                            yaxis=dict(tickformat="$.2f")
                        )
                        st.plotly_chart(fig_pnl_e, use_container_width=True, key="pnl_etf_single_new")

# --- VIEW 3: TICKER POPULATION OLYMPIC ---
with tab3:
    st.markdown("<h2 style='text-align: center; color: #FFD700;'>🏆 30-Day Walk-Forward Bayesian Olympics</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Comparing the actual simulated PnL performance of different S&P 500 feature extractions.</p>", unsafe_allow_html=True)

    # --- ETA TIMER LOGIC ---
    import calendar
    import datetime
    import streamlit.components.v1 as components
    
    now = datetime.datetime.now()
    days_ahead = 5 - now.weekday() # Saturday is 5
    if days_ahead <= 0:
        days_ahead += 7
    next_sat = now + datetime.timedelta(days=days_ahead)
    run_time = next_sat.replace(hour=14, minute=0, second=0, microsecond=0)
    expected_finish = run_time + datetime.timedelta(hours=4.5)
    
    if now > expected_finish:
        expected_finish = expected_finish + datetime.timedelta(days=7)
        
    js_date_str = expected_finish.strftime("%b %d, %Y %H:%M:%S")
    display_date_str = expected_finish.strftime("%A, %B %d, %Y @ %I:%M %p")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    components.html(f"""
        <div style='display: flex; justify-content: center; align-items: center; gap: 40px; padding: 10px;'>
            
            <!-- CARD 1: Finish Date -->
            <div style='background: linear-gradient(145deg, #1e1e24 0%, #2a2a35 100%); 
                        border-top: 4px solid #9b59b6; 
                        border-radius: 12px; 
                        padding: 20px 30px; 
                        box-shadow: 0 8px 16px rgba(0,0,0,0.4); 
                        text-align: center;'>
                <div style='font-size: 12px; color: #a0a0b0; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px; font-family: sans-serif;'>Next Scheduled Olympic Run</div>
                <div style='color: white; font-family: sans-serif; font-size: 22px; font-weight: bold;'>
                    📅 {display_date_str}
                </div>
            </div>
            
            <!-- CARD 2: Live Countdown -->
            <div style='background: linear-gradient(145deg, #1e1e24 0%, #2a2a35 100%); 
                        border-top: 4px solid #ff4b4b; 
                        border-radius: 12px; 
                        padding: 20px 30px; 
                        box-shadow: 0 8px 16px rgba(0,0,0,0.4); 
                        text-align: center;
                        min-width: 250px;'>
                <div style='font-size: 12px; color: #a0a0b0; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px; font-family: sans-serif;'>Time Remaining</div>
                <div style='color: #ff4b4b; font-family: sans-serif; font-size: 22px; font-weight: bold;'>
                    ⏳ <span id='timer'></span>
                </div>
            </div>
            
        </div>
        <script>
        var countDownDate = new Date("{js_date_str}").getTime();
        var x = setInterval(function() {{
          var now = new Date().getTime();
          var distance = countDownDate - now;
          if (distance < 0) {{
            clearInterval(x);
            document.getElementById("timer").innerHTML = "0h 0m 0s (Running...)";
          }} else {{
            var days = Math.floor(distance / (1000 * 60 * 60 * 24));
            var hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            var minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
            var seconds = Math.floor((distance % (1000 * 60)) / 1000);
            
            var disp = "";
            if (days > 0) disp += days + "d ";
            disp += hours + "h " + minutes + "m " + seconds + "s";
            document.getElementById("timer").innerHTML = disp;
          }}
        }}, 1000);
        </script>
    """, height=150)
    
    st.markdown("<br><hr>", unsafe_allow_html=True)

    
    cap_path = os.path.join(BASE_DIR, 'Backtest_Ledger_EL_CAP.csv')
    vol_path = os.path.join(BASE_DIR, 'Backtest_Ledger_EL_VOLTI.csv')
    champ_path = os.path.join(BASE_DIR, 'Backtest_Ledger_CHAMPION.csv')
    
    if os.path.exists(cap_path) and os.path.exists(vol_path) and os.path.exists(champ_path):
        df_cap = pd.read_csv(cap_path)
        df_vol = pd.read_csv(vol_path)
        df_champ = pd.read_csv(champ_path)
        
        # Merge on date
        df_merged = df_cap[['Date', 'Equity']].rename(columns={'Equity': 'EL_CAP (70% Liquidity)'})
        df_merged = df_merged.merge(df_vol[['Date', 'Equity']].rename(columns={'Equity': 'EL_VOLTI (70% Stability)'}), on='Date', how='inner')
        df_merged = df_merged.merge(df_champ[['Date', 'Equity']].rename(columns={'Equity': 'CHAMPION (Live VIP)'}), on='Date', how='inner')
        
        df_merged['Date'] = pd.to_datetime(df_merged['Date'])
        df_merged = df_merged.set_index('Date')
        
        # --- THE PNL RACE CHART ---
        st.markdown("### 🏎️ Population PnL Race")
        fig_oly = go.Figure()
        
        # --- Dynamic Medal Ranking ---
        final_eq = df_merged.iloc[-1]
        ranks = final_eq.rank(method='min', ascending=False)
        def get_medal(r):
            if r == 1: return " <span style='font-size:24px; text-shadow: 0 0 10px #FFD700, 0 0 20px #FFD700;'>🏅</span>"
            elif r == 2: return " <span style='font-size:24px; text-shadow: 0 0 5px #C0C0C0;'>🥈</span>"
            elif r == 3: return " <span style='font-size:24px; text-shadow: 0 0 5px #CD7F32;'>🥉</span>"
            return ""
            
        name_cap = 'EL_CAP (Liquidity)' + get_medal(ranks['EL_CAP (70% Liquidity)'])
        name_vol = 'EL_VOLTI (Stability)' + get_medal(ranks['EL_VOLTI (70% Stability)'])
        name_champ = 'CHAMPION (VIP)' + get_medal(ranks['CHAMPION (Live VIP)'])

        # 1. EL_CAP
        fig_oly.add_trace(go.Scatter(x=df_merged.index, y=df_merged['EL_CAP (70% Liquidity)'], mode='lines', line=dict(color='#FF851B', width=8, dash='dot'), name=name_cap))
        # 2. EL_VOLTI
        fig_oly.add_trace(go.Scatter(x=df_merged.index, y=df_merged['EL_VOLTI (70% Stability)'], mode='lines', line=dict(color='#2ECC40', width=5, dash='dash'), name=name_vol))
        # 3. CHAMPION
        fig_oly.add_trace(go.Scatter(x=df_merged.index, y=df_merged['CHAMPION (Live VIP)'], mode='lines+markers', line=dict(color='#00E5FF', width=2), name=name_champ, marker=dict(size=6)))
        
        if HAS_YF:
            try:
                spy_oly = yf.download('SPY', start=df_merged.index.min(), end=df_merged.index.max() + pd.Timedelta(days=1), progress=False)
                if not spy_oly.empty:
                    start_eq_o = df_merged.iloc[0, 0]
                    if isinstance(spy_oly.columns, pd.MultiIndex):
                        spy_c = spy_oly['Close']['SPY']
                    else:
                        spy_c = spy_oly['Close']
                    norm_spy_o = spy_c / spy_c.iloc[0] * start_eq_o
                    norm_spy_o = norm_spy_o.reindex(df_merged.index).ffill().bfill()
                    fig_oly.add_trace(go.Scatter(x=norm_spy_o.index, y=norm_spy_o, mode='lines', line=dict(color='white', width=1, dash='solid'), name='S&P 500'))
            except: pass
            
        # --- Dynamic Y-Axis Padding ---
        y_cols = ['EL_CAP (70% Liquidity)', 'EL_VOLTI (70% Stability)', 'CHAMPION (Live VIP)']
        y_min = df_merged[y_cols].min().min()
        y_max = df_merged[y_cols].max().max()
        
        if HAS_YF and 'norm_spy_o' in locals():
            try:
                y_min = min(y_min, norm_spy_o.min())
                y_max = max(y_max, norm_spy_o.max())
            except: pass
            
        y_pad = (y_max - y_min) * 0.20 if (y_max - y_min) != 0 else abs(y_max) * 0.02
        
        # INVISIBLE ANCHORS TO FORCE Y-AXIS PADDING
        fig_oly.add_trace(go.Scatter(x=[df_merged.index[0], df_merged.index[0]], y=[y_min - y_pad, y_max + y_pad], mode='markers', marker=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='skip'))
        
        fig_oly.update_layout(
            **STD_LAYOUT,
            height=600,
            yaxis=dict(tickformat="$.2f"),
            xaxis=dict(rangeslider=dict(visible=True, thickness=0.08, bgcolor='#383838', bordercolor='#1E90FF', borderwidth=1))
        )
        st.plotly_chart(fig_oly, use_container_width=True, key="pnl_olympic")
        
        # --- THE KPI SCOREBOARD ---
        st.markdown("### 📊 Olympic Scoreboard")
        c_o1, c_o2, c_o3 = st.columns(3)
        
        def calc_o_metrics(df, col):
            eq = df[col].values
            ret = (eq[-1] - eq[0]) / eq[0] * 100
            peak = df[col].cummax()
            dd = (df[col] - peak) / peak * 100
            max_dd = dd.min()
            return ret, max_dd
            
        r_c, d_c = calc_o_metrics(df_merged, 'EL_CAP (70% Liquidity)')
        with c_o1:
            st.metric("EL_CAP Return", f"{r_c:+.2f}%")
            st.metric("EL_CAP Max DD", f"{d_c:.2f}%")
            
        r_v, d_v = calc_o_metrics(df_merged, 'EL_VOLTI (70% Stability)')
        with c_o2:
            st.metric("EL_VOLTI Return", f"{r_v:+.2f}%")
            st.metric("EL_VOLTI Max DD", f"{d_v:.2f}%")
            
        r_ch, d_ch = calc_o_metrics(df_merged, 'CHAMPION (Live VIP)')
        with c_o3:
            st.metric("🏆 CHAMPION Return", f"{r_ch:+.2f}%")
            st.metric("🏆 CHAMPION Max DD", f"{d_ch:.2f}%")
            
        disp_merged = format_df_for_display(df_merged.iloc[::-1])
        st.dataframe(disp_merged.style.format(na_rep=''), use_container_width=True)
    else:
        st.info("Olympic Backtest ledgers are currently being generated in the background. Please check the ETA timer in the sidebar to see when the race will begin!")

# --- VIEW 4: TRADE AUTOPSY ---
with tab4:
    st.markdown("<h2 style='text-align: center;'>🏥 Trade Autopsy (Failure Pattern Analytics)</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Forensic cross-referencing of capitalized losses against historical PyMC predictions.</p>", unsafe_allow_html=True)
    
    c_auto1, c_auto2, c_auto3 = st.columns([1, 2, 1])
    with c_auto2:
        col_p, col_m = st.columns(2)
        with col_p:
            auto_persona_ui = st.selectbox("Select Target Persona", ["Conservative", "Neutral", "BallsForBrains", "Dynamic Sharpe"], index=3, key="auto_persona")
            auto_persona = "Dynamic" if auto_persona_ui == "Dynamic Sharpe" else auto_persona_ui
        with col_m:
            auto_mode = st.selectbox("Select Market Sector", ["Single Stocks", "ETFs"], index=0, key="auto_mode")
            auto_mode_val = "Single" if auto_mode == "Single Stocks" else "ETF"
            
    st.markdown("---")
    
    trades_df, offenders_df = get_losing_trades(persona=auto_persona, mode=auto_mode_val)
    
    if trades_df.empty:
        st.success(f"No losing trades found for {auto_persona} ({auto_mode}). The ledger is perfectly clean.")
    else:
        # Row 1: High Level Metrics
        col_metric1, col_metric2, col_metric3, col_metric4 = st.columns(4)
        
        total_lost = abs(trades_df['Realized Loss ($)'].sum())
        worst_loss = abs(trades_df['Realized Loss ($)'].min())
        worst_asset = offenders_df.iloc[0]['Asset'] if not offenders_df.empty else "N/A"
        worst_day = trades_df['Day of Week'].value_counts().index[0] if not trades_df.empty else "N/A"
        
        col_metric1.metric("Total Capital Bled", f"-${total_lost:,.2f}")
        col_metric2.metric("Maximum Single Loss", f"-${worst_loss:,.2f}")
        col_metric3.metric("Serial Offender (Asset)", worst_asset)
        col_metric4.metric("Most Vulnerable Day", worst_day)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Row 2: Charts
        col_ch1, col_ch2 = st.columns([1.5, 1])
        with col_ch1:
            st.markdown("### 🧨 Serial Offenders (Cumulative Losses)")
            if not offenders_df.empty:
                import plotly.express as px
                fig_offenders = px.bar(
                    offenders_df.head(10), 
                    x='Cumulative Loss ($)', 
                    y='Asset', 
                    orientation='h',
                    color='Cumulative Loss ($)',
                    color_continuous_scale='Reds_r'
                )
                fig_offenders.update_layout(**STD_LAYOUT, xaxis_title="Capital Lost ($)", yaxis_title="Asset")
                st.plotly_chart(fig_offenders, use_container_width=True, key="auto_offenders")
                
        with col_ch2:
            st.markdown("### 📅 Day of Week Vulnerability")
            if not trades_df.empty:
                import plotly.express as px
                day_counts = trades_df['Day of Week'].value_counts().reindex(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']).fillna(0)
                fig_days = px.bar(
                    x=day_counts.index, 
                    y=day_counts.values,
                    color=day_counts.values,
                    color_continuous_scale='Reds'
                )
                fig_days.update_layout(**STD_LAYOUT, xaxis_title="", yaxis_title="Number of Losing Trades")
                st.plotly_chart(fig_days, use_container_width=True, key="auto_days")
                
        # Row 3: The Raw Forensic Ledger
        st.markdown("---")
        st.markdown("### Forensic Autopsy Ledger")
        st.markdown("Cross-referenced with the Bayesian PyMC prediction cast the day *before* the loss.")
        
        disp_trades = format_df_for_display(trades_df)
        st.dataframe(disp_trades.style.format(na_rep='N/A'), use_container_width=True, height=400)
