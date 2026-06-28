import pandas as pd
import numpy as np
import os

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'
OUTPUT_EXCEL = os.path.join(BASE_DIR, 'ETF_Broker_30Day_Trial.xlsx')
PERSONAS = ["Conservative", "Neutral", "Balls For Brain"]

def process_ledger(persona_name):
    file_persona = "BallsForBrains" if persona_name == "Balls For Brain" else persona_name
    path = os.path.join(BASE_DIR, f'ETF_Capital_Ledger_{file_persona}.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
        
    df = pd.read_csv(path)
    # Ensure Date is datetime
    df['Date'] = pd.to_datetime(df['Date'])
    
    # Calculate Profits
    df['Prev_Equity'] = df['Total_Equity'].shift(1)
    df['Prev_Equity'] = df['Prev_Equity'].fillna(10000.0) # Starting amount
    
    df[f'{persona_name}_Daily_Profit_$'] = df['Total_Equity'] - df['Prev_Equity']
    df[f'{persona_name}_Daily_Profit_%'] = (df[f'{persona_name}_Daily_Profit_$'] / df['Prev_Equity'])
    
    df['Prev_Holdings_JSON'] = df['Holdings_JSON'].shift(1).fillna('{}')
    
    import json
    def format_action(row):
        try:
            curr = json.loads(row['Holdings_JSON']) if isinstance(row['Holdings_JSON'], str) else {}
        except:
            curr = {}
        try:
            prev = json.loads(row['Prev_Holdings_JSON']) if isinstance(row['Prev_Holdings_JSON'], str) else {}
        except:
            prev = {}
            
        all_tickers = set(curr.keys()).union(set(prev.keys()))
        if not all_tickers:
            return "Cash Only"
            
        actions = []
        for t in sorted(all_tickers):
            item_curr = curr.get(t, {})
            item_prev = prev.get(t, {})
            
            if isinstance(item_curr, dict):
                v_curr = item_curr.get("dollars", 0.0)
                u_curr = item_curr.get("units", 0)
                p_curr = item_curr.get("price", 0.0)
            else:
                v_curr = float(item_curr) if item_curr else 0.0
                u_curr = 0
                p_curr = 0.0
                
            if isinstance(item_prev, dict):
                v_prev = item_prev.get("dollars", 0.0)
                u_prev = item_prev.get("units", 0)
                p_prev = item_prev.get("price", 0.0)
            else:
                v_prev = float(item_prev) if item_prev else 0.0
                u_prev = 0
                p_prev = 0.0
            
            if v_curr > 0 and v_prev == 0:
                if u_curr > 0:
                    actions.append(f"[BUY] {t}: {u_curr} units @ ${p_curr:.2f} = ${v_curr:,.2f}")
                else:
                    actions.append(f"[BUY] {t}: ${v_curr:,.2f}")
            elif v_curr > 0 and v_prev > 0:
                actions.append(f"[HOLD] {t}: $0.00")
            elif v_curr == 0 and v_prev > 0:
                if u_prev > 0:
                    actions.append(f"[SELL] {t}: {u_prev} units @ ${p_prev:.2f} = -${v_prev:,.2f}")
                else:
                    actions.append(f"[SELL] {t}: -${v_prev:,.2f}")
                
        if not actions:
            return "Cash Only"
        return " | ".join(actions)
            
    df['Formatted_Holdings'] = df.apply(format_action, axis=1)
    
    # Rename for merging
    df = df.rename(columns={
        'Cash': f'{persona_name}_Cash',
        'Total_Equity': f'{persona_name}_Total_Equity',
        'Formatted_Holdings': f'{persona_name}_Holdings'
    })
    
    # Drop Prev_Equity, but keep Daily_PnL_JSON if it exists for summary
    df = df.drop(columns=['Prev_Equity', 'Holdings_JSON', 'Prev_Holdings_JSON'])
    return df

def generate_excel():
    print("=== GENERATING 30-DAY TRIAL EXCEL REPORT ===")
    
    # 1. Merge all ledgers
    merged_df = None
    ticker_stats = []
    for p in PERSONAS:
        df_p = process_ledger(p)
        if df_p.empty:
            print(f"Warning: Ledger for {p} not found.")
            continue
            
        if merged_df is None:
            merged_df = df_p
        else:
            merged_df = pd.merge(merged_df, df_p, on='Date', how='outer')
            
        # Parse raw ledger for Ticker Summary
        file_p = "BallsForBrains" if p == "Balls For Brain" else p
        path = os.path.join(BASE_DIR, f'ETF_Capital_Ledger_{file_p}.csv')
        if os.path.exists(path):
            raw_df = pd.read_csv(path)
            has_settled_trades = False
            
            if 'Daily_PnL_JSON' in raw_df.columns:
                pnl_dict = {}
                import json
                for _, row in raw_df.iterrows():
                    try:
                        pnl_json = json.loads(row['Daily_PnL_JSON']) if isinstance(row['Daily_PnL_JSON'], str) else {}
                        for t, val in pnl_json.items():
                            pnl_dict[t] = pnl_dict.get(t, 0.0) + float(val)
                            has_settled_trades = True
                    except:
                        pass
                for t, total_pnl in pnl_dict.items():
                    ticker_stats.append({
                        'Persona': p,
                        'Ticker': t,
                        'Total Profit $': total_pnl
                    })
                    
            if not has_settled_trades:
                # Day 1 fallback: show current holdings with Pending profit
                try:
                    last_row = raw_df.iloc[-1]
                    holdings = json.loads(last_row['Holdings_JSON']) if isinstance(last_row['Holdings_JSON'], str) else {}
                    if not holdings:
                        ticker_stats.append({'Persona': p, 'Ticker': 'Cash Only', 'Total Profit $': 'Pending'})
                    else:
                        for t in holdings.keys():
                            ticker_stats.append({'Persona': p, 'Ticker': t, 'Total Profit $': 'Pending'})
                except:
                    ticker_stats.append({'Persona': p, 'Ticker': 'Cash Only', 'Total Profit $': 'Pending'})
            
    if merged_df is None or merged_df.empty:
        print("No ledger data to export!")
        return

    merged_df = merged_df.sort_values('Date').reset_index(drop=True)
    
    # Reorder columns logically
    cols = ['Date']
    for p in PERSONAS:
        cols.extend([
            f'{p}_Total_Equity',
            f'{p}_Daily_Profit_$',
            f'{p}_Daily_Profit_%',
            f'{p}_Cash',
            f'{p}_Holdings'
        ])
    merged_df = merged_df[cols]
    
    # 2. Create Weekly Summary
    # Group every 5 trading days
    merged_df['Week'] = (merged_df.index // 5) + 1
    weekly_summary = []
    
    for week_num, group in merged_df.groupby('Week'):
        first_day = group.iloc[0]
        last_day = group.iloc[-1]
        
        week_row = {
            'Week': f"Week {week_num}",
            'Start Date': first_day['Date'].strftime('%Y-%m-%d'),
            'End Date': last_day['Date'].strftime('%Y-%m-%d')
        }
        
        for p in PERSONAS:
            start_eq = 10000.0 if week_num == 1 else merged_df.loc[merged_df.index[0] + (week_num-1)*5 - 1, f'{p}_Total_Equity']
            end_eq = last_day[f'{p}_Total_Equity']
            profit_dollar = end_eq - start_eq
            profit_pct = (profit_dollar / start_eq) if start_eq > 0 else 0
            
            week_row[f'{p} End Equity'] = end_eq
            week_row[f'{p} Weekly Profit $'] = profit_dollar
            week_row[f'{p} Weekly Profit %'] = profit_pct
            
        weekly_summary.append(week_row)
        
    weekly_df = pd.DataFrame(weekly_summary)
    
    # 3. Write to Excel with Formatting and Charts
    writer = pd.ExcelWriter(OUTPUT_EXCEL, engine='xlsxwriter')
    
    # Sheet 1: Daily Tracking
    merged_df['Date'] = merged_df['Date'].dt.strftime('%Y-%m-%d')
    merged_df.drop(columns=['Week']).to_excel(writer, sheet_name='Daily Tracking', index=False)
    
    # Format Sheet 1
    workbook = writer.book
    worksheet1 = writer.sheets['Daily Tracking']
    
    money_fmt = workbook.add_format({'num_format': '$#,##0.00'})
    pct_fmt = workbook.add_format({'num_format': '0.00%'})
    
    # Write headers manually to apply colors
    header_fmt_base = {'bold': True, 'border': 1, 'align': 'center', 'valign': 'vcenter'}
    
    fmt_date = workbook.add_format({**header_fmt_base, 'bg_color': '#D9D9D9'})
    fmt_conservative = workbook.add_format({**header_fmt_base, 'bg_color': '#C6E0B4', 'font_color': '#375623'}) # Green
    fmt_neutral = workbook.add_format({**header_fmt_base, 'bg_color': '#B4C6E7', 'font_color': '#1F497D'}) # Blue
    fmt_balls = workbook.add_format({**header_fmt_base, 'bg_color': '#F4B084', 'font_color': '#833C0C'}) # Red
    
    worksheet1.write(0, 0, 'Date', fmt_date)
    
    col_idx = 1
    for p, fmt in zip(PERSONAS, [fmt_conservative, fmt_neutral, fmt_balls]):
        for col_name in [f'{p}_Total_Equity', f'{p}_Daily_Profit_$', f'{p}_Daily_Profit_%', f'{p}_Cash', f'{p}_Holdings']:
            worksheet1.write(0, col_idx, col_name, fmt)
            col_idx += 1
            
    # Apply column formats based on names
    for col_num, col_name in enumerate(merged_df.drop(columns=['Week']).columns):
        if 'Equity' in col_name or 'Cash' in col_name or 'Profit_$' in col_name:
            worksheet1.set_column(col_num, col_num, 15, money_fmt)
        elif 'Profit_%' in col_name:
            worksheet1.set_column(col_num, col_num, 12, pct_fmt)
        elif 'Holdings' in col_name:
            worksheet1.set_column(col_num, col_num, 40)
        else:
            worksheet1.set_column(col_num, col_num, 12)
            
    # Add Equity Line Chart to Daily Tracking
    chart = workbook.add_chart({'type': 'line'})
    max_row = len(merged_df)
    
    colors = ['#1F497D', '#4F81BD', '#C0504D'] # Blue, Light Blue, Red
    
    for idx, p in enumerate(PERSONAS):
        col_idx = cols.index(f'{p}_Total_Equity')
        chart.add_series({
            'name':       p,
            'categories': ['Daily Tracking', 1, 0, max_row, 0],
            'values':     ['Daily Tracking', 1, col_idx, max_row, col_idx],
            'line':       {'color': colors[idx], 'width': 2.25},
        })
        
    chart.set_title ({'name': '30-Day Multi-Persona Equity Race'})
    chart.set_x_axis({'name': 'Date'})
    chart.set_y_axis({'name': 'Total Equity ($)', 'num_format': '$#,##0'})
    chart.set_size({'width': 800, 'height': 400})
    
    # Insert chart to the right of the data
    worksheet1.insert_chart('Q2', chart)
    
    # Sheet 2: Weekly Summary
    weekly_df.to_excel(writer, sheet_name='Weekly Summary', index=False)
    worksheet2 = writer.sheets['Weekly Summary']
    
    # Write Weekly headers manually for colors
    worksheet2.write(0, 0, 'Week', fmt_date)
    worksheet2.write(0, 1, 'Start Date', fmt_date)
    worksheet2.write(0, 2, 'End Date', fmt_date)
    
    w_col = 3
    for p, fmt in zip(PERSONAS, [fmt_conservative, fmt_neutral, fmt_balls]):
        for col_name in [f'{p} End Equity', f'{p} Weekly Profit $', f'{p} Weekly Profit %']:
            worksheet2.write(0, w_col, col_name, fmt)
            w_col += 1
            
    # Apply column formatting for Weekly Summary data
    for col_num, col_name in enumerate(weekly_df.columns):
        if 'Equity' in col_name or 'Profit $' in col_name:
            worksheet2.set_column(col_num, col_num, 15, money_fmt)
        elif 'Profit %' in col_name:
            worksheet2.set_column(col_num, col_num, 15, pct_fmt)
        else:
            worksheet2.set_column(col_num, col_num, 12)

    # Sheet 3: Ticker Summary
    if not ticker_stats:
        ticker_stats = [{'Persona': 'Pending (No Settled Trades Yet)', 'Ticker': '-', 'Total Profit $': 0.0}]
        
    ticker_df = pd.DataFrame(ticker_stats)
    try:
        ticker_df = ticker_df.sort_values(['Persona', 'Total Profit $'], ascending=[True, False])
    except:
        ticker_df = ticker_df.sort_values(['Persona'])
        
    ticker_df.to_excel(writer, sheet_name='Ticker Summary', index=False)
    worksheet3 = writer.sheets['Ticker Summary']
        
    worksheet3.write(0, 0, 'Persona', fmt_date)
    worksheet3.write(0, 1, 'Ticker', fmt_date)
    worksheet3.write(0, 2, 'Total Profit $', fmt_date)
    
    for col_num, col_name in enumerate(ticker_df.columns):
        if 'Profit' in col_name:
            worksheet3.set_column(col_num, col_num, 15, money_fmt)
        else:
            worksheet3.set_column(col_num, col_num, 15)
            
    last_row3 = len(ticker_df) + 1
    worksheet3.conditional_format(f'A2:A{last_row3}', {'type': 'cell', 'criteria': '==', 'value': '"Conservative"', 'format': fmt_conservative})
    worksheet3.conditional_format(f'A2:A{last_row3}', {'type': 'cell', 'criteria': '==', 'value': '"Neutral"', 'format': fmt_neutral})
    worksheet3.conditional_format(f'A2:A{last_row3}', {'type': 'cell', 'criteria': '==', 'value': '"Balls For Brain"', 'format': fmt_balls})

    writer.close()
    print(f"Successfully generated: {OUTPUT_EXCEL}")

if __name__ == '__main__':
    generate_excel()
