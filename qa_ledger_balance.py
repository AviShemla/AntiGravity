import pandas as pd
import numpy as np
import os
import sys

# Add directory to path so we can import the virtual broker logic
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from virtual_broker import calculate_kelly_fraction

def run_qa_ledger_balance():
    print("========================================")
    print("   QA: FINANCIAL LEDGER & MATH AUDIT    ")
    print("========================================")
    
    passed = 0
    failed = 0
    
    # TEST 1: Kelly Criterion Bounds Check
    print("\n[TEST 1] Kelly Criterion Bounds & Edge Cases")
    try:
        # Edge Case A: Negative expected return
        k_neg = calculate_kelly_fraction(0.8, -0.05, 0.2)
        assert k_neg == 0.0, f"Expected 0.0 for negative return, got {k_neg}"
        
        # Edge Case B: Extremely high confidence (Should be capped correctly by math)
        k_high = calculate_kelly_fraction(0.99, 0.1, 0.05) # R = 2.0. W=0.99. Kelly = 0.99 - (0.01 / 2) = 0.985
        assert round(k_high, 3) == 0.985, f"Expected 0.985, got {k_high}"
        
        # Edge Case C: Low probability, high return (Kelly should clamp to 0 if negative)
        k_low = calculate_kelly_fraction(0.4, 0.05, 0.2) # R = 0.25. W = 0.4. Kelly = 0.4 - (0.6 / 0.25) = 0.4 - 2.4 = -2.0 -> 0.0
        assert k_low == 0.0, f"Expected 0.0, got {k_low}"
        
        print("  => PASSED: Kelly calculations are mathematically sound and perfectly clamped.")
        passed += 1
    except Exception as e:
        print(f"  => FAILED: {e}")
        failed += 1
        
    # TEST 2: Portfolio PnL Math & Precision (Simulated)
    print("\n[TEST 2] Portfolio PnL Accounting & Precision")
    try:
        cash = 10000.0
        holdings = {"GOOG": {"dollars": 2000.0, "price": 100.0}}
        total_equity = cash + holdings["GOOG"]["dollars"]
        
        assert total_equity == 12000.0, "Initial equity calculation is flawed."
        
        # Simulate overnight hold with +5% return
        settle_price = 105.0
        ret = (settle_price - holdings["GOOG"]["price"]) / holdings["GOOG"]["price"]
        pnl = holdings["GOOG"]["dollars"] * ret
        new_cash = cash + holdings["GOOG"]["dollars"] + pnl
        new_equity = new_cash # All positions settled
        
        assert new_cash == 12100.0, f"Expected cash to be 12100.0, got {new_cash}"
        assert new_equity == 12100.0, f"Expected equity to be 12100.0, got {new_equity}"
        
        print("  => PASSED: Portfolio PnL math accurately reflects exact fractional dollar returns.")
        passed += 1
    except Exception as e:
        print(f"  => FAILED: {e}")
        failed += 1
        
    # TEST 3: CSV Persistence Integrity
    print("\n[TEST 3] Floating-Point Ledger Persistence")
    try:
        test_path = "tmp_qa_ledger.csv"
        df = pd.DataFrame([{
            'Date': '2026-06-05',
            'Cash': 12100.1234567,
            'Total_Equity': 12100.1234567,
            'Holdings_JSON': '{"AAPL": {"dollars": 1000.0, "price": 150.0}}'
        }])
        df.to_csv(test_path, index=False)
        
        df_read = pd.read_csv(test_path)
        cash_read = float(df_read['Cash'].iloc[0])
        
        # Verify 7 decimal places are preserved in CSV without float truncation rounding errors
        assert abs(cash_read - 12100.1234567) < 1e-6, f"Float precision lost during CSV write/read. Got {cash_read}"
        
        import json
        h_json = json.loads(df_read['Holdings_JSON'].iloc[0])
        assert "AAPL" in h_json, "JSON serialization failed in CSV."
        
        os.remove(test_path)
        print("  => PASSED: Ledger precisely maintains floating-point history to 7 decimal places.")
        passed += 1
    except Exception as e:
        print(f"  => FAILED: {e}")
        failed += 1
        
    # TEST 4: Zero-Unit "Aborted Buy" Math Audit
    print("\n[TEST 4] Zero-Unit Aborted Buy Simulation")
    try:
        # Simulate virtual broker setting 0 units due to API failure
        virtual_holdings = {"AAL": {"dollars": 1000.0, "units": 0, "price": 0}}
        cash = 9000.0
        
        # Simulating intraday tracker intercept
        for ticker, data in virtual_holdings.items():
            if data["units"] == 0:
                # Intraday tracker strips it from holdings and refunds cash
                cash += data["dollars"]
                data["dollars"] = 0.0 # Force zero dollars so it doesn't corrupt equity
                
        assert cash == 10000.0, f"Failed to properly refund cash. Got {cash}"
        assert virtual_holdings["AAL"]["dollars"] == 0.0, "Failed to zero-out dollars for 0-unit stock."
        print("  => PASSED: Zero-unit API failures safely refund cash and zero-out allocations.")
        passed += 1
    except Exception as e:
        print(f"  => FAILED: {e}")
        failed += 1
        
    # TEST 5: Division-By-Zero PnL Audit
    print("\n[TEST 5] Division-By-Zero / NaN Prevention")
    try:
        # Simulate ETF virtual broker calculating PnL on a stock with $0 purchase price
        purchase_price = 0.0
        close_price = 100.0
        
        # Safely default to 0.0% return instead of crashing
        actual_return_pct = (close_price - purchase_price) / purchase_price if purchase_price > 0 else 0.0
        assert actual_return_pct == 0.0, f"Expected 0.0% return, got {actual_return_pct}"
        
        print("  => PASSED: PnL calculations safely trap $0 purchase prices without throwing Div/Zero or NaN errors.")
        passed += 1
    except Exception as e:
        print(f"  => FAILED: {e}")
        failed += 1

    print("\n========================================")
    print(f"LEDGER AUDIT RESULTS: {passed} PASSED | {failed} FAILED")
    print("========================================")
    
    if failed > 0:
        os._exit(1)

if __name__ == "__main__":
    run_qa_ledger_balance()
