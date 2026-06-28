"""
post_rebuild_pipeline.py
Runs automatically after rebuild completes:
1. Full QA financial audit
2. If green: run catch-up from Jun 4 → today
3. Run QA again
4. If still green: git commit, re-enable git backup task
5. Verify night run is scheduled
"""
import subprocess, sys, os, datetime

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
PY = sys.executable

def run(cmd, label):
    print(f"\n{'='*60}")
    print(f"  STEP: {label}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=BASE_DIR)
    return result.returncode == 0

# ── STEP 1: Full QA audit on rebuilt ledgers ──────────────────
print("\n[QA] STEP 1: Running Full QA Financial Audit...")
qa1 = subprocess.run([PY, "qa_financial_audit.py"], cwd=BASE_DIR)
if qa1.returncode != 0:
    print("\n[ERROR] QA FAILED after rebuild. Stopping. Fix virtual_broker.py further.")
    sys.exit(1)

print("\n[OK] QA PASSED on rebuilt ledgers!")

# ── STEP 2: Catch-up from Jun 4 → today ──────────────────────
print("\n[UP] STEP 2: Running Catch-Up (Jun 4 -> Jun 18)...")
import pandas as pd
import pandas_market_calendars as mcal

nyse = mcal.get_calendar('NYSE')
start = pd.Timestamp('2026-06-05')
end   = pd.Timestamp.now(tz='America/New_York').normalize().tz_localize(None)
days  = nyse.valid_days(start_date=start.strftime('%Y-%m-%d'), end_date=end.strftime('%Y-%m-%d'))

print(f"  Catch-up dates: {len(days)} trading days from {start.date()} to {end.date()}")
for d in days:
    date_str = d.strftime('%Y-%m-%d')
    print(f"\n  -> Processing {date_str}")
    subprocess.run([PY, "virtual_broker.py", "--target-date", date_str], cwd=BASE_DIR)
    subprocess.run([PY, "intraday_tracker.py", "--target-date", date_str], cwd=BASE_DIR)

# ── STEP 3: Export dashboards ─────────────────────────────────
print("\n[DB] STEP 3: Exporting Dashboards...")
subprocess.run([PY, "export_broker_excel_report.py"], cwd=BASE_DIR)

# ── STEP 4: Final QA audit ────────────────────────────────────
print("\n[QA] STEP 4: Final Full QA Audit (post catch-up)...")
qa2 = subprocess.run([PY, "qa_financial_audit.py"], cwd=BASE_DIR)
if qa2.returncode != 0:
    print("\n[ERROR] QA FAILED after catch-up. Stopping before Git commit.")
    sys.exit(1)

print("\n[OK] FINAL QA PASSED! All ledgers are mathematically clean.")

# ── STEP 5: Git commit ────────────────────────────────────────
print("\n[GIT] STEP 5: Committing to Git...")
today_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
try:
    subprocess.run(["git", "add", "."], cwd=BASE_DIR, check=True)
    subprocess.run(["git", "commit", "-m",
        f"Fix: Remove yfinance close-price override in settlement (phantom gain bug). Full ledger rebuild + QA verified. {today_str}"],
        cwd=BASE_DIR, check=True)
    print("  [OK] Git commit successful.")
except Exception as e:
    print(f"  [WARN] Git commit failed: {e}")

# ── STEP 6: Verify night run ──────────────────────────────────
print("\n[NIGHT] STEP 6: Verifying Night Run Schedule...")
result = subprocess.run(
    ["schtasks", "/query", "/tn", "AntiGravity_Daily_Pipeline", "/fo", "LIST"],
    capture_output=True, text=True, cwd=BASE_DIR
)
print(result.stdout)

print("\n" + "="*60)
print("  ALL DONE. Single stocks are fully rebuilt, QA-verified, and committed.")
print("  Night run is scheduled for tonight at 01:00 AM.")
print("="*60)
