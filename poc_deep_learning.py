import yfinance as yf
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import MinMaxScaler
import matplotlib.pyplot as plt
import os
import time

# --- CONFIGURATION ---
TICKERS = ['SPY', 'AAPL']
SEQ_LENGTH = 60
EPOCHS = 30
BATCH_SIZE = 32
HIDDEN_SIZE = 64
NUM_LAYERS = 2
LEARNING_RATE = 0.001
ARTIFACT_DIR = r"C:\Users\AviShemla\.gemini\antigravity\brain\b409853a-2b0b-46f6-a175-a22b0cfe3421"

print("========================================")
print("  ANTI-GRAVITY: DEEP LEARNING POC")
print("========================================")
print("NOTE: This is a standalone script. It will not touch the Turso database.")

# --- 1. DATA COLLECTION ---
def get_data(ticker):
    print(f"Downloading 5 years of historical data for {ticker}...")
    df = yf.download(ticker, period="5y", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    df['Return'] = df['Close'].pct_change()
    df['LogReturn'] = np.log(df['Close'] / df['Close'].shift(1))
    df['Volatility_14'] = df['Return'].rolling(14).std()
    
    df = df.dropna()
    return df

# --- 2. LSTM MODEL DEFINITION ---
class AntiGravityLSTM(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers):
        super(AntiGravityLSTM, self).__init__()
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

def create_sequences(data, seq_length):
    xs = []
    ys = []
    for i in range(len(data) - seq_length):
        x = data[i:(i + seq_length)]
        y = data[i + seq_length, 0] # First column is target
        xs.append(x)
        ys.append(y)
    return np.array(xs), np.array(ys)

# --- 3. TRAINING LOOP ---
def train_and_predict(ticker):
    df = get_data(ticker)
    
    df['HL_Spread'] = (df['High'] - df['Low']) / df['Close']
    df['CO_Spread'] = (df['Close'] - df['Open']) / df['Close']
    
    features = ['LogReturn', 'Volatility_14', 'HL_Spread', 'CO_Spread']
    data = df[features].values
    
    scaler = MinMaxScaler()
    data_scaled = scaler.fit_transform(data)
    
    target_scaler = MinMaxScaler()
    target_scaler.fit(df[['LogReturn']].values)
    
    X, y = create_sequences(data_scaled, SEQ_LENGTH)
    
    split = int(0.8 * len(X))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]
    
    X_train_t = torch.tensor(X_train, dtype=torch.float32)
    y_train_t = torch.tensor(y_train, dtype=torch.float32).view(-1, 1)
    X_test_t = torch.tensor(X_test, dtype=torch.float32)
    y_test_t = torch.tensor(y_test, dtype=torch.float32).view(-1, 1)
    
    train_dataset = TensorDataset(X_train_t, y_train_t)
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    
    model = AntiGravityLSTM(input_size=len(features), hidden_size=HIDDEN_SIZE, num_layers=NUM_LAYERS)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    
    print(f"[{ticker}] Training LSTM model for {EPOCHS} epochs...")
    start_time = time.time()
    
    for epoch in range(EPOCHS):
        model.train()
        epoch_loss = 0
        for batch_X, batch_y in train_loader:
            optimizer.zero_grad()
            outputs = model(batch_X)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            
        if (epoch+1) % 10 == 0:
            print(f"  -> Epoch {epoch+1}/{EPOCHS}, Loss: {epoch_loss/len(train_loader):.5f}")
            
    print(f"[{ticker}] Training Complete. Took {time.time() - start_time:.1f} seconds.")
    
    model.eval()
    with torch.no_grad():
        test_predictions = model(X_test_t).numpy()
        test_actuals = y_test_t.numpy()
        
    test_predictions_real = target_scaler.inverse_transform(test_predictions)
    test_actuals_real = target_scaler.inverse_transform(test_actuals)
    
    last_60_days = data_scaled[-SEQ_LENGTH:]
    last_60_tensor = torch.tensor(last_60_days, dtype=torch.float32).unsqueeze(0)
    with torch.no_grad():
        tomorrow_pred_scaled = model(last_60_tensor).numpy()
    tomorrow_pred_real = target_scaler.inverse_transform(tomorrow_pred_scaled)[0][0]
    
    direction = "UP" if tomorrow_pred_real > 0 else "DOWN"
    
    # PLOTTING
    plt.figure(figsize=(10, 5))
    cum_actual = np.exp(np.cumsum(test_actuals_real)) - 1
    cum_pred = np.exp(np.cumsum(test_predictions_real)) - 1
    
    plt.plot(cum_actual, label='Actual Cumulative Return', color='blue')
    plt.plot(cum_pred, label='LSTM Predicted Cumulative Return', color='orange')
    plt.title(f"{ticker} - LSTM Non-Linear Predictive Model (Test Data)")
    plt.xlabel("Test Days")
    plt.ylabel("Cumulative Return")
    plt.legend()
    plt.grid(True)
    
    plot_path = os.path.join(ARTIFACT_DIR, f"{ticker}_LSTM_Prediction.png")
    plt.savefig(plot_path)
    plt.close()
    
    print(f"\n=> {ticker} POC COMPLETE <=")
    print(f"   LSTM Neural Network Prediction for Tomorrow: {direction} ({tomorrow_pred_real*100:.2f}%)")
    print(f"   Chart saved to: {plot_path}\n")
    
    return direction, tomorrow_pred_real

if __name__ == "__main__":
    results = {}
    for ticker in TICKERS:
        d, v = train_and_predict(ticker)
        results[ticker] = (d, v)
        
    print("========================================")
    print("      DEEP LEARNING POC FINAL RESULTS")
    print("========================================")
    for t, (d, v) in results.items():
        print(f"  {t}: {d} (Expected LogReturn: {v*100:.2f}%)")
