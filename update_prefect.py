import os

with open("prefect_pipeline.py", "r") as f:
    content = f.read()

# We need to add the missing flows
missing_tasks = """
@task(name="Run Git Backup", retries=1)
def run_git_backup():
    print("Running Git Backup...")
    result = subprocess.run(["git", "add", "."], cwd=BASE_DIR, shell=True)
    subprocess.run(["git", "commit", "-m", "Automated Backup"], cwd=BASE_DIR, shell=True)
    subprocess.run(["git", "push"], cwd=BASE_DIR, shell=True)

@task(name="Run Daily Migration", retries=1)
def run_daily_migration():
    print("Running Daily Migration...")
    result = subprocess.run([python_exe, "execute_daily_migration.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"Daily Migration failed with code {result.returncode}")

@task(name="Run API Health Check", retries=0)
def run_api_health():
    print("Running API Health Check...")
    result = subprocess.run([python_exe, "qa_api_health.py"], cwd=BASE_DIR)

@task(name="Run Clean Ghosts", retries=0)
def run_clean_ghosts():
    print("Running Clean Ghosts...")
    result = subprocess.run([python_exe, "clean_ghosts.py"], cwd=BASE_DIR)

@flow(name="AntiGravity Git Backup", log_prints=True)
def antigravity_git_backup_flow():
    run_git_backup()

@flow(name="AntiGravity Daily Migration", log_prints=True)
def antigravity_daily_migration_flow():
    run_daily_migration()

@flow(name="AntiGravity API Health QA", log_prints=True)
def antigravity_api_health_flow():
    run_api_health()

@flow(name="AntiGravity Maintenance", log_prints=True)
def antigravity_maintenance_flow():
    run_unified_qa()
    run_clean_ghosts()
"""

# Insert missing tasks before the if __name__ == "__main__": block
content = content.replace('if __name__ == "__main__":', missing_tasks + '\nif __name__ == "__main__":')

# Update the serve block
serve_block = """        if sys.argv[1] == "serve":
            # Deploy all flows
            antigravity_nightly_flow.serve(name="nightly-pipeline", cron="0 1 * * *")
            antigravity_weekend_flow.serve(name="weekend-trainers", cron="0 14 * * 6")
            antigravity_git_backup_flow.serve(name="git-backup", cron="0 5 * * *")
            antigravity_daily_migration_flow.serve(name="daily-migration", cron="30 23 * * *")
            antigravity_api_health_flow.serve(name="api-health", cron="*/15 * * * *")
            antigravity_maintenance_flow.serve(name="maintenance-qa", cron="0 * * * *")"""

import re
content = re.sub(r'        if sys.argv\[1\] == "serve":.*?(?=        elif sys.argv\[1\] == "qa":)', serve_block + '\n', content, flags=re.DOTALL)

with open("prefect_pipeline.py", "w") as f:
    f.write(content)
print("prefect_pipeline.py updated successfully.")
