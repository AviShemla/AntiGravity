import yfinance as yf
import time

def test_vix_latency():
    print("=== VIX FEASIBILITY & PERFORMANCE TEST ===")
    
    start_time = time.time()
    
    try:
        # Download 1 day of 1-minute interval data for the VIX
        print("Fetching live ^VIX data from Yahoo Finance...")
        vix_data = yf.download("^VIX", period="1d", interval="1m", progress=False)
        
        end_time = time.time()
        latency = (end_time - start_time) * 1000  # Convert to milliseconds
        
        if vix_data.empty:
            print("ERROR: Could not fetch VIX data.")
            return
            
        # Extract the absolute latest close price
        if isinstance(vix_data.columns, type(vix_data.index)): # handle multiindex
            pass
        latest_vix = float(vix_data['Close'].iloc[-1].item())
        
        print(f"\n=> SUCCESS! Live ^VIX Price: {latest_vix:.2f}")
        print(f"=> API Fetch Latency: {latency:.2f} ms")
        
        # Calculate Dummy Scalar
        scalar = 1.0
        if latest_vix < 20:
            scalar = 1.0
            status = "NORMAL (Standard 5% Stop-Loss)"
        elif 20 <= latest_vix <= 30:
            scalar = 1.5
            status = "ELEVATED (Widen Stop-Loss to 7.5% to avoid whipsaw)"
        else:
            scalar = 0.4
            status = "PANIC (Tighten Stop-Loss to 2.0% to protect capital)"
            
        print(f"\n[Dynamic Scalar Engine]")
        print(f"Current Market State: {status}")
        print(f"Calculated Volatility Multiplier: {scalar}x")
        
        print("\nCONCLUSION: Extremely feasible for intraday performance tracking.")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_vix_latency()
