import os

def fix_indent(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
        
    content = content.replace(
        "                plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()\n                    plot_df = plot_df.reindex(",
        "                plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()\n                plot_df = plot_df.reindex("
    )
    content = content.replace(
        "                    plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()\n                    plot_df = plot_df.reindex(",
        "                    plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()\n                    plot_df = plot_df.reindex("
    )
    content = content.replace(
        "                plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()\n                    plot_df_e = plot_df_e.reindex(",
        "                plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()\n                plot_df_e = plot_df_e.reindex("
    )
    content = content.replace(
        "                    plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()\n                    plot_df_e = plot_df_e.reindex(",
        "                    plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()\n                    plot_df_e = plot_df_e.reindex("
    )
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

fix_indent('dashboard.py')
fix_indent('dashboard_v1.py')
print("Fixed")
