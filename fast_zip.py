import os
import zipfile

def create_slim_zip(target_path, output_zip):
    exclude_dirs = {'.venv', 'venv', '.git', '__pycache__', '.pytest_cache', 'node_modules', 'scratch', 'vultr_sync.zip', 'vultr_slim.zip'}
    
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(target_path):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if file.endswith('.zip') or file.endswith('.csv'): 
                    # Optionally skip heavy CSVs if db has everything
                    pass
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, target_path)
                zipf.write(file_path, arcname)

create_slim_zip(r"C:\Users\AviShemla\AntiGravity", r"C:\Users\AviShemla\AntiGravity\vultr_slim.zip")
print("Slim zip created successfully.")
