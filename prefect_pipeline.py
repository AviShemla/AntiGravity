import os
import subprocess
import sys
from prefect import flow, task

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
python_exe = sys.executable

@task(name="Run Preflight Checks", retries=0)
def run_preflight():
    print("Running Pre-Flight Checks...")
    result = subprocess.run([python_exe, "preflight_check.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"Preflight checks failed with code {result.returncode}")

@task(name="Master Pipeline (Stocks)", retries=2, retry_delay_seconds=60)
def run_master_pipeline():
    print("Running Master Pipeline...")
    result = subprocess.run([python_exe, "master_pipeline.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"Master Pipeline failed with code {result.returncode}")

@task(name="Daily Pipeline (ETFs & Extra)", retries=2, retry_delay_seconds=60)
def run_daily_pipeline():
    print("Running Daily Pipeline...")
    result = subprocess.run([python_exe, "daily_pipeline.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"Daily Pipeline failed with code {result.returncode}")

@task(name="Unified QA Manager Audit", retries=1)
def run_unified_qa():
    print("Running Unified QA Manager...")
    result = subprocess.run([python_exe, "qa_manager.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"QA Manager Audit Failed! Code {result.returncode}")

@task(name="Run Weekend Stock Trainer", retries=1)
def run_weekend_stock():
    print("Running Weekend Stock DL Trainer...")
    result = subprocess.run([python_exe, "weekend_dl_trainer.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"Weekend Stock Trainer failed with code {result.returncode}")

@task(name="Run Weekend ETF Trainer", retries=1)
def run_weekend_etf():
    print("Running Weekend ETF DL Trainer...")
    result = subprocess.run([python_exe, "etf_weekend_dl_trainer.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"Weekend ETF Trainer failed with code {result.returncode}")

@flow(name="AntiGravity Nightly Protocol", log_prints=True)
def antigravity_nightly_flow():
    print("Starting AntiGravity Nightly Protocol via Prefect...")
    run_preflight()
    run_master_pipeline()
    run_daily_pipeline()
    run_unified_qa()
    print("Nightly Protocol Complete!")

@flow(name="AntiGravity Weekend Protocol", log_prints=True)
def antigravity_weekend_flow():
    print("Starting AntiGravity Weekend Protocol via Prefect...")
    run_weekend_stock()
    run_weekend_etf()
    print("Weekend Protocol Complete!")

@flow(name="On-Demand System QA", log_prints=True)
def on_demand_qa_flow():
    print("Starting On-Demand System QA via Prefect...")
    run_preflight()
    run_unified_qa()
    print("QA Complete!")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "serve":
            # Schedule the nightly flow every day at 1:00 AM
            antigravity_nightly_flow.serve(name="nightly-deployment", cron="0 1 * * *")
            # Schedule weekend flow every Saturday at 14:00
            antigravity_weekend_flow.serve(name="weekend-deployment", cron="0 14 * * 6")
        elif sys.argv[1] == "qa":
            on_demand_qa_flow()
        else:
            print("Invalid argument. Use 'serve' or 'qa'.")
    else:
        antigravity_nightly_flow()
