import pandas as pd
import yfinance as yf
import os
import time
from etf_whale_extractor import get_60_percent_whales

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
os.makedirs(BASE_DIR, exist_ok=True)

PORTFOLIO_PATH = os.path.join(BASE_DIR, 'Active_Portfolio.csv')
OUTPUT_PATH = os.path.join(BASE_DIR, 'SP500_Fundamentals_Score.csv')
TARGET_ETFS = ['XLK', 'XLV', 'XLY', 'XLF']

def calculate_fundamental_score(info):
    """
    Calculates a score between -1.0 (Terrible) and 1.0 (Excellent)
    Based on Profitability, Growth, Debt, and Analyst Consensus.
    """
    score = 0.0
    
    # 1. Profitability (Net Margin)
    margin = info.get('profitMargins', 0)
    if margin is None: margin = 0
    if margin > 0.20: score += 0.4
    elif margin > 0.10: score += 0.2
    elif margin < 0: score -= 0.4
    
    # 2. Financial Health (Debt to Equity)
    # Lower is better. Normal is 1.0 to 1.5. 
    dte = info.get('debtToEquity', 100)
    if dte is None: dte = 100
    if dte < 50: score += 0.3
    elif dte > 200: score -= 0.3
    
    # 3. Valuation/Growth (Trailing EPS)
    eps = info.get('trailingEps', 0)
    if eps is None: eps = 0
    if eps > 5.0: score += 0.2
    elif eps > 0: score += 0.1
    elif eps < 0: score -= 0.2
    
    # 4. Analyst Consensus (1.0=Strong Buy, 5.0=Strong Sell)
    rec = info.get('recommendationMean')
    if rec is not None:
        if rec <= 2.0: score += 0.2  # Buy
        elif rec >= 3.0: score -= 0.2 # Sell
        
    # 5. Analyst Upside Potential
    target = info.get('targetMeanPrice')
    price = info.get('currentPrice')
    if target is not None and price is not None and price > 0:
        upside = (target / price) - 1.0
        if upside > 0.20: score += 0.3  # >20% undervalued
        elif upside > 0.10: score += 0.1
        elif upside < 0: score -= 0.3   # Overvalued
        
    # Normalize to roughly -1.0 to 1.0
    return max(-1.0, min(1.0, score))

def extract_fundamentals():
    print("=== EXTRACTING FUNDAMENTAL DATA ===")
    
    tickers = set()
    if os.path.exists(PORTFOLIO_PATH):
        active = pd.read_csv(PORTFOLIO_PATH)['Ticker'].tolist()
        tickers.update(active)
    else:
        # Fallback to a few standard tickers if file missing
        tickers.update(['AAPL', 'MSFT', 'NVDA', 'MU', 'TSLA'])
        
    print("Extracting ETF Whales to add to fundamental scan...")
    for etf in TARGET_ETFS:
        whales = get_60_percent_whales(etf)
        tickers.update(whales)
        
    tickers = list(tickers)
    print(f"Total unique companies to scan: {len(tickers)}")
        
    results = []
    
    for i, ticker in enumerate(tickers):
        print(f"[{i+1}/{len(tickers)}] Pulling institutional fundamentals for {ticker}...")
        try:
            t = yf.Ticker(ticker)
            info = t.info
            
            score = calculate_fundamental_score(info)
            
            results.append({
                'Ticker': ticker,
                'Profit_Margin': info.get('profitMargins', 0),
                'Debt_To_Equity': info.get('debtToEquity', 0),
                'Analyst_Rec': info.get('recommendationMean', 'N/A'),
                'Analyst_Target': info.get('targetMeanPrice', 'N/A'),
                'Fundamental_Score': score
            })
            # Sleep 2.0 seconds to prevent Yahoo Finance IP-Bans
            time.sleep(2.0)
        except Exception as e:
            print(f"  Error pulling {ticker}: {e}")
            results.append({
                'Ticker': ticker,
                'Fundamental_Score': 0.0 # Neutral prior if data fails
            })
            
    df = pd.DataFrame(results)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nSUCCESS: Fundamental Scores saved to {OUTPUT_PATH}")

if __name__ == '__main__':
    extract_fundamentals()
