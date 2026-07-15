import yfinance as yf
import pandas as pd
import numpy as np
import time
import os
import pytz
import json
from datetime import datetime, timedelta
import pandas_market_calendars as mcal
import database_manager
import config

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"

# ==========================================
# INDICATOR UTILS & VIX WATCHDOG
# ==========================================

def get_vix_score():
    vix_path = os.path.join(BASE_DIR, "financial_data", "vix_score.json")
    if os.path.exists(vix_path):
        try:
            with open(vix_path, 'r') as f:
                data = json.load(f)
                return float(data.get("vix_value", 15.0))
        except:
            return 15.0
    return 15.0

def calculate_vwap(df):
    """Calculate VWAP from a dataframe of 1m candles."""
    if df.empty or 'Volume' not in df.columns: return 0.0
    df['TP'] = (df['High'] + df['Low'] + df['Close']) / 3
    df['TPV'] = df['TP'] * df['Volume']
    cum_vol = df['Volume'].sum()
    if cum_vol == 0: return df['Close'].iloc[-1]
    return df['TPV'].sum() / cum_vol

def _get_yesterday_metrics_internal(ticker, target_date=None):
    """Calculate Yesterday's Close and Yesterday's Intraday VWAP."""
    try:
        if target_date:
            from failover_downloader import download_ticker_with_failover
            df = download_ticker_with_failover(ticker)
            df = df.ffill()
            target_ts = pd.to_datetime(target_date)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df = df[df.index < target_ts]
            if df.empty: return None, None
            yest = df.iloc[-1]
            yest_close = yest['Close']
            yest_vwap = (yest['High'] + yest['Low'] + yest['Close']) / 3.0
            return yest_close, yest_vwap
            
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
    except Exception as e:
        print(f"EXCEPTION in get_yesterday_metrics for {ticker}: {e}")
        return None, None

def get_yesterday_metrics(ticker, target_date=None):
    from timeout_runner import run_with_timeout
    try:
        return run_with_timeout(_get_yesterday_metrics_internal, args=(ticker, target_date), timeout_seconds=15)
    except TimeoutError:
        print(f"    -> [TIMEOUT] yfinance froze while fetching yesterday's data for {ticker}. Falling back to Tiingo...")
        from failover_downloader import download_ticker_with_failover
        try:
            df = download_ticker_with_failover(ticker)
            if df.empty: return None, None
            yest = df.iloc[-1]
            yest_close = yest['Close']
            yest_vwap = (yest['High'] + yest['Low'] + yest['Close']) / 3.0
            return yest_close, yest_vwap
        except Exception as e:
            print(f"    -> [FAILOVER ERROR] Yesterday metrics fallback failed for {ticker}: {e}")
            return None, None
    except Exception as e:
        print(f"EXCEPTION in get_yesterday_metrics wrapper for {ticker}: {e}")
        return None, None

def _get_live_metrics_internal(ticker, target_date=None):
    """Get the absolute latest live asking price and live volume (last 1m candle close)."""
    try:
        if target_date:
            from failover_downloader import download_ticker_with_failover
            df = download_ticker_with_failover(ticker)
            df = df.ffill()
            target_ts = pd.to_datetime(target_date)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df = df[df.index <= target_ts]
            if df.empty: return None, 0.0
            return df.iloc[-1]['Close'], 1e9 # Bypass volume check for historical runs
            
        df_1m = yf.download(ticker, period="1d", interval="1m", progress=False)
        if df_1m.empty: return None, 0.0
        if isinstance(df_1m.columns, pd.MultiIndex):
            df_1m.columns = df_1m.columns.droplevel(1)
        
        live_price = df_1m['Close'].iloc[-1]
        live_volume = float(df_1m['Volume'].sum())
        return live_price, live_volume
    except Exception as e:
        print(f"EXCEPTION in get_live_metrics for {ticker}: {e}")
        return None, 0.0

def get_live_metrics(ticker, target_date=None):
    from timeout_runner import run_with_timeout
    try:
        return run_with_timeout(_get_live_metrics_internal, args=(ticker, target_date), timeout_seconds=15)
    except TimeoutError:
        print(f"    -> [TIMEOUT] yfinance froze while fetching live data for {ticker}. Falling back to Tiingo...")
        from failover_downloader import download_ticker_with_failover
        try:
            df = download_ticker_with_failover(ticker)
            if df.empty: return None, 0.0
            return df.iloc[-1]['Close'], 1e9
        except Exception as e:
            print(f"    -> [FAILOVER ERROR] Live metrics fallback failed for {ticker}: {e}")
            return None, 0.0
    except Exception as e:
        print(f"EXCEPTION in get_live_metrics wrapper for {ticker}: {e}")
        return None, 0.0

def get_avg_volume(ticker):
    """Get the 10-day Average Daily Volume for fakeout protection."""
    try:
        df = yf.download(ticker, period="10d", interval="1d", progress=False)
        if df.empty or 'Volume' not in df.columns: return 1.0
        return float(df['Volume'].mean().item())
    except:
        return 1.0

def is_triple_witching(date_obj):
    if isinstance(date_obj, str):
        date_obj = pd.to_datetime(date_obj)
    if date_obj.month not in [3, 6, 9, 12]: return False
    nyse = mcal.get_calendar('NYSE')
    start_of_month = date_obj.replace(day=1)
    if date_obj.month == 12:
        end_of_month = date_obj.replace(year=date_obj.year+1, month=1, day=1) - timedelta(days=1)
    else:
        end_of_month = date_obj.replace(month=date_obj.month+1, day=1) - timedelta(days=1)
    
    dates = pd.date_range(start=start_of_month, end=end_of_month)
    fridays = dates[dates.weekday == 4]
    if len(fridays) < 3: return False
    third_friday = fridays[2]
    
    valid_on_friday = nyse.valid_days(start_date=third_friday.date(), end_date=third_friday.date())
    if len(valid_on_friday) == 0:
        witching_day = third_friday - timedelta(days=1)
    else:
        witching_day = third_friday
        
    return date_obj.date() == witching_day.date()

# ==========================================
# EXECUTION LOGIC
# ==========================================

def execute_pending_orders(is_eod_fallback=False, target_date=None):
    """
    Scans Pending_Orders.json.
    For each persona, it checks the target holdings (the BUYS).
    If a BUY target meets the Momentum criteria, it executes it and commits to the ledger.
    If is_eod_fallback=True, it permanently aborts unmet trades, logs HOLD, and commits to ledger.
    """
    try:
        df = database_manager.execute_query("SELECT persona FROM pending_orders")
        rows = df.values.tolist()
    except Exception:
        rows = []
    
    if not rows:
        print("No pending orders.")
        return False
        
    completed_personas = []
    yfinance_failure = False
    
    for row in rows:
        persona = row[0]
        state = database_manager.get_pending_order(persona)
        if not state: continue
        
        target_holdings = json.loads(state['target_holdings_json']) if isinstance(state['target_holdings_json'], str) else state['target_holdings_json']
        # Map state columns to what the code expects
        state['Date'] = state['date']
        state['Target_Cash'] = state['target_cash']
        state['Target_Total_Equity'] = state['target_total_equity']
        state['Target_Holdings'] = target_holdings
        state['Daily_PnL_JSON'] = json.loads(state['daily_pnl_json']) if isinstance(state['daily_pnl_json'], str) else state['daily_pnl_json']
        state['Executed_Intraday_Trades'] = json.loads(state['executed_intraday_trades_json']) if isinstance(state['executed_intraday_trades_json'], str) else state['executed_intraday_trades_json']
        
        # Load the CURRENT active portfolio from the ledger to see what we already own
        ledger = database_manager.get_ledger(persona)
        if ledger.empty:
            ledger = pd.DataFrame([{
                'Date': '2026-04-22',
                'Cash': 10000.0,
                'Total_Equity': 10000.0,
                'Holdings_JSON': '{}',
                'Daily_PnL_JSON': '{}'
            }])
        
        last_ledger_row = ledger.iloc[-1]
        current_holdings_raw = last_ledger_row['Holdings_JSON']
        current_holdings = json.loads(current_holdings_raw) if isinstance(current_holdings_raw, str) else current_holdings_raw
        
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
            yest_close, yest_vwap = get_yesterday_metrics(ticker, target_date)
            live_price, live_volume = get_live_metrics(ticker, target_date)
            
            time.sleep(0.3)
            
            if not yest_close or not live_price:
                print(f"    -> ERROR: Could not fetch YFinance data for {ticker}. Waiting...")
                yfinance_failure = True
                continue
                
            # Calculate Dynamic VWAP Threshold based on Persona Risk Tolerance
            vwap_multiplier = 1.005 # Default to Neutral
            if "Conservative" in persona:
                vwap_multiplier = 1.01
            elif "BallsToTheWall" in persona or "Balls" in persona:
                vwap_multiplier = 1.0025
                
            dynamic_vwap_threshold = yest_vwap * vwap_multiplier
            
            # --- HIGH VOLATILITY & TRIPLE WITCHING INTEGRATION ---
            live_vix = get_vix_score()
            now_ny = datetime.now(pytz.timezone('America/New_York'))
            is_tw = is_triple_witching(target_date if target_date else now_ny)
            
            if live_vix >= 20 or is_tw:
                print(f"    ->  [VOLATILITY ALERT] VIX={live_vix:.2f} | TripleWitching={is_tw}. Widening VWAP Targets.")
                dynamic_vwap_threshold = yest_vwap * (vwap_multiplier + 0.015) # Require a much steeper breakout/discount
            
            print(f"    -> Yesterday Close: ${yest_close:.2f} | Yesterday VWAP: ${yest_vwap:.2f}")
            print(f"    -> Target VWAP Threshold ({persona}): ${dynamic_vwap_threshold:.2f}")
            print(f"    -> Live Ask Price : ${live_price:.2f}")
            
            # RULE 1: Live Price > Yesterday Close
            # RULE 2: Live Price > Dynamic VWAP Threshold
            if target_date:
                momentum_passed = True # Bypass for historical rebuilds to match intended Target Holdings
            else:
                momentum_passed = (live_price > yest_close) and (live_price > dynamic_vwap_threshold)
            
            if momentum_passed:
                # --- DYNAMIC VOLUME GATING ---
                avg_daily_vol = get_avg_volume(ticker)
                market_open = now_ny.replace(hour=9, minute=30, second=0, microsecond=0)
                elapsed_minutes = max(1.0, (now_ny - market_open).total_seconds() / 60.0)
                expected_vol_so_far = avg_daily_vol * (elapsed_minutes / 390.0)
                
                if live_volume < (expected_vol_so_far * 0.5) and not target_date:
                    print(f"    ->  [FAKEOUT BLOCKED] Price momentum passed, but Volume is suspiciously low ({live_volume:,.0f} vs expected {expected_vol_so_far:,.0f}). Holding fire.")
                else:
                    print(f"    ->  MOMENTUM & VOLUME PASSED! Authorizing Execution at ${live_price:.2f}.")
                    approved_buys[ticker] = live_price
            else:
                print(f"    ->  MOMENTUM FAILED! Holding fire.")
                
                if is_eod_fallback:
                    print(f"    ->  15:55 EST EOD FALLBACK: Aborting trade permanently. Forcing HOLD.")
                    aborted_buys.append(ticker)
                    
        # ==========================================
        # PENDING SELL MOMENTUM SHIELD
        # ==========================================
        for ticker in pending_sells:
            print(f"\n  [EVALUATING] Pending SELL for {ticker} (Persona: {persona})")
            yest_close, _ = get_yesterday_metrics(ticker, target_date)
            live_price, _ = get_live_metrics(ticker, target_date)
            
            time.sleep(0.3)
            
            if not yest_close or not live_price:
                yfinance_failure = True
                print(f"    -> [TIMEOUT] yfinance froze. Auto-aborting SELL for {ticker} to prevent orphaning.")
                # We must abort the sell so it is added back to final_holdings
                aborted_sells[ticker] = current_holdings[ticker]['price']
                continue
                
            vwap_multiplier = 1.005
            if "Conservative" in persona: vwap_multiplier = 1.01
            elif "BallsToTheWall" in persona or "Balls" in persona: vwap_multiplier = 1.0025
            dynamic_vwap_threshold = yest_vwap * vwap_multiplier
            
            print(f"    -> Yesterday Close: ${yest_close:.2f} | Yesterday VWAP: ${yest_vwap:.2f}")
            print(f"    -> Live Ask Price : ${live_price:.2f}")
            
            if (live_price > yest_close) and (live_price > dynamic_vwap_threshold):
                print(f"    ->  SURGE DETECTED! Market disagrees with AI. Aborting SELL and holding!")
                aborted_sells[ticker] = yest_close
            else:
                print(f"    ->  Bearish momentum confirmed. Authorizing SELL.")
                approved_sells[ticker] = live_price
                    
        # ==========================================
        # INTRADAY TAKE-PROFIT SURGE PROTOCOL
        # ==========================================
        for ticker in held_tickers:
            print(f"\n  [MONITORING] Held Position: {ticker} (Persona: {persona})")
            yest_close, _ = get_yesterday_metrics(ticker, target_date)
            live_price, _ = get_live_metrics(ticker, target_date)
            
            time.sleep(0.3)
            
            if not yest_close or not live_price:
                yfinance_failure = True
                continue
                
            surge_pct = ((live_price - yest_close) / yest_close) * 100.0
            
            surge_threshold = 10.0 # Default Neutral
            stop_threshold = -10.0
            
            # --- DYNAMIC VIX SCALAR LOGIC ---
            live_vix = get_vix_score()
            vix_scalar = 1.0
            
            if "ETF_" in persona:
                is_leveraged = ticker in ["UDOW", "MSTZ", "UPRO", "TQQQ", "SOXL", "SPXL", "TECL", "FAS", "LABU"]
                lev_multiplier = 2.5 if is_leveraged else 1.0
                
                if "Conservative" in persona:
                    surge_threshold = 2.0 * lev_multiplier
                    if live_vix >= 25:
                        print(f"    ->  [VIX PANIC] Conservative Broker liquidating! VIX={live_vix}")
                        approved_sells[ticker] = live_price
                        continue
                    elif live_vix >= 20:
                        vix_scalar = 0.4
                    stop_threshold = -2.0 * lev_multiplier * vix_scalar
                    
                elif "BallsToTheWall" in persona or "Balls" in persona:
                    surge_threshold = 8.0 * lev_multiplier
                    if live_vix >= 45:
                        print(f"    ->  [VIX MELTDOWN] BallsForBrains liquidating! VIX={live_vix}")
                        approved_sells[ticker] = live_price
                        continue
                    stop_threshold = -8.0 * lev_multiplier
                    
                else: # Neutral / Dynamic
                    surge_threshold = 4.0 * lev_multiplier
                    if live_vix >= 30:
                        print(f"    ->  [VIX PANIC] Neutral Broker liquidating! VIX={live_vix}")
                        approved_sells[ticker] = live_price
                        continue
                    elif live_vix >= 20:
                        vix_scalar = 1.5
                    stop_threshold = -4.0 * lev_multiplier * vix_scalar
                    
            else:
                if "Conservative" in persona:
                    surge_threshold = 5.0
                    if live_vix >= 25:
                        print(f"    ->  [VIX PANIC] Conservative Broker liquidating! VIX={live_vix}")
                        approved_sells[ticker] = live_price
                        continue
                    elif live_vix >= 20:
                        vix_scalar = 0.4 # Tighten stops to 2%
                    stop_threshold = -5.0 * vix_scalar
                    
                elif "BallsToTheWall" in persona or "Balls" in persona:
                    surge_threshold = 20.0
                    if live_vix >= 45: # Global Meltdown
                        print(f"    ->  [VIX MELTDOWN] BallsForBrains liquidating! VIX={live_vix}")
                        approved_sells[ticker] = live_price
                        continue
                    stop_threshold = -20.0 # Ignores standard elevated fear
                    
                else: # Neutral
                    surge_threshold = 10.0
                    if live_vix >= 30:
                        print(f"    ->  [VIX PANIC] Neutral Broker liquidating! VIX={live_vix}")
                        approved_sells[ticker] = live_price
                        continue
                    elif live_vix >= 20:
                        vix_scalar = 1.5 # Widen to 15% to avoid whipsaw
                    stop_threshold = -10.0 * vix_scalar
            # --------------------------------
            print(f"    -> Yesterday Close: ${yest_close:.2f} | Live Price: ${live_price:.2f}")
            print(f"    -> Intraday Surge: {surge_pct:+.2f}% (Take-Profit: +{surge_threshold}%, Stop-Loss: {stop_threshold}%)")
            
            if surge_pct >= surge_threshold:
                print(f"    ->  SURGE DETECTED! Taking profit on {ticker} at ${live_price:.2f}!")
                approved_sells[ticker] = live_price
            elif surge_pct <= stop_threshold:
                print(f"    ->  PLUNGE DETECTED! Emergency stop-loss on {ticker} at ${live_price:.2f}!")
                approved_sells[ticker] = live_price
                    
        # If we have any actionable intelligence, modify and commit the ledger!
        if approved_buys or approved_sells or aborted_sells or aborted_buys or is_eod_fallback:
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
                    broker_purchase_price = final_holdings[ticker]['price']
                    live_price = record["price"]
                    live_units = record.get("units", original_units)
                    
                    # Refund the full overnight allocation, deduct the actual live cash spent for safe units
                    final_cash += (original_units * broker_purchase_price)
                    final_cash -= (live_units * live_price)
                    
                    # Update holding with true purchase price and safe unit count
                    final_holdings[ticker]['price'] = live_price
                    final_holdings[ticker]['units'] = live_units
                    final_holdings[ticker]['dollars'] = live_units * live_price
                    
                elif record["type"] == "SELL":
                    if ticker in current_holdings and ticker not in final_holdings:
                        # This was a pending overnight sell.
                        # Reverse the exact credit that the virtual broker added to Target_Cash
                        units = current_holdings[ticker]['units']
                        allocated_dollars = units * current_holdings[ticker]['price']
                        broker_credited = allocated_dollars + state['Daily_PnL_JSON'].get(ticker, 0.0)
                        
                        live_price = record["price"]
                        sale_value = units * live_price
                        
                        final_cash -= broker_credited
                        final_cash += sale_value
                        
                        # Update the Daily PNL to reflect the EXACT realized PNL instead of the broker's assumption
                        state['Daily_PnL_JSON'][ticker] = sale_value - allocated_dollars

                    elif ticker in final_holdings:
                        # This was an intraday take-profit / stop-loss.
                        units = final_holdings[ticker]['units']
                        live_price = record["price"]
                        sale_value = units * live_price
                        
                        # The broker assumed we held this and spent `final_holdings[ticker]['dollars']` to keep it in Target_Holdings.
                        broker_assumed_value = final_holdings[ticker]['dollars']
                        
                        final_cash += sale_value
                        del final_holdings[ticker]
                        
                        # The PNL needs to shift by the exact difference between what the broker assumed it was worth and what we actually sold it for.
                        if ticker in state['Daily_PnL_JSON']:
                            state['Daily_PnL_JSON'][ticker] += (sale_value - broker_assumed_value)
                        else:
                            state['Daily_PnL_JSON'][ticker] = (sale_value - broker_assumed_value)

                elif record["type"] == "ABORTED_SELL":
                    units = current_holdings[ticker]['units']
                    
                    # Reverse the broker's cash credit because we did NOT sell it
                    allocated_dollars = units * current_holdings[ticker]['price']
                    broker_credited = allocated_dollars + state['Daily_PnL_JSON'].get(ticker, 0.0)
                    
                    final_cash -= broker_credited
                    
                    # Add back to holdings. The broker's credited value represents the precise End-of-Day value it assumed we sold it for.
                    # Since we are holding it, this becomes its new cost basis for tomorrow!
                    final_holdings[ticker] = {
                        'dollars': broker_credited,
                        'units': units,
                        'price': broker_credited / units if units > 0 else 0.0
                    }
                    
                    # We DO NOT modify the PNL here, because the PNL predicted by the broker is perfectly accurate for an asset held to close!
                    
            status_note = "EOD Forced HOLD"
            if executed_memory:
                status_parts = []
                if any(r["type"] == "BUY" for r in executed_memory.values()): status_parts.append("BUY")
                if any(r["type"] == "SELL" for r in executed_memory.values()): status_parts.append("TP/SL")
                if any(r["type"] == "ABORTED_SELL" for r in executed_memory.values()): status_parts.append("ABORTED SELL")
                status_note = "Tracker Executed: " + " & ".join(status_parts)
                    
            # Dynamically recalculate live Total Equity to account for any realized PnL from intraday Take-Profits or Stop-Losses
            live_total_equity = final_cash + sum(item['dollars'] for item in final_holdings.values())
            
            # Create the final committed row in SQLite
            database_manager.save_ledger_row(
                persona=persona,
                date=state['Date'],
                cash=round(final_cash, 2),
                total_equity=round(live_total_equity, 2),
                holdings_json=final_holdings,
                daily_pnl_json=state['Daily_PnL_JSON'],
                intraday_status=status_note,
                engine_version=config.CURRENT_MODEL_VERSION
            )
            
            # If EOD fallback, or if ALL new buys were approved and we're just holding,
            # this persona is completely finished for the day!
            if is_eod_fallback or set(new_buys) == set(approved_buys.keys()):
                completed_personas.append(persona)
                
    # Cleanup completed personas from pending orders
    if completed_personas:
        client = database_manager.get_connection()
        for cp in completed_personas:
            client.execute("DELETE FROM pending_orders WHERE persona = ?", [cp])

    return yfinance_failure

def get_next_market_open():
    ny_tz = pytz.timezone('America/New_York')
    now = datetime.now(ny_tz)
    nyse = mcal.get_calendar('NYSE')
    
    # Check schedule for the next 10 days
    schedule = nyse.schedule(start_date=now.date(), end_date=(now + timedelta(days=10)).date())
    for dt in schedule.index:
        market_open_time = ny_tz.localize(datetime.combine(dt.date(), datetime.strptime("09:31", "%H:%M").time()))
        if now < market_open_time:
            return market_open_time
    return now + timedelta(days=1)

def run_intraday_tracker(target_date=None):
    ny_tz = pytz.timezone('America/New_York')
    print("=" * 70)
    print("=== AntiGravity Intraday Execution Engine ===")
    print("=" * 70)
    
    if target_date:
        print(f"\n[CATCH-UP MODE] Forcing immediate EOD execution for historical date: {target_date}")
        execute_pending_orders(is_eod_fallback=True, target_date=target_date)
        return
        
    while True:
        now_ny = datetime.now(ny_tz)
        
        market_open = now_ny.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_ny.replace(hour=16, minute=0, second=0, microsecond=0)
        eod_fallback_time = now_ny.replace(hour=15, minute=55, second=0, microsecond=0)
        
        nyse = mcal.get_calendar('NYSE')
        valid_today = nyse.valid_days(start_date=now_ny.date(), end_date=now_ny.date())
        is_market_day = len(valid_today) > 0
        
        if is_market_day and (market_open <= now_ny < market_close):
            print(f"\n[{now_ny.strftime('%Y-%m-%d %H:%M:%S EST')}] Market is OPEN. Scanning Pending Orders...")
            
            # Check if we hit the 15:55 EOD fallback window (within a 10 min tolerance)
            is_eod = now_ny >= eod_fallback_time
            
            yfinance_failure = execute_pending_orders(is_eod_fallback=is_eod)
            
            if yfinance_failure:
                print("--- YFinance Rate Limit Detected! Automatically falling back to 5-minute penalty cooldown ---")
                time.sleep(300)
            else:
                print("Zzz... Sleeping for 3 minutes...")
                time.sleep(180)
        else:
            next_open = get_next_market_open()
            sleep_seconds = (next_open - now_ny).total_seconds()
            print(f"\n[{now_ny.strftime('%Y-%m-%d %H:%M:%S EST')}] Market is CLOSED. Waiting for opening bell...")
            time.sleep(sleep_seconds)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date", type=str, help="Target date to simulate catch-up execution")
    args = parser.parse_args()
    run_intraday_tracker(target_date=args.target_date)
