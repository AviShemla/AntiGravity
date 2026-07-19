import zipfile
import os

source_dir = os.path.dirname(os.path.abspath(__file__))
zip_path = r"C:\Users\AviShemla\AG_BCK\AntiGravity_Full_Migration_Backup.zip"

print("Starting robust migration zip protocol...")

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(source_dir):
        # Skip permission-denied cache folders
        if '.pytest_cache' in dirs:
            dirs.remove('.pytest_cache')
        if '__pycache__' in dirs:
            dirs.remove('__pycache__')
            
        for file in files:
            file_path = os.path.join(root, file)
            # Exclude the zip script itself and any other locks
            if "zip_migration.py" in file_path:
                continue
            
            try:
                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)
            except Exception as e:
                print(f"Skipped {file_path}: {e}")

print(f"Migration backup successfully generated at {zip_path}")
