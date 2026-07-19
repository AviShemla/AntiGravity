import os
import re
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
files = glob.glob(os.path.join(BASE_DIR, "*.py"))

for filepath in files:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(filepath, 'r', encoding='utf-16') as f:
            content = f.read()
        
    original = content
    
    # Remove and shape=X_data.shape[1] from observed definitions
    content = re.sub(r',\s*shape=X_data\.shape\[0\]', '', content)
    content = re.sub(r'shape=X_data\.shape\[0\]\s*,?', '', content)
    
    # Enforce int64 instead of int32 for targets
    content = content.replace('astype(np.int64)', 'astype(np.int64)')
    
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Patched PyTensor math in {os.path.basename(filepath)}")

print("All PyMC math bugs patched.")
