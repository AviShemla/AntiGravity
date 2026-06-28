import os
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import joblib
from sklearn.preprocessing import StandardScaler
from dl_transformer_model import TimeSeriesTransformer

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
DATA_FILE = os.path.join(BASE_DIR, "financial_data", "Unified_ETF_DeepLearning_Dataset.csv")
MODELS_DIR = os.path.join(BASE_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)

WEIGHTS_FILE = os.path.join(MODELS_DIR, 'transformer_etf_weights.pt')
SCALER_FILE = os.path.join(MODELS_DIR, 'transformer_etf_scaler.pkl')

SEQ_LENGTH = 60
BATCH_SIZE = 64
EPOCHS = 10  # Very quick training for proof of concept
LEARNING_RATE = 1e-4

class ETFDataset(Dataset):
    def __init__(self, df, feature_cols):
        self.sequences = []
        self.labels = []
        
        for ticker, group in df.groupby('Ticker'):
            group = group.sort_values('Date').reset_index(drop=True)
            if len(group) < SEQ_LENGTH:
                continue
                
            features = group[feature_cols].values
            # 1 if Direction == 'UP', 0 otherwise
            targets = (group['Target_Direction'] == 'UP').astype(int).values
            
            for i in range(len(group) - SEQ_LENGTH):
                seq = features[i:i+SEQ_LENGTH]
                label = targets[i+SEQ_LENGTH]
                self.sequences.append(seq)
                self.labels.append(label)
                
    def __len__(self):
        return len(self.sequences)
        
    def __getitem__(self, idx):
        return torch.FloatTensor(self.sequences[idx]), torch.FloatTensor([self.labels[idx]])

def train_etf_model():
    print(">>> Loading Unified ETF Deep Learning Dataset...")
    df = pd.read_csv(DATA_FILE)
    df['Date'] = pd.to_datetime(df['Date'])
    
    # Identify feature columns
    exclude = ['Date', 'Ticker', 'Target_Return_%', 'Target_Direction']
    feature_cols = [c for c in df.columns if c not in exclude]
    print(f"Detected {len(feature_cols)} Macro Features.")
    
    print(">>> Chronological Train/Test split for Scaler fitting...")
    df = df.sort_values('Date').reset_index(drop=True)
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx]
    
    print(">>> Scaling features...")
    scaler = StandardScaler()
    # Fit ONLY on the training split to prevent lookahead bias
    scaler.fit(train_df[feature_cols])
    
    # Transform the entire dataset using the cleanly fitted scaler
    df[feature_cols] = scaler.transform(df[feature_cols])
    joblib.dump(scaler, SCALER_FILE)
    
    print(">>> Building sequences...")
    dataset = ETFDataset(df, feature_cols)
    dataloader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f">>> Using device: {device}")
    
    model = TimeSeriesTransformer(num_features=len(feature_cols), d_model=64, nhead=4, num_layers=2).to(device)
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    
    print(">>> Beginning Training...")
    model.train()
    for epoch in range(EPOCHS):
        total_loss = 0
        for batch_features, batch_labels in dataloader:
            batch_features = batch_features.to(device)
            batch_labels = batch_labels.to(device)
            
            optimizer.zero_grad()
            predictions = model(batch_features)
            loss = criterion(predictions, batch_labels)
            loss.backward()
            optimizer.step()
            
            total_loss += loss.item()
            
        print(f"Epoch {epoch+1}/{EPOCHS} | Loss: {total_loss/len(dataloader):.4f}")
        
    torch.save(model.state_dict(), WEIGHTS_FILE)
    print(f">>> Training Complete. ETF weights saved to {WEIGHTS_FILE}")

if __name__ == '__main__':
    train_etf_model()
