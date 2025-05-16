import os
import requests
import pandas as pd
from datetime import datetime

# Gate.io API endpoint for Klines
GATE_IO_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"

# Parameters
symbol = "PI_USDT"  # Use Gate.io format with underscore
interval = "900"     # 900 = 15m candles
limit = 1000          # Max allowed by Gate.io, ~10 nap 10 óra

params = {
    "currency_pair": symbol,
    "interval": interval,
    "limit": limit
}

response = requests.get(GATE_IO_URL, params=params)
data = response.json()

# Convert to DataFrame
df = pd.DataFrame(data, columns=[
    "timestamp", "volume", "close", "high", "low", "open"])

# Convert timestamp to readable format
df["timestamp"] = pd.to_datetime(df["timestamp"], unit='s')

# Reorder columns
df = df[["timestamp", "open", "high", "low", "close", "volume"]]

# Save as CSV
output_file = "pi_15m_ohlcv.csv"
df.to_csv(output_file, index=False)
print(f"CSV exported: {output_file}")
