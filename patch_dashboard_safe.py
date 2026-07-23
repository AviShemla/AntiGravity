import os

def patch_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Fix the missing dates by reindexing to today
    content = content.replace(
        "plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()",
        "plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()\n                    plot_df = plot_df.reindex(pd.date_range(start=plot_df.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()"
    )
    content = content.replace(
        "plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()",
        "plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()\n                    plot_df_e = plot_df_e.reindex(pd.date_range(start=plot_df_e.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()"
    )

    # 2. Fix the Plotly formatting
    # Replace xaxis=dict(rangeslider=... with xaxis=dict(tickformat="%d/%m/%Y", tickmode="linear", dtick=86400000.0, tickangle=-45, rangeslider=...
    content = content.replace(
        "xaxis=dict(rangeslider=dict",
        "xaxis=dict(tickformat=\"%d/%m/%Y\", tickmode=\"linear\", dtick=86400000.0, tickangle=-45, rangeslider=dict"
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Patched {filename}")

if __name__ == "__main__":
    patch_file('dashboard.py')
    patch_file('dashboard_v1.py')
