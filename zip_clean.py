import os
import zipfile

def create_clean_backup():
    source_dir = r"C:\Users\AviShemla\AntiGravity"
    backup_path = r"C:\Users\AviShemla\AG_BCK\AntiGravity_Clean_Backup_July26.zip"
    
    exclude_dirs = {'.git', '.venv', '__pycache__', 'scratch', 'OLD_code', '.vscode'}
    exclude_exts = {'.zip', '.lock'}
    
    print(f"Creating clean backup at {backup_path}...")
    
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            # Mutate dirs in place to exclude unwanted directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                # Exclude unwanted extensions
                if any(file.endswith(ext) for ext in exclude_exts):
                    continue
                    
                file_path = os.path.join(root, file)
                # Calculate the relative path to maintain structure inside the zip
                arcname = os.path.relpath(file_path, start=source_dir)
                zipf.write(file_path, arcname)
                
    # Get the final size
    size_mb = os.path.getsize(backup_path) / (1024 * 1024)
    print(f"Backup created successfully! Size: {size_mb:.2f} MB")

if __name__ == '__main__':
    create_clean_backup()
