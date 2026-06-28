import subprocess, sys; etfs = ['XLK', 'XLV', 'XLY', 'XLF', 'XLC', 'XLI', 'XLE', 'XLP', 'XLU', 'XLRE', 'XLB']; [subprocess.run([sys.executable, 'build_etf_hybrid_matrix.py', etf]) for etf in etfs]
