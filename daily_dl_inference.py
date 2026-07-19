import os
import sys
import pandas as pd
import numpy as np
import torch
import joblib
from dl_transformer_model import TimeSeriesTransformer
import etf_dl_dataset_builder

print(">>> [DAILY INFERENCE] Waking up Deep Learning Shadow Engine...")

SEQ_LENGTH = 60
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
WEIGHTS_FILE = os.path.join(MODELS_DIR, 'transformer_weights.pt')
SCALER_FILE = os.path.join(MODELS_DIR, 'transformer_scaler.pkl')
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'SP500_Clean_Advanced_Analysis.csv')

ETF_WEIGHTS_FILE = os.path.join(MODELS_DIR, 'transformer_etf_weights.pt')
ETF_SCALER_FILE = os.path.join(MODELS_DIR, 'transformer_etf_scaler.pkl')
ETF_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Unified_ETF_DeepLearning_Dataset.csv')

def get_dynamic_assets():
    import pandas as pd
    import os, sys
    
    portfolio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Active_Portfolio.csv')
    stocks = ['NVDA', 'AAPL']
    etfs = ['SPY', 'QQQ']
    
    if os.path.exists(portfolio_path):
        try:
            df = pd.read_csv(portfolio_path)
            # Limit to exactly Top 10 Stocks mathematically extracted from the live portfolio
            stocks = df['Ticker'].head(10).tolist()
            
            # Dynamic ETF Extraction based on Whale Priors
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            from etf_whale_extractor import get_60_percent_whales_with_weights
            
            fund_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'SP500_Fundamentals_Score.csv')
            fund_df = pd.read_csv(fund_path).set_index('Ticker') if os.path.exists(fund_path) else pd.DataFrame()
            
            all_etfs = ['XLK', 'XLF', 'XLV', 'XLE', 'XLY', 'XLP', 'XLU', 'XLI', 'XLB', 'XLC', 'XLRE']
            scores = {}
            for e in all_etfs:
                try:
                    whales = get_60_percent_whales_with_weights(e)
                    s = 0.0
                    w_tot = 0.0
                    for w, weight in whales.items():
                        if w in df['Ticker'].values:  # Must be an active target stock
                            val = fund_df.loc[w, 'Fundamental_Score'] if w in fund_df.index else pd.NA
                            if isinstance(val, pd.Series): val = val.iloc[0]
                            if pd.notna(val):
                                s += float(val) * float(weight)
                                w_tot += float(weight)
                    if w_tot > 0:
                        scores[e] = s / w_tot
                except: pass
            
            # Limit to exactly Top 10 ETFs mathematically linked to the active stock whales
            top_etfs = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
            if len(top_etfs) > 0:
                etfs = [x[0] for x in top_etfs]
        except Exception as e:
            print(f"Warning extracting dynamic assets: {e}")
    return stocks, etfs

TARGET_UNIVERSE, ETF_UNIVERSE = get_dynamic_assets()

FEATURES = ['Close', 'Volume', 'Daily_Return_%', 'RSI_14d', 'ADX_14d', 'VIX_Close', 'TNX_Close']

def run_daily_inference():
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    predictions = []
    
    # ==========================================
    # 1. STOCK INFERENCE (Original Brain)
    # ==========================================
    if os.path.exists(WEIGHTS_FILE) and os.path.exists(SCALER_FILE):
        print(">>> Loading pre-trained Neural Network STOCK weights...")
        scaler = joblib.load(SCALER_FILE)
        model = TimeSeriesTransformer(num_features=len(FEATURES), d_model=64, nhead=4, num_layers=2).to(device)
        model.load_state_dict(torch.load(WEIGHTS_FILE, map_location=device, weights_only=True))
        model.eval()
        
        df = pd.read_csv(DATA_FILE)
        df['Date'] = pd.to_datetime(df['Date'])
        for col in ['VIX_Close', 'TNX_Close']:
            if col in df.columns:
                df[col] = df[col].ffill().bfill()
            else: df[col] = 0.0

        with torch.no_grad():
            for ticker in TARGET_UNIVERSE:
                ticker_df = df[df['Ticker'] == ticker].copy().sort_values('Date').reset_index(drop=True).dropna(subset=FEATURES)
                if len(ticker_df) < SEQ_LENGTH:
                    continue
                
                recent_data = ticker_df.iloc[-SEQ_LENGTH:].copy()
                last_date = recent_data['Date'].iloc[-1]
                last_close = recent_data['Close'].iloc[-1]
                
                scaled_features = scaler.transform(recent_data[FEATURES])
                tensor_input = torch.FloatTensor(scaled_features).unsqueeze(0).to(device)
                
                prediction_prob = model(tensor_input).item()
                predictions.append({
                    'Date': last_date.strftime('%Y-%m-%d'),
                    'Ticker': ticker,
                    'Last_Close': last_close,
                    'Transformer_P(UP)': round(prediction_prob, 4),
                    'AI_Signal': 'BUY' if prediction_prob > 0.55 else 'HOLD',
                    'Engine': 'StockBrain'
                })
                
    # ==========================================
    # 2. ETF INFERENCE (Macro Brain)
    # ==========================================
    if os.path.exists(ETF_WEIGHTS_FILE) and os.path.exists(ETF_SCALER_FILE):
        print(">>> Building latest Unified ETF Dataset...")
        etf_dl_dataset_builder.build_dataset()
        
        if os.path.exists(ETF_DATA_FILE):
            print(">>> Loading pre-trained Neural Network ETF MACRO weights...")
            etf_scaler = joblib.load(ETF_SCALER_FILE)
            
            etf_df = pd.read_csv(ETF_DATA_FILE)
            etf_df['Date'] = pd.to_datetime(etf_df['Date'])
            
            exclude = ['Date', 'Ticker', 'Target_Return_%', 'Target_Direction']
            if hasattr(etf_scaler, 'feature_names_in_'):
                etf_feature_cols = list(etf_scaler.feature_names_in_)
            else:
                etf_feature_cols = [c for c in etf_df.columns if c not in exclude]
                
            for col in etf_feature_cols:
                if col not in etf_df.columns:
                    etf_df[col] = 0.0
                    
            etf_model = TimeSeriesTransformer(num_features=len(etf_feature_cols), d_model=64, nhead=4, num_layers=2).to(device)
            etf_model.load_state_dict(torch.load(ETF_WEIGHTS_FILE, map_location=device, weights_only=True))
            etf_model.eval()
            
            with torch.no_grad():
                for ticker in ETF_UNIVERSE:
                    ticker_df = etf_df[etf_df['Ticker'] == ticker].copy().sort_values('Date').reset_index(drop=True)
                    if len(ticker_df) < SEQ_LENGTH:
                        continue
                    
                    recent_data = ticker_df.iloc[-SEQ_LENGTH:].copy()
                    last_date = recent_data['Date'].iloc[-1]
                    last_close = 0
                    
                    scaled_features = etf_scaler.transform(recent_data[etf_feature_cols])
                    tensor_input = torch.FloatTensor(scaled_features).unsqueeze(0).to(device)
                    
                    prediction_prob = etf_model(tensor_input).item()
                    predictions.append({
                        'Date': last_date.strftime('%Y-%m-%d'),
                        'Ticker': ticker,
                        'Last_Close': last_close,
                        'Transformer_P(UP)': round(prediction_prob, 4),
                        'AI_Signal': 'BUY' if prediction_prob > 0.55 else 'HOLD',
                        'Engine': 'MacroBrain'
                    })
        else:
            print(">>> Skipping ETF Inference: Unified dataset missing (Day 1 Scenario).")
            
    # ==========================================
    # 3. ONLINE LSTM SHADOW INFERENCE
    # ==========================================
    print("\n>>> Waking up Online LSTM Shadow Engine (Phase 3)...")
    try:
        import dl_lstm_shadow
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        print(f"    -> Running fast online LSTM training for {len(TARGET_UNIVERSE)} stocks...")
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_t = {executor.submit(dl_lstm_shadow.process_stock, t): t for t in TARGET_UNIVERSE}
            for future in as_completed(future_to_t):
                t = future_to_t[future]
                try:
                    ticker, prob, last_close, err = future.result()
                    if err is None:
                        predictions.append({
                            'Date': pd.Timestamp.now().strftime('%Y-%m-%d'),
                            'Ticker': ticker,
                            'Last_Close': last_close,
                            'Transformer_P(UP)': round(prob, 4),
                            'AI_Signal': 'BUY' if prob > 0.55 else 'HOLD',
                            'Engine': 'LSTM_Shadow_V2'
                        })
                    else:
                        print(f"    [WARNING] LSTM failed on {t}: {err}")
                except Exception as ex:
                    print(f"    [WARNING] LSTM crashed on {t}: {ex}")
    except Exception as e:
        print(f"    [ERROR] Failed to run LSTM Shadow Engine: {e}")
                
    # Save the Shadow Scorecard
    if predictions:
        results_df = pd.DataFrame(predictions)
        results_df = results_df.sort_values(by='Transformer_P(UP)', ascending=False)
        
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Shadow_Transformer_Scorecard.csv')
        results_df.to_csv(output_path, index=False)
        
        print("\n==============================================")
        print("=== DEEP LEARNING INFERENCE COMPLETE ===")
        print(f"=== Shadow Scorecard saved to: {output_path} ===")
        print("==============================================\n")
        print(results_df.head(20).to_string())

if __name__ == "__main__":
    run_daily_inference()
