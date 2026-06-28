import plotly.graph_objects as go
import pandas as pd

fig = go.Figure()
fig.add_trace(go.Scatter(x=[1, 2, 3], y=[-10, 50, 145]))

y_min, y_max = -10, 145
y_pad = 31

fig.update_layout(
    yaxis=dict(fixedrange=True, range=[y_min - y_pad, y_max + y_pad], tickformat="$.2f"),
    xaxis=dict(rangeslider=dict(visible=True))
)

html = fig.to_html(full_html=False, include_plotlyjs=False)
if "autorange" in html:
    print("autorange is in html!")
if "fixedrange" in html:
    print("fixedrange is in html!")
if "-41" in html:
    print("-41 is in html!")
