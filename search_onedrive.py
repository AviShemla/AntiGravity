import os

base_dir = os.path.dirname(os.path.abspath(__file__))
search_str = "OneDrive"

def search_files(directory):
    found_files = []
    for root, dirs, files in os.walk(directory):
        if '.git' in dirs:
            dirs.remove('.git')
        if '__pycache__' in dirs:
            dirs.remove('__pycache__')
        for file in files:
            file_path = os.path.join(root, file)
            # Skip binary and certain files
            if file.endswith(('.png', '.jpg', '.jpeg', '.xlsx', '.sqlite3', '.code-workspace', '.html')):
                continue
            if 'fix_task.py' in file:
                continue
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if search_str.lower() in content.lower():
                        found_files.append(file_path)
            except Exception:
                pass
    return found_files

results = search_files(base_dir)
print("Files containing OneDrive:")
for f in results:
    print(f)
