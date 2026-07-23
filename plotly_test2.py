import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

dates = pd.date_range(start="2026-06-15", end="2026-07-22", freq='B')
y = np.random.randn(len(dates)).cumsum() + 10000

fig = go.Figure()
fig.add_trace(go.Scatter(x=dates, y=y, mode='lines'))
fig.update_layout(
    xaxis=dict(
        tickformat="%d/%m/%Y", 
        tickmode="linear", 
        dtick=86400000.0, 
        tickangle=-45, 
        rangeslider=dict(visible=True)
    )
)
fig.write_html("test_plot2.html")
print("Done")
