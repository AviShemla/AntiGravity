import os
import sys
import pandas as pd
import numpy as np
import time

print(">>> Booting up the AntiGravity PyTorch LSTM Shadow Engine...")

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    from sklearn.preprocessing import MinMaxScaler
    from sklearn.metrics import accuracy_score, precision_score, classification_report
except ImportError:
    print("[FATAL ERROR] PyTorch or Scikit-Learn not installed. Please wait for pip installation to finish.")
    os._exit(1)

# Configuration
TICKER = 'AAPL' # Using Apple as the hyper-liquid benchmark
SEQ_LENGTH = 30 # Number of lookback days
EPOCHS = 25
BATCH_SIZE = 64
LEARNING_RATE = 0.001
TEST_YEAR = 2026

# Features
FEATURES = ['Close', 'Volume', 'Daily_Return_%', 'RSI_14d', 'ADX_14d', 'VIX_Close', 'TNX_Close']

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'SP500_Clean_Advanced_Analysis.csv')

def load_and_preprocess_data():
    print(f">>> Loading Master Dataset from {DATA_FILE}...")
    if not os.path.exists(DATA_FILE):
        print(f"[ERROR] Could not find dataset at {DATA_FILE}")
        os._exit(1)
        
    df = pd.read_csv(DATA_FILE)
    df['Date'] = pd.to_datetime(df['Date'])
    
    # Filter for target ticker
    df = df[df['Ticker'] == TICKER].copy()
    df = df.sort_values('Date').reset_index(drop=True)
    
    print(f"[{TICKER}] Extracted {len(df)} historical rows.")
    
    # Forward fill macro data in case of missing days
    for col in ['VIX_Close', 'TNX_Close']:
        if col in df.columns:
            df[col] = df[col].ffill().bfill()
        else:
            df[col] = 0.0
            
    # Clean NaNs
    df = df.dropna(subset=FEATURES).copy()
    
    # Create the Target: Will the NEXT day's return be positive?
    df['Next_Return'] = df['Close'].shift(-1) - df['Close']
    df['Target'] = (df['Next_Return'] > 0).astype(int)
    
    # Drop the last row since we don't have tomorrow's truth yet
    df = df.dropna(subset=['Next_Return']).copy()
    
    print(f"[{TICKER}] Cleaned data length: {len(df)} rows.")
    return df

def create_sequences(data, target, dates, seq_length):
    xs, ys, ds = [], [], []
    for i in range(len(data) - seq_length):
        x = data[i:(i + seq_length)]
        y = target.iloc[i + seq_length]
        d = dates.iloc[i + seq_length]
        xs.append(x)
        ys.append(y)
        ds.append(d)
    return np.array(xs), np.array(ys), np.array(ds)

class ShadowLSTM(nn.Module):
    def __init__(self, input_size, hidden_size=64, num_layers=2, dropout=0.2):
        super(ShadowLSTM, self).__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=dropout)
        self.fc1 = nn.Linear(hidden_size, 32)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout)
        self.fc2 = nn.Linear(32, 1)
        self.sigmoid = nn.Sigmoid()
        
    def forward(self, x):
        h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
        c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
        
        out, _ = self.lstm(x, (h0, c0))
        # Take the output of the last time step
        out = out[:, -1, :]
        out = self.fc1(out)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.fc2(out)
        out = self.sigmoid(out)
        return out

def run_experiment():
    df = load_and_preprocess_data()
    
    # Train / Test split
    train_df = df[df['Date'].dt.year < TEST_YEAR].copy()
    test_df = df[df['Date'].dt.year >= TEST_YEAR].copy()
    
    print(f"Train Dataset: {len(train_df)} rows")
    print(f"Test Dataset ({TEST_YEAR}): {len(test_df)} rows")
    
    # Scaling
    scaler = MinMaxScaler()
    train_scaled = scaler.fit_transform(train_df[FEATURES])
    test_scaled = scaler.transform(test_df[FEATURES])
    
    # Create sequences
    print(f"\n>>> Transforming flat data into {SEQ_LENGTH}-Day 3D Tensors...")
    X_train, y_train, _ = create_sequences(train_scaled, train_df['Target'], train_df['Date'], SEQ_LENGTH)
    X_test, y_test, dates_test = create_sequences(test_scaled, test_df['Target'], test_df['Date'], SEQ_LENGTH)
    
    print(f"X_train shape: {X_train.shape}")
    print(f"X_test shape: {X_test.shape}")
    
    # Convert to PyTorch Tensors
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"\n[DEVICE] Computation will run on: {device.type.upper()}")
    
    train_data = TensorDataset(torch.FloatTensor(X_train), torch.FloatTensor(y_train).unsqueeze(1))
    test_data = TensorDataset(torch.FloatTensor(X_test), torch.FloatTensor(y_test).unsqueeze(1))
    
    train_loader = DataLoader(train_data, batch_size=BATCH_SIZE, shuffle=False)
    
    # Initialize Model
    model = ShadowLSTM(input_size=len(FEATURES)).to(device)
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    
    print("\n==============================================")
    print("=== STARTING NON-LINEAR DEEP LEARNING (LSTM) ===")
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
            
        if (epoch+1) % 5 == 0:
            print(f"Epoch [{epoch+1}/{EPOCHS}] | Loss: {epoch_loss/len(train_loader):.4f}")
            
    train_time = time.time() - start_time
    print(f"\n[TRAINING COMPLETE] Time elapsed: {train_time:.2f} seconds")
    
    # Evaluation
    print("\n>>> Running Out-of-Sample Evaluation on 2026 Unseen Data...")
    model.eval()
    with torch.no_grad():
        test_inputs = torch.FloatTensor(X_test).to(device)
        predictions = model(test_inputs).cpu().numpy()
        
    pred_classes = (predictions > 0.55).astype(int) # Using a strict threshold of 55%
    
    acc = accuracy_score(y_test, pred_classes)
    prec = precision_score(y_test, pred_classes, zero_division=0)
    
    print(f"\n=== SHADOW LSTM RESULTS FOR {TICKER} (2026) ===")
    print(f" * Raw Accuracy (Direction): {acc*100:.2f}%")
    print(f" * Precision (When predicting UP, % correct): {prec*100:.2f}%")
    
    print("\nDetailed Classification Report:")
    print(classification_report(y_test, pred_classes))
    
    # Simulate PnL
    test_df_trimmed = test_df.iloc[SEQ_LENGTH:].copy()
    test_df_trimmed['LSTM_Signal'] = pred_classes
    test_df_trimmed['Strategy_Return'] = np.where(test_df_trimmed['LSTM_Signal'] == 1, test_df_trimmed['Next_Return'] / test_df_trimmed['Close'], 0)
    test_df_trimmed['Buy_Hold_Return'] = test_df_trimmed['Next_Return'] / test_df_trimmed['Close']
    
    strat_cum = (1 + test_df_trimmed['Strategy_Return']).cumprod().iloc[-1] - 1
    bh_cum = (1 + test_df_trimmed['Buy_Hold_Return']).cumprod().iloc[-1] - 1
    
    print("\n=== HYPOTHETICAL PnL EVALUATION ===")
    print(f" * Buy & Hold {TEST_YEAR} Return: {bh_cum*100:.2f}%")
    print(f" * LSTM Strategy {TEST_YEAR} Return: {strat_cum*100:.2f}%")
    
    if strat_cum > bh_cum:
        print("\n[SUCCESS] The Non-Linear Engine successfully generated Alpha over Buy & Hold!")
    else:
        print("\n[WARNING] The LSTM failed to beat Buy & Hold. Needs more epochs or Transformer attention layers.")

if __name__ == "__main__":
    run_experiment()
