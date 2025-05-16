import os
import requests
import pandas as pd
from datetime import datetime

# Gate.io API végpont (candlestick adatok)
GATE_IO_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"

# Paraméterek
symbol = "PI_USDT"       # Coin pair
interval = "900"         # 15 perces gyertyák (900 másodperc)
limit = 1000              # Max lekérhető gyertyaszám

params = {
    "currency_pair": symbol,
    "interval": interval,
    "limit": limit
}

# Lekérés
response = requests.get(GATE_IO_URL, params=params)
data = response.json()

# Átalakítás DataFrame-é
columns = ["timestamp", "volume", "close", "high", "low", "open"]
df = pd.DataFrame(data, columns=columns)

# Időbélyeg átalakítása olvasható formára
df["timestamp"] = pd.to_datetime(df["timestamp"], unit='s')

# Oszlopok új sorrendben: timestamp, open, high, low, close, volume
df = df[["timestamp", "open", "high", "low", "close", "volume"]]

# CSV fájl mentése
csv_file = "pi_15m_ohlcv.csv"
df.to_csv(csv_file, index=False)

print(f"Lekérdezés kész. CSV fájl elmentve: {csv_file}")
