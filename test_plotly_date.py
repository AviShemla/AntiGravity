import pandas as pd
import numpy as np
import plotly.graph_objects as go

dates = pd.date_range(start="2026-06-15", end="2026-07-22")
y = np.random.randn(len(dates)).cumsum() + 10000

fig = go.Figure()
fig.add_trace(go.Scatter(x=dates, y=y, mode='lines'))
fig.update_layout(
    xaxis=dict(
        rangeslider=dict(visible=True),
        tickformat="%d/%m/%Y"
    )
)
fig.write_html("test_plot.html")
print("Done")
