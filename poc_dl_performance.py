import torch
import torch.nn as nn
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.preprocessing import StandardScaler
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# Suppress warnings
import warnings
warnings.filterwarnings("ignore")

# Define features
FEATURES = ['Return', 'SMA_10', 'SMA_50', 'Volatility_20', 'RSI_14']
SEQ_LENGTH = 30
EPOCHS = 10  # Very low epochs for fast benchmarking
LR = 0.005

# 1. Define the LSTM Neural Network
class LSTMShadowPredictor(nn.Module):
    def __init__(self, input_size, hidden_size=64, num_layers=2):
        super(LSTMShadowPredictor, self).__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=0.2)
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
        c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
        out, _ = self.lstm(x, (h0, c0))
        out = self.fc(out[:, -1, :])
        return out

def compute_rsi(data, window=14):
    delta = data.diff()
    up, down = delta.copy(), delta.copy()
    up[up < 0] = 0
    down[down > 0] = 0
    roll_up = up.rolling(window).mean()
    roll_down = down.abs().rolling(window).mean()
    RS = roll_up / roll_down
    RSI = 100.0 - (100.0 / (1.0 + RS))
    return RSI.fillna(50)

def fetch_and_prep_data(ticker):
    df = yf.download(ticker, period="5y", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    df['Return'] = df['Close'].pct_change()
    df['SMA_10'] = df['Close'].rolling(10).mean() / df['Close'] - 1
    df['SMA_50'] = df['Close'].rolling(50).mean() / df['Close'] - 1
    df['Volatility_20'] = df['Return'].rolling(20).std()
    df['RSI_14'] = compute_rsi(df['Close']) / 100.0
    
    df['Target'] = df['Return'].shift(-1)
    df = df.dropna()
    return df

def create_sequences(data, target, seq_length):
    xs, ys = [], []
    for i in range(len(data) - seq_length):
        x = data[i:(i + seq_length)]
        y = target[i + seq_length]
        xs.append(x)
        ys.append(y)
    return np.array(xs), np.array(ys)

def process_stock(ticker):
    start_time = time.time()
    try:
        # Fetch data
        df = fetch_and_prep_data(ticker)
        if df.empty or len(df) < SEQ_LENGTH + 10:
            return ticker, "Failed (No Data)", 0.0, 0.0
            
        feature_data = df[FEATURES].values
        target_data = df['Target'].values
        
        # Scale
        scaler = StandardScaler()
        feature_data = scaler.fit_transform(feature_data)
        
        X, y = create_sequences(feature_data, target_data, SEQ_LENGTH)
        
        # Split (Use last 80% for fast training)
        split = int(0.8 * len(X))
        X_train, y_train = X[:split], y[:split]
        
        X_train_t = torch.FloatTensor(X_train)
        y_train_t = torch.FloatTensor(y_train).view(-1, 1)
        
        # Train LSTM
        model = LSTMShadowPredictor(input_size=len(FEATURES))
        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=LR)
        
        model.train()
        for epoch in range(EPOCHS):
            optimizer.zero_grad()
            outputs = model(X_train_t)
            loss = criterion(outputs, y_train_t)
            loss.backward()
            optimizer.step()
            
        # Predict tomorrow
        model.eval()
        last_seq = feature_data[-SEQ_LENGTH:]
        last_seq_t = torch.FloatTensor(last_seq).unsqueeze(0)
        
        with torch.no_grad():
            pred = model(last_seq_t).item()
            
        direction = "UP" if pred > 0 else "DOWN"
        elapsed = time.time() - start_time
        
        return ticker, direction, pred * 100, elapsed
    except Exception as e:
        return ticker, f"Error: {e}", 0.0, time.time() - start_time

if __name__ == "__main__":
    print("=====================================================")
    print("  DEEP LEARNING (LSTM) PERFORMANCE BENCHMARK")
    print("=====================================================\n")
    
    # 1. Read Prod 10 Stocks
    portfolio_path = r'C:\Users\AviShemla\AntiGravity\financial_data\Active_Portfolio.csv'
    if not os.path.exists(portfolio_path):
        print(f"Error: {portfolio_path} not found.")
        exit(1)
        
    portfolio_df = pd.read_csv(portfolio_path)
    tickers = portfolio_df['Ticker'].tolist()
    
    print(f"[INIT] Loaded {len(tickers)} dynamically chosen stocks from Prod.")
    print(f"       Tickers: {', '.join(tickers)}")
    print("\n[EXECUTION] Booting 3-Thread LSTM Worker Pool...\n")
    
    global_start = time.time()
    results = []
    
    # 2. Multi-threaded Execution
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_ticker = {executor.submit(process_stock, ticker): ticker for ticker in tickers}
        
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                t, direction, pred_return, elapsed = future.result()
                print(f"[{ticker}] LSTM Computed in {elapsed:.1f}s | Direction: {direction} ({pred_return:+.3f}%)")
                results.append((ticker, direction, pred_return, elapsed))
            except Exception as e:
                print(f"[{ticker}] CRASHED: {e}")
                
    total_elapsed = time.time() - global_start
    print("\n=====================================================")
    print("  BENCHMARK COMPLETE")
    print("=====================================================")
    print(f"Total Execution Time: {total_elapsed:.1f} seconds ({total_elapsed/60:.1f} minutes)")
    avg_time = np.mean([r[3] for r in results if r[3] > 0])
    print(f"Average Time per Stock: {avg_time:.1f} seconds")
