"""
run_etf_hybrid_screener.py
--------------------------
Thin wrapper called by laptop_catchup_controller.py.
Delegates to etf_fast_screener.screen_hybrid_matrix(target_etf).

Usage: py run_etf_hybrid_screener.py XLK
"""
import sys
from etf_fast_screener import screen_hybrid_matrix

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'XLK'
    screen_hybrid_matrix(target)
