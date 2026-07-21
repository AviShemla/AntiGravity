import torch
import torch.nn as nn
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.preprocessing import StandardScaler
import time
import warnings

warnings.filterwarnings("ignore")

# Define features
FEATURES = ['Return', 'SMA_10', 'SMA_50', 'Volatility_20', 'RSI_14']
SEQ_LENGTH = 30
EPOCHS = 10
LR = 0.005

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

def fetch_and_prep_data(ticker, target_date=None):
    df = yf.download(ticker, period="5y", progress=False)
    if target_date:
        df = df[df.index <= target_date]
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

def process_stock(ticker, target_date=None):
    start_time = time.time()
    try:
        df = fetch_and_prep_data(ticker, target_date)
        if df.empty or len(df) < SEQ_LENGTH + 10:
            return ticker, 0.5, 0.0, "Failed (No Data)"
            
        feature_data = df[FEATURES].values
        target_data = df['Target'].values
        
        last_close = df['Close'].iloc[-1]
        
        scaler = StandardScaler()
        feature_data = scaler.fit_transform(feature_data)
        
        X, y = create_sequences(feature_data, target_data, SEQ_LENGTH)
        split = int(0.8 * len(X))
        X_train, y_train = X[:split], y[:split]
        
        X_train_t = torch.FloatTensor(X_train)
        y_train_t = torch.FloatTensor(y_train).view(-1, 1)
        
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
            
        model.eval()
        last_seq = feature_data[-SEQ_LENGTH:]
        last_seq_t = torch.FloatTensor(last_seq).unsqueeze(0)
        
        with torch.no_grad():
            pred = model(last_seq_t).item()
            
        # Convert prediction magnitude to a probability-like score (50% base)
        # If pred is > 0, probability > 0.5. If pred < 0, probability < 0.5.
        prob = float(1 / (1 + np.exp(-pred * 100)))
        
        return ticker, prob, float(last_close), None
    except Exception as e:
        return ticker, 0.5, 0.0, str(e)
