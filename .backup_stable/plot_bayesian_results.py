import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import matplotlib.dates as mdates

excel_path = r'C:\Users\AviShemla\AntiGravity\financial_data\Top5_Bayesian_Scorecard.xlsx'
output_dir = r'C:\Users\AviShemla\AntiGravity\financial_data'
os.makedirs(output_dir, exist_ok=True)

tickers = ['MU', 'CRL', 'NCLH', 'ROKU', 'TSLA']

for ticker in tickers:
    print(f"Plotting {ticker}...")
    df = pd.read_excel(excel_path, sheet_name=ticker)
    
    dates = pd.to_datetime(df['Date'])
    actual_ret = df['Raw_Return_%']
    p_up = df['Bayesian_Prob_UP']
    
    # Calculate Strategy Return
    # Long if P > 0.65, Short if P < 0.35
    strategy_returns = []
    for ret, p in zip(actual_ret, p_up):
        if p > 0.65:
            strategy_returns.append(ret)
        elif p < 0.35:
            strategy_returns.append(-ret)
        else:
            strategy_returns.append(0.0)
            
    strategy_returns = np.array(strategy_returns)
    
    cum_actual = np.cumsum(actual_ret)
    cum_strategy = np.cumsum(strategy_returns)
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 12))
    fig.suptitle(f'{ticker} — Bayesian Model vs Actual Returns (30-Day Out-of-Sample)', fontsize=16, fontweight='bold')
    
    # --- Top Subplot: Daily Return vs Probability ---
    ax1.plot(dates, actual_ret, color='#8ea9db', label='Actual Daily Return %', linewidth=2)
    ax1.set_ylabel('Actual Return %', color='#8ea9db', fontweight='bold')
    ax1.tick_params(axis='y', labelcolor='#8ea9db')
    ax1.grid(True, alpha=0.3)
    
    ax1_2 = ax1.twinx()
    ax1_2.plot(dates, p_up, color='red', label='Bayesian P(UP)', linewidth=2)
    ax1_2.axhline(0.65, color='green', linestyle='--', alpha=0.5, label='Buy Threshold (0.65)')
    ax1_2.axhline(0.35, color='orange', linestyle='--', alpha=0.5, label='Sell Threshold (0.35)')
    ax1_2.axhline(0.50, color='gray', linestyle=':', alpha=0.3)
    ax1_2.set_ylabel('Bayesian Probability P(UP)', color='red', fontweight='bold')
    ax1_2.tick_params(axis='y', labelcolor='red')
    ax1_2.set_ylim(0, 1)
    
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax1_2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left')
    ax1.set_title('Daily Return vs Model Confidence', fontsize=12)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    
    # --- Bottom Subplot: Cumulative Returns ---
    ax2.plot(dates, cum_actual, color='#8ea9db', label='Buy & Hold Cumulative Return %', linewidth=2)
    ax2.plot(dates, cum_strategy, color='#ff9900', label='Bayesian Strategy Cumulative Return %', linewidth=2)
    ax2.set_ylabel('Cumulative Return %', fontweight='bold')
    ax2.set_xlabel('Date')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper left')
    ax2.set_title('Strategy vs Buy & Hold (Cumulative)', fontsize=12)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    
    plt.tight_layout()
    fig.subplots_adjust(top=0.92)
    
    # Save directly to output directory
    save_path = os.path.join(output_dir, f"{ticker}_bayesian_plot.png")
    plt.savefig(save_path, dpi=150)
    plt.close()
    
    print(f"Saved {save_path}")
