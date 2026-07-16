import os
import sys
import time
import shutil  
import numpy as np
import pandas as pd
import yfinance as yf

import json
import datetime

sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
from failover_downloader import download_ticker_with_failover


# The hardcoded dictionary has been removed.
# Tickers will now be dynamically loaded and rebalanced quarterly via get_active_tickers().

def rebalance_tickers(folder_path):
    print("\n[SYSTEM] Triggering 90-Day Quarterly Ticker Rebalancing...")
    print(">>> Scraping live S&P 500 components from Wikipedia...")
    try:
        import requests
        import io
        headers = {'User-Agent': 'Mozilla/5.0'}
        html = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers=headers).text
        tables = pd.read_html(io.StringIO(html))
        sp500_df = tables[0]
        tickers = sp500_df['Symbol'].tolist()
        tickers = [t.replace('.', '-') for t in tickers]
        sectors = sp500_df['GICS Sector'].tolist()
        ticker_sector_map = dict(zip(tickers, sectors))
        
        print(f">>> Bulk downloading 1-year data for {len(tickers)} tickers to calculate Liquidity & Volatility...")
        # Using un-adjusted close to avoid yfinance multi-index errors on some columns in recent updates, 
        # but auto_adjust=True is fine. For speed we use threads=True implicitly.
        data = yf.download(tickers, period="1y", group_by="ticker", auto_adjust=False, progress=False)
        
        results = []
        for t in tickers:
            try:
                if len(tickers) == 1:
                    df = data
                else:
                    df = data[t]
                    
                if df.empty or 'Close' not in df.columns or 'Volume' not in df.columns:
                    continue
                    
                df = df.dropna(subset=['Close', 'Volume'])
                if len(df) < 50:
                    continue
                
                recent_df = df.tail(30)
                avg_liquidity = (recent_df['Close'] * recent_df['Volume']).mean()
                
                returns = df['Close'].pct_change().dropna()
                volatility = returns.std()
                
                sector = ticker_sector_map.get(t, "Unknown")
                score = avg_liquidity / volatility if volatility > 0 else 0
                
                results.append({
                    'Ticker': t.replace('-', '.'), 
                    'Sector': sector.replace(' ', '_'),
                    'Score': score
                })
            except Exception:
                pass
                
        ranking_df = pd.DataFrame(results)
        
        new_sectors_dict = {}
        for sector, group in ranking_df.groupby('Sector'):
            top_50 = group.sort_values('Score', ascending=False).head(50)
            new_sectors_dict[sector] = top_50['Ticker'].tolist()
            
        os.makedirs(folder_path, exist_ok=True)
        json_path = os.path.join(folder_path, "VIP_Tickers.json")
        save_data = {
            "last_updated": datetime.datetime.now().strftime('%Y-%m-%d'),
            "sectors_dict": new_sectors_dict
        }
        
        with open(json_path, 'w') as f:
            json.dump(save_data, f, indent=4)
            
        print("[SUCCESS] Quarterly Rebalancing Complete! VIP_Tickers.json generated.")
        return new_sectors_dict
        
    except Exception as e:
        print(f"[ERROR] Failed to rebalance tickers: {str(e)[:200]}")
        return None

def get_active_tickers(folder_path):
    active_sectors_dict = None
    json_path = os.path.join(folder_path, "VIP_Tickers.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            last_updated = datetime.datetime.strptime(data['last_updated'], '%Y-%m-%d')
            days_old = (datetime.datetime.now() - last_updated).days
            if days_old <= 90:
                print(f"\n[INFO] Loaded VIP Tickers from Cache (Updated {days_old} days ago)")
                active_sectors_dict = data['sectors_dict']
            else:
                print(f"\n[INFO] VIP Tickers cache is {days_old} days old. Expired.")
        except Exception as e:
            print(f"[WARNING] Failed to read VIP_Tickers.json: {e}")
            
    if not active_sectors_dict:
        active_sectors_dict = rebalance_tickers(folder_path)
        
    if not active_sectors_dict:
        return None
        
    # --- GRANDFATHERING LOGIC ---
    try:
        import pandas as pd
        import json
        from database_manager import execute_query
        
        all_vip_tickers = set(t for sublist in active_sectors_dict.values() for t in sublist)
        legacy_holdings = set()
        
        try:
            # Read from capital_ledgers table for all single stock personas via Turso
            df_ledgers = execute_query("SELECT Persona, Holdings_JSON FROM capital_ledgers WHERE Persona NOT LIKE 'ETF_%'")
        except Exception as e:
            print(f"Grandfathering Turso error: {e}")
            df_ledgers = pd.DataFrame()
            
        # Find the latest holdings for each persona
        if not df_ledgers.empty:
            # Group by persona and take the last row to only grandfather ACTIVE current holdings
            latest_ledgers = df_ledgers.groupby('Persona').last().reset_index()
            for holdings_str in latest_ledgers['Holdings_JSON']:
                try:
                    if pd.isna(holdings_str): continue
                    holdings = json.loads(holdings_str)
                    for t in holdings.keys():
                        if t != 'Cash' and t not in all_vip_tickers:
                            legacy_holdings.add(t)
                except Exception:
                    pass
                        
        if legacy_holdings:
            print(f"\n[GRANDFATHER CLAUSE] Injecting {len(legacy_holdings)} orphaned holdings back into active pipeline: {list(legacy_holdings)}")
            active_sectors_dict["Legacy_Holdings"] = list(legacy_holdings)
            
    except Exception as e:
        print(f"[WARNING] Failed to scan ledgers for grandfathering: {e}")
        
    return active_sectors_dict

def calculate_ras_signal(row):
    if not pd.isna(row['Dynamic_Stop_Loss']) and row['Close'] < row['Dynamic_Stop_Loss']:
        return 'STOP_HIT'
    if pd.isna(row['RSI_14d']) or pd.isna(row['ADX_14d']):
        return 'HOLD'
    if row['RSI_14d'] <= 35 and row['ADX_14d'] >= 25:
        return 'BUY'
    elif row['RSI_14d'] >= 65 and row['ADX_14d'] >= 25:
        return 'SELL'
    else:
        return 'HOLD'

def fix_yfinance_dataframe(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).strip() for c in df.columns]
    if 'Date' not in df.columns:
        df = df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).strip() for c in df.columns]
    df.rename(columns=lambda x: 'Date' if x.lower() == 'date' else x, inplace=True)
    return df

def get_vix_data():
    print("\n>>> Fetching CBOE Volatility Index (VIX) data...")
    try:
        vix_df = yf.download("^VIX", period="5y", interval="1d")
        if not vix_df.empty:
            vix_df = fix_yfinance_dataframe(vix_df)
            vix_df.rename(columns=lambda x: 'Date' if x.lower() == 'date' else ('VIX_Close' if x.lower() == 'close' else x), inplace=True)
            vix_df = vix_df[['Date', 'VIX_Close']]
            vix_df['Date'] = pd.to_datetime(vix_df['Date']).dt.tz_localize(None)
            vix_df['Market_Fear_Level'] = np.where(vix_df['VIX_Close'] >= 30, 'Extreme Panic',
                                          np.where(vix_df['VIX_Close'] >= 20, 'High Volatility', 'Complacency / Calm'))
            return vix_df
    except Exception as e:
        print(f"[WARNING] Could not retrieve VIX data due to an error: {e}")
    return pd.DataFrame()

def get_tnx_data():
    print("\n>>> Fetching 10-Year Treasury Yield (^TNX) data...")
    try:
        tnx_df = yf.download("^TNX", period="5y", interval="1d")
        if not tnx_df.empty:
            tnx_df = fix_yfinance_dataframe(tnx_df)
            tnx_df.rename(columns=lambda x: 'Date' if x.lower() == 'date' else ('TNX_Close' if x.lower() == 'close' else x), inplace=True)
            tnx_df = tnx_df[['Date', 'TNX_Close']]
            tnx_df['Date'] = pd.to_datetime(tnx_df['Date']).dt.tz_localize(None)
            
            # Feature Engineering for TNX
            tnx_df['TNX_Lag1_Return'] = tnx_df['TNX_Close'].pct_change(fill_method=None)
            tnx_df['TNX_Trend_5d'] = tnx_df['TNX_Close'].rolling(window=5).mean()
            
            return tnx_df
    except Exception as e:
        print(f"[WARNING] Could not retrieve TNX data due to an error: {e}")
    return pd.DataFrame()

def get_analyst_raw_data(ticker):
    try:
        t_obj = yf.Ticker(ticker)
        info = t_obj.info
        recommendation = info.get('recommendationKey', 'N/A').upper().replace('_', ' ')
        target_price = info.get('targetMeanPrice', None)
        current_price = info.get('currentPrice', None)
        
        upside = np.nan
        if target_price and current_price:
            upside = ((target_price - current_price) / current_price) * 100
            
        return recommendation, upside
    except Exception:
        return "N/A", np.nan

def download_sp500_full_analysis(sectors_map, folder_path):
    output_filename = "SP500_Clean_Advanced_Analysis.csv"
    full_path = os.path.join(folder_path, output_filename)
    backup_path = full_path + ".bak"  
    
    existing_df = pd.DataFrame()
    max_dates_per_ticker = {}
    is_incremental = False
    
    tickers_updated_count = 0
    tickers_added_count = 0
    tickers_failed_count = 0
    
    if os.path.exists(full_path):
        print(f"\n[INFO] Existing data file found at: {full_path}")
        try:
            shutil.copy2(full_path, backup_path)
            print(f"[BACKUP] Created safe backup file at: {backup_path}")
            
            existing_df = pd.read_csv(full_path)
            if not existing_df.empty and 'Ticker' in existing_df.columns and 'Date' in existing_df.columns:
                existing_df['Date'] = pd.to_datetime(existing_df['Date']).dt.tz_localize(None)
                max_dates_per_ticker = existing_df.groupby('Ticker')['Date'].max().to_dict()
                is_incremental = True
                print(f"[INFO] Operational Mode: Incremental Update for {len(max_dates_per_ticker)} tickers.")
        except Exception as e:
            print(f"[WARNING] Backup/Read failed, starting fresh. Error: {e}")
            existing_df = pd.DataFrame()

    dl_archive_filename = "SP500_DeepLearning_Archive.csv"
    dl_archive_path = os.path.join(folder_path, dl_archive_filename)
    existing_dl_df = pd.DataFrame()
    if os.path.exists(dl_archive_path):
        print(f"[INFO] Existing Deep Learning Archive found at: {dl_archive_path}")
        try:
            existing_dl_df = pd.read_csv(dl_archive_path)
            if not existing_dl_df.empty and 'Ticker' in existing_dl_df.columns and 'Date' in existing_dl_df.columns:
                existing_dl_df['Date'] = pd.to_datetime(existing_dl_df['Date']).dt.tz_localize(None)
        except Exception as e:
            print(f"[WARNING] Deep Learning Archive read failed. Starting fresh. Error: {e}")
            existing_dl_df = pd.DataFrame()
            
    all_combined_data = []
    all_dl_data = []
    vix_data = get_vix_data()
    tnx_data = get_tnx_data()
    
    if vix_data.empty:
        print("[WARNING] Running without VIX market fear overlay. Columns will be skipped.")
    else:
        print("[SUCCESS] VIX Volatility index captured successfully.")
        
    if tnx_data.empty:
        print("[WARNING] Running without TNX macro interest rate overlay. Columns will be skipped.")
    else:
        print("[SUCCESS] TNX 10-Year Treasury Yield captured successfully.")

    valid_tickers_in_dict = [ticker for sublist in sectors_map.values() for ticker in sublist]

    for sector_name, ticker_list in sectors_map.items():
        print(f"\n>>> Starting Sector: {sector_name} ({len(ticker_list)} Hardcoded Tickers)")
        
        for ticker in ticker_list:
            is_new_ticker = ticker not in max_dates_per_ticker
            try:
                if not is_new_ticker:
                    last_date = max_dates_per_ticker[ticker]
                    start_date = (last_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                    print(f"Downloading incremental data for {ticker} starting from {start_date}...")
                    new_raw_df = download_ticker_with_failover(ticker, start=start_date)
                    new_raw_df = fix_yfinance_dataframe(new_raw_df)
                    
                    ticker_history = existing_df[existing_df['Ticker'] == ticker].copy()
                    cols_to_keep = ['Date', 'Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume', 'Ticker', 'Sector', 'Daily_STDEV', 'Analyst_Consensus', 'Analyst_Upside_%']
                    ticker_history = ticker_history[[c for c in cols_to_keep if c in ticker_history.columns]]
                    
                    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                        if col in ticker_history.columns:
                            ticker_history[col] = pd.to_numeric(ticker_history[col], errors='coerce')
                else:
                    print(f"Downloading full 5y data for {ticker}...")
                    new_raw_df = download_ticker_with_failover(ticker, period="5y")
                    new_raw_df = fix_yfinance_dataframe(new_raw_df)
                    ticker_history = pd.DataFrame()

                if new_raw_df.empty or 'Close' not in new_raw_df.columns:
                    if not ticker_history.empty:
                        all_combined_data.append(existing_df[existing_df['Ticker'] == ticker])
                        tickers_updated_count += 1
                        
                        # Forward the DL archive as well
                        if not existing_dl_df.empty:
                            dl_hist = existing_dl_df[existing_dl_df['Ticker'] == ticker]
                            if not dl_hist.empty:
                                all_dl_data.append(dl_hist)
                    else:
                        tickers_failed_count += 1
                    continue
                
                new_raw_df['Date'] = pd.to_datetime(new_raw_df['Date']).dt.tz_localize(None)
                new_raw_df['Ticker'] = ticker
                new_raw_df['Sector'] = sector_name
                
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if col in new_raw_df.columns:
                        new_raw_df[col] = pd.to_numeric(new_raw_df[col], errors='coerce')
                
                if not ticker_history.empty:
                    df = pd.concat([ticker_history, new_raw_df], ignore_index=True)
                    df = df.drop_duplicates(subset=['Date']).sort_values('Date').reset_index(drop=True)
                else:
                    df = new_raw_df.sort_values('Date').reset_index(drop=True)
                
                # Append to Deep Learning Archive (Raw Data)
                if not existing_dl_df.empty:
                    dl_history = existing_dl_df[existing_dl_df['Ticker'] == ticker].copy()
                    if not dl_history.empty:
                        dl_df = pd.concat([dl_history, new_raw_df], ignore_index=True)
                        dl_df = dl_df.drop_duplicates(subset=['Date']).sort_values('Date').reset_index(drop=True)
                    else:
                        dl_df = new_raw_df.sort_values('Date').reset_index(drop=True)
                else:
                    dl_df = new_raw_df.sort_values('Date').reset_index(drop=True)
                
                if not dl_df.empty:
                    all_dl_data.append(dl_df.copy())
                
                if len(df) < 252:
                    tickers_failed_count += 1
                    continue
                
                # --- חישובים טכניים ---
                df['Daily_Return_%'] = df['Close'].pct_change() * 100
                df['Daily_STDEV'] = df[['Open', 'High', 'Low', 'Close']].std(axis=1)
                df['STDEV_5d'] = df['Close'].rolling(window=5).std()
                df['STDEV_10d'] = df['Close'].rolling(window=10).std()
                df['STDEV_20d'] = df['Close'].rolling(window=20).std()
                df['Max_High_20d'] = df['High'].rolling(window=20).max()
                df['Min_Low_20d'] = df['Low'].rolling(window=20).min()
                
                delta = df['Close'].diff()
                gain = np.where(delta > 0, delta, 0)
                loss = np.where(delta < 0, -delta, 0)
                
                avg_gain = pd.Series(gain).ewm(com=13, min_periods=14).mean().values
                avg_loss = pd.Series(loss).ewm(com=13, min_periods=14).mean().values
                
                avg_loss = np.where(avg_loss == 0, 0.00001, avg_loss)
                rs = avg_gain / avg_loss
                df['RSI_14d'] = 100 - (100 / (1 + rs))
                
                prev_high = df['High'].shift(1)
                prev_low = df['Low'].shift(1)
                prev_close = df['Close'].shift(1)
                
                tr1 = df['High'] - df['Low']
                tr2 = (df['High'] - prev_close).abs()
                tr3 = (df['Low'] - prev_close).abs()
                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                
                df['ATR_14d'] = tr.ewm(com=13, min_periods=14).mean().values
                
                up_move = df['High'] - prev_high
                down_move = prev_low - df['Low']
                
                plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
                minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
                
                smoothed_plus_dm = pd.Series(plus_dm).ewm(com=13, min_periods=14).mean().values
                smoothed_minus_dm = pd.Series(minus_dm).ewm(com=13, min_periods=14).mean().values
                
                safe_atr = np.where(df['ATR_14d'] == 0, 0.00001, df['ATR_14d'])
                df['Plus_DI_14d'] = 100 * (smoothed_plus_dm / safe_atr)
                df['Minus_DI_14d'] = 100 * (smoothed_minus_dm / safe_atr)
                
                di_sum = df['Plus_DI_14d'] + df['Minus_DI_14d']
                di_sum = np.where(di_sum == 0, 0.00001, di_sum)
                dx = 100 * ((df['Plus_DI_14d'] - df['Minus_DI_14d']).abs() / di_sum)
                df['ADX_14d'] = pd.Series(dx).ewm(com=13, min_periods=14).mean().values
                
                raw_stop = df['Max_High_20d'] - (2.5 * df['ATR_14d'])
                df['Dynamic_Stop_Loss'] = np.maximum.accumulate(raw_stop.fillna(0))
                df.loc[df['ATR_14d'].isna(), 'Dynamic_Stop_Loss'] = np.nan
                
                df['RAS_Signal'] = df.apply(calculate_ras_signal, axis=1)
                
                if 'Analyst_Consensus' not in df.columns:
                    df['Analyst_Consensus'] = "N/A"
                    df['Analyst_Upside_%'] = np.nan
                
                df = df.dropna(subset=['Close', 'RSI_14d', 'ADX_14d']).reset_index(drop=True)
                
                if not df.empty:
                    all_combined_data.append(df)
                    if is_new_ticker:
                        tickers_added_count += 1
                    else:
                        tickers_updated_count += 1
                else:
                    tickers_failed_count += 1
                
                time.sleep(0.01)  
                
            except Exception as e:
                print(f"Error processing {ticker}: {e}")
                tickers_failed_count += 1
                continue

    for ticker, last_date in max_dates_per_ticker.items():
        if ticker not in valid_tickers_in_dict:
            ticker_history = existing_df[existing_df['Ticker'] == ticker].copy()
            all_combined_data.append(ticker_history)
            
            # Forward the DL archive for removed tickers
            if not existing_dl_df.empty:
                dl_hist = existing_dl_df[existing_dl_df['Ticker'] == ticker].copy()
                if not dl_hist.empty:
                    all_dl_data.append(dl_hist)
    
    if not all_combined_data:
        print("\n[CRITICAL] No ticker data was successfully calculated. Dataset is empty.")
        return
        
    final_df = pd.concat(all_combined_data, ignore_index=True)
    final_df['Date'] = pd.to_datetime(final_df['Date']).dt.tz_localize(None)
    
    if all_dl_data:
        dl_final_df = pd.concat(all_dl_data, ignore_index=True)
        try:
            dl_final_df.to_csv(dl_archive_path, index=False)
            print(f"\n[SUCCESS] Deep Learning Archive seamlessly saved to: {dl_archive_path} (Total Rows: {len(dl_final_df)})")
        except Exception as e:
            print(f"[CRITICAL ERROR] Failed to save Deep Learning Archive: {e}")
    
    # 🔥 🔥 🔥 מנגנון חישוב וקטורי מואץ לזיהוי רוטציית סקטורים (Sector Regime Shift Indicator) 🔥 🔥 🔥
    print("\n>>> Computing Sector Regime Shift Indicators...")
    # חישוב תשואת השוק הכללית (ממוצע נע של כלל המניות ב-60 הימים האחרונים)
    final_df['Market_Mean_60d'] = final_df.groupby('Date')['Daily_Return_%'].transform('mean').rolling(window=60, min_periods=1).mean()
    # חישוב תשואת הסקטור הספציפי באותה נקודת זמן
    final_df['Sector_Mean_60d'] = final_df.groupby(['Date', 'Sector'])['Daily_Return_%'].transform('mean').rolling(window=60, min_periods=1).mean()
    
    # עמודה 1: ציון המומנטום היחסי של הסקטור מול השוק
    final_df['Sector_Momentum_Score'] = final_df['Sector_Mean_60d'] - final_df['Market_Mean_60d']
    # עמודה 2: קביעת משטר השוק של הסקטור (BULL במומנטום חיובי, BEAR במומנטום שלילי)
    final_df['Sector_Regime'] = np.where(final_df['Sector_Momentum_Score'] >= 0, 'BULL_REGIME', 'BEAR_REGIME')
    
    # ניקוי עמודות העזר הזמניות
    final_df.drop(columns=['Market_Mean_60d', 'Sector_Mean_60d'], errors='ignore', inplace=True)
    
    if not vix_data.empty:
        print(">>> Re-merging historical VIX index risk levels...")
        cols_to_drop = [c for c in ['VIX_Close', 'Market_Fear_Level'] if c in final_df.columns]
        if cols_to_drop:
            final_df.drop(columns=cols_to_drop, inplace=True)
        final_df = pd.merge(final_df, vix_data, on='Date', how='left')
        
    if not tnx_data.empty:
        print(">>> Re-merging historical TNX macro interest rate levels...")
        cols_to_drop = [c for c in ['TNX_Close', 'TNX_Lag1_Return', 'TNX_Trend_5d'] if c in final_df.columns]
        if cols_to_drop:
            final_df.drop(columns=cols_to_drop, inplace=True)
        final_df = pd.merge(final_df, tnx_data, on='Date', how='left')
    
    os.makedirs(folder_path, exist_ok=True)
    
    try:
        final_df.to_csv(full_path, index=False)
        print(f"\n[SUCCESS] Saved updated stock analysis to: {full_path}")
        print(f"Total processed database rows: {len(final_df)}")
        
        print("\n=== Tickers Extraction Summary ===")
        print(f" * Tickers Updated Successfully: {tickers_updated_count}")
        print(f" * New Tickers Added From Scratch: {tickers_added_count}")
        print(f" * Tickers Failed / Delisted: {tickers_failed_count}")
        
        print("\n=== Current Market Signals Summary ===")
        latest_rows = final_df.sort_values('Date').groupby('Ticker').last().reset_index()
        active_latest_rows = latest_rows[latest_rows['Ticker'].isin(valid_tickers_in_dict)]
        
        signal_counts = active_latest_rows['RAS_Signal'].value_counts()
        for signal, count in signal_counts.items():
            print(f" * {signal}: {count} tickers")
            
        buy_tickers = active_latest_rows[active_latest_rows['RAS_Signal'] == 'BUY']
        stop_hit_tickers = active_latest_rows[active_latest_rows['RAS_Signal'] == 'STOP_HIT']['Ticker'].tolist()
        
        if not buy_tickers.empty:
            print(f"\n[TRADE ALERTS - BUY] ({len(buy_tickers)} tickers):")
            for _, row in buy_tickers.iterrows():
                upside_val = row['Analyst_Upside_%']
                upside_str = f" | Potential Upside: {upside_val:.1f}%" if not pd.isna(upside_val) else ""
                print(f"   -> {row['Ticker']} (Wall Street Consensus: {row['Analyst_Consensus']}{upside_str} | Sector Regime: {row['Sector_Regime']})")
        else:
            print("\n[TRADE ALERTS - BUY]: No new buy signals found today.")
            
        if stop_hit_tickers:
            print(f"\n[RISK ALERTS - STOP HIT] ({len(stop_hit_tickers)} tickers):")
            print(", ".join(stop_hit_tickers))
        else:
            print("[RISK ALERTS - STOP HIT]: No tickers hit their trailing stops today.")
        
        if os.path.exists(backup_path):
            os.remove(backup_path)
            print("\n[CLEANUP] Temporary backup file removed successfully.")
    except Exception as e:
        print(f"\n[CRITICAL ERROR] Failed to save new CSV file: {e}")
        if os.path.exists(backup_path):
            print(f"[RECOVERY] Your original data is safe inside: {backup_path}")

if __name__ == "__main__":
    output_directory = os.path.join(os.getcwd(), "financial_data")
    
    # 1. Fetch dynamic active tickers (Quarterly Rebalance logic)
    active_sectors_dict = get_active_tickers(output_directory)
    
    if active_sectors_dict:
        # 2. Run the main pipeline
        download_sp500_full_analysis(active_sectors_dict, output_directory)
        os._exit(0)
    else:
        print("[CRITICAL] Could not load or generate VIP tickers. Pipeline aborted.")
        os._exit(1)
