import os, glob, re

count = 0
for filepath in glob.glob('*.py'):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(filepath, 'r', encoding='utf-16') as f:
                content = f.read()
        except:
            continue

    if 'os._exit(' in content and 'import sys' in content:
        if 'import os' not in content:
            content = 'import os\n' + content
        new_content = re.sub(r'\bsys\.exit\(', 'os._exit(', content)
        if new_content != content:
            # write back with original encoding
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
            except:
                with open(filepath, 'w', encoding='utf-16') as f:
                    f.write(new_content)
            count += 1
print(f'Patched {count} files globally.')
