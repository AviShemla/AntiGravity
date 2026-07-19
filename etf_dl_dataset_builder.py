import os
import pandas as pd
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "financial_data")

ETF_UNIVERSE = ['XLK', 'XLF', 'XLV', 'XLE', 'XLY', 'XLP', 'XLU', 'XLI', 'XLB', 'XLC', 'XLRE']

def build_dataset():
    all_data = []
    
    for etf in ETF_UNIVERSE:
        file_path = os.path.join(DATA_DIR, f"{etf}_Hybrid_Matrix.csv")
        if not os.path.exists(file_path):
            print(f"Skipping {etf}: Matrix not found.")
            continue
            
        df = pd.read_csv(file_path)
        
        rename_map = {
            f'{etf}_Return_%': 'Target_Return_%',
            f'{etf}_Direction': 'Target_Direction',
            f'{etf}_Lag1': 'Target_Lag1',
            f'{etf}_Lag2': 'Target_Lag2',
            f'{etf}_Lag3': 'Target_Lag3',
            f'{etf}_Lag4': 'Target_Lag4',
            f'{etf}_Lag5': 'Target_Lag5',
            f'{etf}_Daily_STDEV': 'Target_Daily_STDEV',
        }
        
        df = df.rename(columns=rename_map)
        df['Ticker'] = etf
        
        universal = ['Date', 'Target_Return_%', 'Target_Direction', 'Target_Lag1', 'Target_Lag2', 'Target_Lag3', 'Target_Lag4', 'Target_Lag5', 'Target_Daily_STDEV', 'SPY_Lag1', 'SPY_Lag2', 'SPY_Lag3', 'SPY_Lag4', 'SPY_Lag5', 'TLT_Lag1', 'TLT_Lag2', 'TLT_Lag3', 'TLT_Lag4', 'TLT_Lag5', 'GLD_Lag1', 'GLD_Lag2', 'GLD_Lag3', 'GLD_Lag4', 'GLD_Lag5', 'UUP_Lag1', 'UUP_Lag2', 'UUP_Lag3', 'UUP_Lag4', 'UUP_Lag5', 'Ticker']
        
        cols_to_drop = []
        for col in df.columns:
            if col not in universal and ('_Lag' in col or '_Nested_P_UP' in col):
                cols_to_drop.append(col)
                
        df = df.drop(columns=cols_to_drop)
        all_data.append(df)
        
    if not all_data:
        print("Warning: No ETF matrices found. Skipping unified dataset build.")
        return
        
    final_df = pd.concat(all_data, ignore_index=True)
    final_df['Date'] = pd.to_datetime(final_df['Date'])
    final_df = final_df.sort_values(by=['Date', 'Ticker'])
    final_df = final_df.fillna(0)
    
    out_path = os.path.join(DATA_DIR, "Unified_ETF_DeepLearning_Dataset.csv")
    final_df.to_csv(out_path, index=False)
    print(f"Unified dataset created at {out_path} with shape {final_df.shape}")

if __name__ == '__main__':
    build_dataset()
