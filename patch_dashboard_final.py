import os

def patch_final(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # Apply the ffill logic with pd.to_datetime for plot_df
    # We replace the original sort_index().ffill() line.
    content = content.replace(
        "plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()",
        "plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()\n                plot_df.index = pd.to_datetime(plot_df.index)\n                plot_df = plot_df.reindex(pd.date_range(start=plot_df.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()"
    )
    
    # Same for plot_df_e
    content = content.replace(
        "plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()",
        "plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()\n                plot_df_e.index = pd.to_datetime(plot_df_e.index)\n                plot_df_e = plot_df_e.reindex(pd.date_range(start=plot_df_e.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()"
    )

    # For df_merged in Olympics:
    content = content.replace(
        "df_merged = df_merged.ffill()",
        "df_merged = df_merged.ffill()\n        df_merged.index = pd.to_datetime(df_merged.index)\n        df_merged = df_merged.reindex(pd.date_range(start=df_merged.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()"
    )

    # Apply the Plotly formatting override
    content = content.replace(
        "xaxis=dict(rangeslider=dict",
        "xaxis=dict(tickformat=\"%d/%m/%Y\", tickmode=\"linear\", dtick=86400000.0, tickangle=-45, rangeslider=dict"
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Patched {filename}")

patch_final('dashboard.py')
patch_final('dashboard_v1.py')
