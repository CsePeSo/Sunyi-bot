
import os
import requests
import pandas as pd
from datetime import datetime
from flask import Flask, send_file

app = Flask(__name__)

# Gate.io API végpont (candlestick adatok)
GATE_IO_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"

# Paraméterek
symbol = "PI_USDT"
interval = "900"         # 15 perces gyertyák
limit = 1000             # Max lekérhető gyertyaszám

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

# Oszlopok sorrendje: timestamp, open, high, low, close, volume
df = df[["timestamp", "open", "high", "low", "close", "volume"]]

# CSV mentés
csv_file = "pi_15m_ohlcv.csv"
df.to_csv(csv_file, index=False)
print(f"Lekérdezés kész. CSV fájl elmentve: {csv_file}")

# Letöltés végpont
@app.route("/")
def home():
    return "CSV letöltő aktív – menj a /download végpontra."

@app.route("/download")
def download():
    return send_file(csv_file, as_attachment=True)

# Indítás
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

