import sys

print("Importing yfinance...")
sys.stdout.flush()
import yfinance as yf
print("yfinance done!")
sys.stdout.flush()

print("Importing pandas_market_calendars...")
sys.stdout.flush()
import pandas_market_calendars as mcal
print("pandas_market_calendars done!")
sys.stdout.flush()

print("Importing pytz...")
sys.stdout.flush()
import pytz
print("pytz done!")
sys.stdout.flush()
