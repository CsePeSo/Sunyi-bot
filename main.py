import requests
import pandas as pd
import os
import logging

# --- Logging beállítások ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- Környezeti változók ---
TOKEN = os.getenv("TG_API_KEY")
CHAT_ID = os.getenv("TG_CHAT_ID")
GATE_API_KEY = os.getenv("GATEI_KEY")
GATE_SECRET_KEY = os.getenv("GATEI_SECRET")

# --- Telegram üzenet küldése ---
def send_telegram_message(message):
    if not TOKEN or not CHAT_ID:
        logging.warning("Hiányzó Telegram beállítások!")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    try:
        r = requests.post(url, data=data)
        r.raise_for_status()
    except Exception as e:
        logging.error(f"Telegram hiba: {e}")

# --- Coinpárok ---
PAIRS = ["PI_USDT", "SOL_USDT", "XRP_USDT", "PEPE_USDT", "TRUMP_USDT"]

# --- Üdvözlő üzenet ---
send_telegram_message("🤖 A több coin figyelő bot elindult! (TG_API_KEY / TG_CHAT_ID)")

# --- Adatok lekérése ---
def fetch_data(pair):
    url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&limit=30&interval=1h"
    headers = {"KEY": GATE_API_KEY, "SECRET": GATE_SECRET_KEY}
    try:
        r = requests.get(url, headers=headers)
        data = r.json()
        columns = ["timestamp", "volume", "open", "high", "low", "close", "not_used", "complete"]
        df = pd.DataFrame(data, columns=columns)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception as e:
        logging.error(f"{pair} lekérés hiba: {e}")
        return None

# --- RSI számítása ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- Score számítás ---
def calculate_score(df):
    score = 0
    
    # 🚀 EMA trend megerősítés
    if df["EMA12"].iloc[-1] > df["EMA26"].iloc[-1] and df["EMA26"].iloc[-1] > df["EMA26"].iloc[-2]:
        score += 1  

    # 🚀 MACD keresztvizsgálat
    if df["MACD"].iloc[-1] > df["Signal"].iloc[-1] and df["MACD"].iloc[-2] < df["Signal"].iloc[-2]:
        score += 1  

    # 🚀 RSI szűrés
    if df["RSI"].iloc[-1] > 60:
        score += 1  

    # 🚀 EMA50 távolságszűrés
    current_price = df["close"].iloc[-1]
    ema50 = df["EMA50"].iloc[-1]
    distance_pct = abs((current_price - ema50) / ema50) * 100

    if current_price > ema50 and 2 <= distance_pct <= 3:
        score += 1  

    # 🚀 Volumen megerősítés
    inflow = (df["close"].iloc[-1] - df["open"].iloc[-1]) * df["volume"].iloc[-1]
    avg_inflow = ((df["close"] - df["open"]) * df["volume"]).iloc[-6:-1].mean()
    if inflow > avg_inflow:
        score += 1  

    return round(score, 2)

# --- Coinok értékelése ---
report = []
for pair in PAIRS:
    df = fetch_data(pair)
    if df is not None and len(df) >= 26:
        df["EMA12"] = df["close"].ewm(span=12, adjust=False).mean()
        df["EMA26"] = df["close"].ewm(span=26, adjust=False).mean()
        df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["MACD"] = df["EMA12"] - df["EMA26"]
        df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["RSI"] = calculate_rsi(df["close"])
        
        s = calculate_score(df)
        if s >= 3.5:  # csak erősebb jelzéseket küld
            report.append((pair, s))

# --- Jelentés ---
if report:
    ranked = sorted(report, key=lambda x: x[1], reverse=True)
    message = "📈 *Bullish score alapján erős coinok:*\n"
    for pair, sc in ranked:
        message += f"• `{pair}` — score: {sc}\n"
    send_telegram_message(message)
```
