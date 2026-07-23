import os

def fix_all(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for i in range(len(lines)):
        if "plot_df.reindex(pd.date_range" in lines[i] or "plot_df_e.reindex(pd.date_range" in lines[i]:
            # Look at previous line's indentation
            prev_line = lines[i-1]
            indent = prev_line[:len(prev_line) - len(prev_line.lstrip())]
            lines[i] = indent + lines[i].lstrip()
            
    with open(filename, 'w', encoding='utf-8') as f:
        f.writelines(lines)

fix_all('dashboard.py')
fix_all('dashboard_v1.py')
