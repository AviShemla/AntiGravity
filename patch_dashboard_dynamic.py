import re

def patch_dynamic(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # Dynamic replacement for plot_df
    content = re.sub(
        r'([ \t]+)plot_df = pd\.concat\(all_ledgers, axis=1\)\.sort_index\(\)\.ffill\(\)',
        r"\1plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()\n\1plot_df.index = pd.to_datetime(plot_df.index)\n\1plot_df = plot_df.reindex(pd.date_range(start=plot_df.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()",
        content
    )
    
    # Dynamic replacement for plot_df_e
    content = re.sub(
        r'([ \t]+)plot_df_e = pd\.concat\(all_ledgers_e, axis=1\)\.sort_index\(\)\.ffill\(\)',
        r"\1plot_df_e = pd.concat(all_ledgers_e, axis=1).sort_index().ffill()\n\1plot_df_e.index = pd.to_datetime(plot_df_e.index)\n\1plot_df_e = plot_df_e.reindex(pd.date_range(start=plot_df_e.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()",
        content
    )

    # For df_merged in Olympics:
    content = re.sub(
        r'([ \t]+)df_merged = df_merged\.ffill\(\)',
        r"\1df_merged = df_merged.ffill()\n\1df_merged.index = pd.to_datetime(df_merged.index)\n\1df_merged = df_merged.reindex(pd.date_range(start=df_merged.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()",
        content
    )

    # Apply the Plotly formatting override
    content = content.replace(
        "xaxis=dict(rangeslider=dict",
        "xaxis=dict(tickformat=\"%d/%m/%Y\", tickmode=\"linear\", dtick=86400000.0, tickangle=-45, rangeslider=dict"
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Patched {filename}")

patch_dynamic('dashboard.py')
patch_dynamic('dashboard_v1.py')
