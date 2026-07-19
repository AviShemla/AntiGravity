import yfinance as yf
import pandas as pd
import numpy as np
import time
import os
import pytz
import json
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==========================================
# INDICATOR UTILS
# ==========================================

def calculate_vwap(df):
    """Calculate VWAP from a dataframe of 1m candles."""
    if df.empty or 'Volume' not in df.columns: return 0.0
    df['TP'] = (df['High'] + df['Low'] + df['Close']) / 3
    df['TPV'] = df['TP'] * df['Volume']
    cum_vol = df['Volume'].sum()
    if cum_vol == 0: return df['Close'].iloc[-1]
    return df['TPV'].sum() / cum_vol

def get_yesterday_metrics(ticker):
    """Calculate Yesterday's Close and Yesterday's Intraday VWAP."""
    try:
        # Pull 2 days of 1-minute data to get yesterday's full intraday profile
        df_1m = yf.download(ticker, period="5d", interval="1m", progress=False)
        if df_1m.empty: return None, None
        
        if isinstance(df_1m.columns, pd.MultiIndex):
            df_1m.columns = df_1m.columns.droplevel(1)
            
        df_1m = df_1m.reset_index()
        df_1m['Date_Only'] = df_1m['Datetime'].dt.date
        
        # Get unique dates and pick the second to last one (Yesterday)
        unique_dates = df_1m['Date_Only'].unique()
        if len(unique_dates) < 2: return None, None
        
        yesterday_date = unique_dates[-2]
        yesterday_df = df_1m[df_1m['Date_Only'] == yesterday_date].copy()
        
        yest_close = yesterday_df['Close'].iloc[-1]
        yest_vwap = calculate_vwap(yesterday_df)
        
        return yest_close, yest_vwap
    except:
        return None, None

def get_live_metrics(ticker):
    """Get the absolute latest live asking price (last 1m candle close)."""
    try:
        df_1m = yf.download(ticker, period="1d", interval="1m", progress=False)
        if df_1m.empty: return None
        if isinstance(df_1m.columns, pd.MultiIndex):
            df_1m.columns = df_1m.columns.droplevel(1)
        return df_1m['Close'].iloc[-1]
    except:
        return None

# ==========================================
# EXECUTION LOGIC
# ==========================================

def execute_pending_orders(is_eod_fallback=False):
    """
    Scans Pending_Orders.json.
    For each persona, it checks the target holdings (the BUYS).
    If a BUY target meets the Momentum criteria, it executes it and commits to the ledger.
    If is_eod_fallback=True, it permanently aborts unmet trades, logs HOLD, and commits to ledger.
    """
    pending_path = os.path.join(BASE_DIR, 'financial_data', 'Pending_Orders.json')
    if not os.path.exists(pending_path):
        return
        
    with open(pending_path, 'r') as f:
        try:
            pending_orders = json.load(f)
        except:
            return
            
    if not pending_orders:
        return
        
    # We will track which personas we fully completed so we can remove them from pending
    completed_personas = []
    
    for persona, state in pending_orders.items():
        ledger_path = state['Ledger_Path']
        target_holdings = state['Target_Holdings']
        
        # Load the CURRENT active portfolio from the ledger to see what we already own
        if not os.path.exists(ledger_path): continue
        ledger = pd.read_csv(ledger_path)
        if ledger.empty: continue
        
        last_ledger_row = ledger.iloc[-1]
        current_holdings = json.loads(last_ledger_row['Holdings_JSON'])
        
        # Find which tickers are NEW BUYS (in target but not in current)
        new_buys = [t for t in target_holdings.keys() if t not in current_holdings]
        
        # Find which tickers are HELD (in target AND in current)
        held_tickers = [t for t in target_holdings.keys() if t in current_holdings]
        
        # Find which tickers are PENDING SELLS (in current but not in target)
        pending_sells = [t for t in current_holdings.keys() if t not in target_holdings]
        
        approved_buys = {} # Map of ticker -> live_price
        aborted_buys = []
        approved_sells = {} # Map of ticker -> sale_price
        aborted_sells = {} # Map of ticker -> yest_close
        
        for ticker in new_buys:
            print(f"\n  [EVALUATING] Pending BUY for {ticker} (Persona: {persona})")
            yest_close, yest_vwap = get_yesterday_metrics(ticker)
            live_price = get_live_metrics(ticker)
            
            time.sleep(0.3)
            
            if not yest_close or not live_price:
                print(f"    -> ERROR: Could not fetch YFinance data for {ticker}. Waiting...")
                continue
                
            # Calculate Dynamic VWAP Threshold based on Persona Risk Tolerance
            vwap_multiplier = 1.005 # Default to Neutral
            if "Conservative" in persona:
                vwap_multiplier = 1.01
            elif "BallsToTheWall" in persona or "Balls" in persona:
                vwap_multiplier = 1.0025
                
            dynamic_vwap_threshold = yest_vwap * vwap_multiplier
            
            print(f"    -> Yesterday Close: ${yest_close:.2f} | Yesterday VWAP: ${yest_vwap:.2f}")
            print(f"    -> Target VWAP Threshold ({persona}): ${dynamic_vwap_threshold:.2f}")
            print(f"    -> Live Ask Price : ${live_price:.2f}")
            
            # RULE 1: Live Price > Yesterday Close
            # RULE 2: Live Price > Dynamic VWAP Threshold
            momentum_passed = (live_price > yest_close) and (live_price > dynamic_vwap_threshold)
            
            if momentum_passed:
                print(f"    -> ✅ MOMENTUM PASSED! Authorizing Execution at ${live_price:.2f}.")
                approved_buys[ticker] = live_price
            else:
                print(f"    -> ❌ MOMENTUM FAILED! Holding fire.")
                
                if is_eod_fallback:
                    print(f"    -> ⏰ 15:55 EST EOD FALLBACK: Aborting trade permanently. Forcing HOLD.")
                    aborted_buys.append(ticker)
                    
        # ==========================================
        # PENDING SELL MOMENTUM SHIELD
        # ==========================================
        for ticker in pending_sells:
            print(f"\n  [EVALUATING] Pending SELL for {ticker} (Persona: {persona})")
            yest_close, yest_vwap = get_yesterday_metrics(ticker)
            live_price = get_live_metrics(ticker)
            
            time.sleep(0.3)
            
            if not yest_close or not live_price:
                continue
                
            vwap_multiplier = 1.005
            if "Conservative" in persona: vwap_multiplier = 1.01
            elif "BallsToTheWall" in persona or "Balls" in persona: vwap_multiplier = 1.0025
            dynamic_vwap_threshold = yest_vwap * vwap_multiplier
            
            print(f"    -> Yesterday Close: ${yest_close:.2f} | Yesterday VWAP: ${yest_vwap:.2f}")
            print(f"    -> Live Ask Price : ${live_price:.2f}")
            
            if (live_price > yest_close) and (live_price > dynamic_vwap_threshold):
                print(f"    -> 🚨 SURGE DETECTED! Market disagrees with AI. Aborting SELL and holding!")
                aborted_sells[ticker] = yest_close
            else:
                print(f"    -> ✅ Bearish momentum confirmed. Authorizing SELL.")
                    
        # ==========================================
        # INTRADAY TAKE-PROFIT SURGE PROTOCOL
        # ==========================================
        for ticker in held_tickers:
            print(f"\n  [MONITORING] Held Position: {ticker} (Persona: {persona})")
            yest_close, _ = get_yesterday_metrics(ticker)
            live_price = get_live_metrics(ticker)
            
            time.sleep(0.3)
            
            if not yest_close or not live_price:
                continue
                
            surge_pct = ((live_price - yest_close) / yest_close) * 100.0
            
            surge_threshold = 10.0 # Default Neutral
            stop_threshold = -10.0
            if "Conservative" in persona:
                surge_threshold = 5.0
                stop_threshold = -5.0
            elif "BallsToTheWall" in persona or "Balls" in persona:
                surge_threshold = 20.0
                stop_threshold = -20.0
                
            print(f"    -> Yesterday Close: ${yest_close:.2f} | Live Price: ${live_price:.2f}")
            print(f"    -> Intraday Surge: {surge_pct:+.2f}% (Take-Profit: +{surge_threshold}%, Stop-Loss: {stop_threshold}%)")
            
            if surge_pct >= surge_threshold:
                print(f"    -> 🚨 SURGE DETECTED! Taking profit on {ticker} at ${live_price:.2f}!")
                approved_sells[ticker] = live_price
            elif surge_pct <= stop_threshold:
                print(f"    -> 🚨 PLUNGE DETECTED! Emergency stop-loss on {ticker} at ${live_price:.2f}!")
                approved_sells[ticker] = live_price
                    
        # If we have any actionable intelligence, modify and commit the ledger!
        if approved_buys or approved_sells or aborted_sells or (is_eod_fallback and aborted_buys):
            print(f"\n  [COMMITTING LEDGER] Updating {persona} portfolio state...")
            
            # Ensure the memory bank exists
            if "Executed_Intraday_Trades" not in state:
                state["Executed_Intraday_Trades"] = {}
                
            executed_memory = state["Executed_Intraday_Trades"]
            
            # 1. Log newly executed trades into the memory bank permanently
            for t, p in approved_buys.items():
                # Dynamically recalculate units to prevent negative cash if price surged
                original_dollars = target_holdings[t]['units'] * target_holdings[t]['price']
                safe_units = int(original_dollars // p)
                executed_memory[t] = {"type": "BUY", "price": p, "units": safe_units}
            for t, p in approved_sells.items():
                executed_memory[t] = {"type": "SELL", "price": p}
            for t, p in aborted_sells.items():
                executed_memory[t] = {"type": "ABORTED_SELL", "price": p}
            
            # Start with the pure overnight intended Target Holdings
            final_holdings = target_holdings.copy()
            final_cash = state['Target_Cash']
            
            # 2. Strip out any target buys that haven't been approved yet AND aren't in memory
            for ticker in new_buys:
                if ticker not in executed_memory:
                    refund_amount = final_holdings[ticker]['dollars']
                    final_cash += refund_amount
                    del final_holdings[ticker]
                    
            # 3. Process everything in the memory bank to rebuild the exact live state
            for ticker, record in executed_memory.items():
                if record["type"] == "BUY":
                    original_units = final_holdings[ticker]['units']
                    yest_close_price = final_holdings[ticker]['price']
                    live_price = record["price"]
                    live_units = record.get("units", original_units)
                    
                    # Refund the full overnight allocation, deduct the actual live cash spent for safe units
                    final_cash += (original_units * yest_close_price)
                    final_cash -= (live_units * live_price)
                    
                    # Update holding with true purchase price and safe unit count
                    final_holdings[ticker]['price'] = live_price
                    final_holdings[ticker]['units'] = live_units
                    final_holdings[ticker]['dollars'] = live_units * live_price
                    
                elif record["type"] == "SELL":
                    if ticker in final_holdings:
                        units = final_holdings[ticker]['units']
                        live_price = record["price"]
                        sale_value = units * live_price
                        final_cash += sale_value
                        del final_holdings[ticker]
                        
                elif record["type"] == "ABORTED_SELL":
                    yest_close = record["price"]
                    units = current_holdings[ticker]['units']
                    re_buy_cost = units * yest_close
                    final_cash -= re_buy_cost
                    final_holdings[ticker] = {
                        'dollars': re_buy_cost,
                        'units': units,
                        'price': yest_close
                    }
                    
            status_note = "EOD Forced HOLD"
            if executed_memory:
                status_parts = []
                if any(r["type"] == "BUY" for r in executed_memory.values()): status_parts.append("BUY")
                if any(r["type"] == "SELL" for r in executed_memory.values()): status_parts.append("TP/SL")
                if any(r["type"] == "ABORTED_SELL" for r in executed_memory.values()): status_parts.append("ABORTED SELL")
                status_note = "Tracker Executed: " + " & ".join(status_parts)
                    
            # Dynamically recalculate live Total Equity to account for any realized PnL from intraday Take-Profits or Stop-Losses
            live_total_equity = final_cash + sum(item['dollars'] for item in final_holdings.values())
            
            # Create the final committed row
            new_row = pd.DataFrame([{
                'Date': state['Date'],
                'Cash': round(final_cash, 2),
                'Total_Equity': round(live_total_equity, 2),
                'Holdings_JSON': json.dumps(final_holdings),
                'Daily_PnL_JSON': json.dumps(state['Daily_PnL_JSON']),
                'Intraday_Status': status_note
            }])
            
            if state['Date'] in ledger['Date'].values:
                ledger = ledger[ledger['Date'] != state['Date']]
                
            ledger = pd.concat([ledger, new_row], ignore_index=True)
            ledger.to_csv(ledger_path, index=False)
            
            # If EOD fallback, or if ALL new buys were approved and we're just holding,
            # this persona is completely finished for the day!
            if is_eod_fallback or set(new_buys) == set(approved_buys.keys()):
                completed_personas.append(persona)
                
    # Cleanup completed personas from pending orders
    for cp in completed_personas:
        del pending_orders[cp]
        
    with open(pending_path, 'w') as f:
        json.dump(pending_orders, f, indent=4)


def get_next_market_open():
    ny_tz = pytz.timezone('America/New_York')
    now = datetime.now(ny_tz)
    next_open = now.replace(hour=9, minute=31, second=0, microsecond=0)
    if now >= next_open:
        next_open += timedelta(days=1)
    while next_open.weekday() >= 5:
        next_open += timedelta(days=1)
    return next_open

def run_intraday_tracker():
    ny_tz = pytz.timezone('America/New_York')
    print("=" * 70)
    print("🚀 AntiGravity Intraday Execution Engine")
    print("=" * 70)
    
    while True:
        now_ny = datetime.now(ny_tz)
        
        market_open = now_ny.replace(hour=9, minute=31, second=0, microsecond=0)
        market_close = now_ny.replace(hour=16, minute=0, second=0, microsecond=0)
        eod_fallback_time = now_ny.replace(hour=15, minute=55, second=0, microsecond=0)
        
        is_weekday = now_ny.weekday() < 5
        
        if is_weekday and (market_open <= now_ny <= market_close):
            print(f"\n[{now_ny.strftime('%Y-%m-%d %H:%M:%S EST')}] Market is OPEN. Scanning Pending Orders...")
            
            # Check if we hit the 15:55 EOD fallback window (within a 10 min tolerance)
            is_eod = now_ny >= eod_fallback_time
            
            execute_pending_orders(is_eod_fallback=is_eod)
            
            print("Zzz... Sleeping for 10 minutes...")
            time.sleep(600)
        else:
            next_open = get_next_market_open()
            sleep_seconds = (next_open - now_ny).total_seconds()
            print(f"\n[{now_ny.strftime('%Y-%m-%d %H:%M:%S EST')}] Market is CLOSED. Waiting for opening bell...")
            time.sleep(sleep_seconds)

if __name__ == "__main__":
    run_intraday_tracker()
