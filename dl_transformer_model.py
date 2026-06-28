import torch
import torch.nn as nn
import math

class PositionalEncoding(nn.Module):
    """
    Injects some information about the relative or absolute position of the tokens in the sequence.
    Transformers have no inherent concept of time/sequence order, so this is mathematically necessary.
    """
    def __init__(self, d_model, max_len=5000):
        super(PositionalEncoding, self).__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0).transpose(0, 1) # Shape: (max_len, 1, d_model)
        self.register_buffer('pe', pe)

    def forward(self, x):
        # x shape: (seq_len, batch_size, d_model)
        x = x + self.pe[:x.size(0), :]
        return x

class TimeSeriesTransformer(nn.Module):
    """
    Non-Linear Deep Learning Attention Model.
    Designed specifically to find hidden sequence patterns (Alpha) in stock market data.
    """
    def __init__(self, num_features, d_model=64, nhead=4, num_layers=2, dim_feedforward=128, dropout=0.2):
        super(TimeSeriesTransformer, self).__init__()
        
        self.model_type = 'Transformer'
        self.d_model = d_model
        
        # 1. Feature projection (Transforms raw features into the dimension expected by the Transformer)
        self.feature_extractor = nn.Linear(num_features, d_model)
        
        # 2. Time-Sequence Contextualizer
        self.pos_encoder = PositionalEncoding(d_model)
        
        # 3. The Attention Brain
        encoder_layers = nn.TransformerEncoderLayer(d_model=d_model, nhead=nhead, 
                                                    dim_feedforward=dim_feedforward, 
                                                    dropout=dropout, activation='gelu')
        self.transformer_encoder = nn.TransformerEncoder(encoder_layers, num_layers=num_layers)
        
        # 4. Decoder (Predicts Direction: 1 for UP, 0 for DOWN)
        self.fc_out = nn.Sequential(
            nn.Linear(d_model, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
            nn.Sigmoid() # Output a strict probability between 0 and 1
        )
        
    def forward(self, src):
        # src shape from DataLoader: (batch_size, seq_length, num_features)
        
        # PyTorch Transformers expect shape: (seq_length, batch_size, features)
        src = src.transpose(0, 1) 
        
        # Project features to d_model dimension
        src = self.feature_extractor(src) * math.sqrt(self.d_model)
        
        # Inject Time Context
        src = self.pos_encoder(src)
        
        # Pass through Self-Attention Layers
        output = self.transformer_encoder(src)
        
        # We only care about the last output in the sequence (the prediction for tomorrow)
        # output shape is (seq_length, batch_size, d_model)
        last_time_step = output[-1, :, :]
        
        # Final Probability
        pred_prob = self.fc_out(last_time_step)
        return pred_prob
