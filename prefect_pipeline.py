import os
import subprocess
import sys
from prefect import flow, task
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
python_exe = sys.executable

@task(name="Catchup Master Pipeline", retries=2, retry_delay_seconds=60)
def run_master_pipeline():
    print("Running Master Pipeline Catchup...")
    result = subprocess.run([python_exe, "laptop_catchup_controller.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"Master Pipeline failed with code {result.returncode}")

@task(name="Catchup ETF Pipeline", retries=2, retry_delay_seconds=60)
def run_etf_pipeline():
    print("Running ETF Pipeline Catchup...")
    # ETF pipeline is handled inside laptop_catchup_controller in some setups, but we call the function explicitly if needed
    # Wait, the daily_pipeline.py calls both! Let's just run daily_pipeline.py!
    result = subprocess.run([python_exe, "daily_pipeline.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"Daily Pipeline failed with code {result.returncode}")

@task(name="Unified QA Manager Audit", retries=1)
def run_unified_qa():
    print("Running Unified QA Manager...")
    result = subprocess.run([python_exe, "qa_manager.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"QA Manager Audit Failed! Code {result.returncode}")

@flow(name="AntiGravity Nightly Protocol", log_prints=True)
def antigravity_nightly_flow():
    print("Starting AntiGravity Nightly Protocol via Prefect...")
    run_etf_pipeline()
    run_unified_qa()
    print("Nightly Protocol Complete!")

@flow(name="On-Demand System QA", log_prints=True)
def on_demand_qa_flow():
    print("Starting On-Demand System QA via Prefect...")
    run_unified_qa()
    print("QA Complete!")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "serve":
            antigravity_nightly_flow.serve(name="nightly-deployment", cron="0 18 * * *")
        elif sys.argv[1] == "qa":
            on_demand_qa_flow()
        else:
            print("Invalid argument. Use 'serve' or 'qa'.")
    else:
        antigravity_nightly_flow()
