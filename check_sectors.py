import pandas as pd
import io, requests

html = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers={'User-Agent': 'Mozilla/5.0'}).text
sp500_df = pd.read_html(io.StringIO(html))[0]
print(sp500_df['GICS Sector'].unique())
print(len(sp500_df['GICS Sector'].unique()))
