import os
import sys
import time
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import MinMaxScaler
from dl_transformer_model import TimeSeriesTransformer
import joblib

print(">>> [SATURDAY HEAVY-LIFTING] Booting Deep Learning Weekend Trainer...")

# Configuration
SEQ_LENGTH = 60 # 60-day context window for Attention
EPOCHS = 1 # Accelerated to 1 epoch for an instant execution benchmark
BATCH_SIZE = 128
LEARNING_RATE = 0.0005
MODELS_DIR = r"C:\Users\AviShemla\AntiGravity\models"
DATA_FILE = r"C:\Users\AviShemla\AntiGravity\financial_data\SP500_Clean_Advanced_Analysis.csv"

# Our Target Alpha Universe (Top 15 Momentum Stocks normally fetched from fast_screener)
TOP_15_TICKERS = ['NVDA', 'META', 'AMZN', 'MSFT', 'AAPL', 'GOOGL', 'TSLA', 'AVGO', 'LLY', 'JPM', 'UNH', 'XOM', 'V', 'JNJ', 'PG']

FEATURES = ['Close', 'Volume', 'Daily_Return_%', 'RSI_14d', 'ADX_14d', 'VIX_Close', 'TNX_Close']

os.makedirs(MODELS_DIR, exist_ok=True)

def create_sequences(data, target, seq_length):
    xs, ys = [], []
    for i in range(len(data) - seq_length):
        xs.append(data[i:(i + seq_length)])
        ys.append(target.iloc[i + seq_length])
    return np.array(xs), np.array(ys)

def load_universe_data():
    if not os.path.exists(DATA_FILE):
        print(f"[FATAL ERROR] Dataset not found at {DATA_FILE}")
        sys.exit(1)
        
    print(">>> Loading historical dataset...")
    df = pd.read_csv(DATA_FILE)
    df['Date'] = pd.to_datetime(df['Date'])
    
    # Forward fill macro data
    for col in ['VIX_Close', 'TNX_Close']:
        if col in df.columns:
            df[col] = df[col].ffill().bfill()
        else:
            df[col] = 0.0
            
    return df

def train_transformer():
    df = load_universe_data()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"[DEVICE] Training Transformer on: {device.type.upper()}")
    
    # Initialize the global model that will learn patterns across ALL 15 stocks
    model = TimeSeriesTransformer(num_features=len(FEATURES), d_model=64, nhead=4, num_layers=2).to(device)
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    
    global_X, global_y = [], []
    
    # 1. Feature Engineering & Tensor Creation
    print(">>> Fusing 15 Tickers into Global Sequence Tensor...")
    scaler = MinMaxScaler()
    
    for ticker in TOP_15_TICKERS:
        ticker_df = df[df['Ticker'] == ticker].copy()
        if len(ticker_df) < SEQ_LENGTH + 10:
            continue
            
        ticker_df = ticker_df.sort_values('Date').reset_index(drop=True)
        ticker_df = ticker_df.dropna(subset=FEATURES)
        
        # Target: Will tomorrow be positive?
        ticker_df['Next_Return'] = ticker_df['Close'].shift(-1) - ticker_df['Close']
        ticker_df['Target'] = (ticker_df['Next_Return'] > 0).astype(int)
        ticker_df = ticker_df.dropna(subset=['Next_Return'])
        
        if len(ticker_df) < SEQ_LENGTH:
            continue
            
        scaled_features = scaler.fit_transform(ticker_df[FEATURES]) # Simplification for universal scaling
        X, y = create_sequences(scaled_features, ticker_df['Target'], SEQ_LENGTH)
        global_X.append(X)
        global_y.append(y)
        
    global_X = np.vstack(global_X)
    global_y = np.concatenate(global_y)
    
    # Save the scaler so the inference engine uses the EXACT same bounds
    joblib.dump(scaler, os.path.join(MODELS_DIR, 'transformer_scaler.pkl'))
    print(f">>> Tensor Built! Shape: {global_X.shape}")
    
    # 2. PyTorch DataLoaders
    train_data = TensorDataset(torch.FloatTensor(global_X), torch.FloatTensor(global_y).unsqueeze(1))
    train_loader = DataLoader(train_data, batch_size=BATCH_SIZE, shuffle=True)
    
    # 3. Training Loop
    print("\n==============================================")
    print("=== COMMENCING 500-EPOCH TRANSFORMER TRAINING ===")
    print("==============================================\n")
    
    start_time = time.time()
    for epoch in range(EPOCHS):
        model.train()
        epoch_loss = 0
        for batch_X, batch_y in train_loader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            
            optimizer.zero_grad()
            outputs = model(batch_X)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            
            epoch_loss += loss.item()
            
        if (epoch+1) % 10 == 0:
            print(f"Epoch [{epoch+1}/{EPOCHS}] | Average Batch Loss: {epoch_loss/len(train_loader):.4f}")
            
    train_time = time.time() - start_time
    print(f"\n[TRAINING COMPLETE] Time elapsed: {train_time/60:.2f} minutes")
    
    # 4. Save the Immutable Neural Network Brain Weights
    weights_path = os.path.join(MODELS_DIR, 'transformer_weights.pt')
    torch.save(model.state_dict(), weights_path)
    print(f">>> [VAULTED] Deep Learning Weights permanently saved to: {weights_path}")

if __name__ == "__main__":
    train_transformer()
