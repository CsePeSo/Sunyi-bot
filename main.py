
import requests
import pandas as pd
import os
import logging

# --- Alap beállítások ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- API kulcsok ---
TOKEN = os.getenv("TG_API_KEY")
CHAT_ID = os.getenv("TG_CHAT_ID")
GATE_API_KEY = os.getenv("GATE_API_KEY")
GATE_SECRET_KEY = os.getenv("GATE_SECRET_KEY")

# --- Telegram értesítés ---
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
        logging.warning(f"Telegram hiba: {e}")

send_telegram_message("🤖 A több coin figyelő bot elindult!\n(TG_API_KEY / TG_CHAT_ID)")

# --- Pénzmozgás becslése ---
def compute_inflow_strength(df):
    return (df["close"] - df["open"]) * df["volume"]

# --- Bullish score számítás ---
def calculate_score(df):
    score = 0
    if df["ema12"].iloc[-1] > df["ema26"].iloc[-1]:
        score += 1
    if df["macd"].iloc[-1] > df["macd_signal"].iloc[-1]:
        score += 1
    if df["rsi"].iloc[-1] > 55:
        score += 1
    if df["close"].iloc[-1] > df["close"].iloc[-2]:
        score += 0.5
    if df["ema26"].iloc[-1] > df["ema26"].iloc[-2]:
        score += 0.5
    inflow = compute_inflow_strength(df.iloc[-1])
    avg_inflow = compute_inflow_strength(df.iloc[-6:-1]).mean()
    if inflow > avg_inflow:
        score += 1
    return score

# --- RSI számítás ---
def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# --- MACD számítás ---
def calculate_macd(close):
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    return macd, signal, ema12, ema26

# --- Coin lista ---
COINS = ["PI_USDT", "SOL_USDT", "XRP_USDT", "PEPE_USDT", "TRUMP_USDT"]

# --- Gate API lekérdezés (30 perces timeframe) ---
def fetch_candles(coin):
    url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}&limit=100&interval=30m"
    try:
        response = requests.get(url)
        data = response.json()
        df = pd.DataFrame(data, columns=["timestamp", "volume", "close", "high", "low", "open", "unused1", "unused2"])
        df = df[["timestamp", "volume", "close", "high", "low", "open"]]
        df = df.astype(float)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df.sort_values("timestamp", inplace=True)

        df["ema12"] = df["close"].ewm(span=12).mean()
        df["ema26"] = df["close"].ewm(span=26).mean()
        df["macd"], df["macd_signal"], _, _ = calculate_macd(df["close"])
        df["rsi"] = calculate_rsi(df["close"])
        return df
    except Exception as e:
        logging.error(f"Hiba a {coin} lekérdezésnél: {e}")
        return None

# --- Pullback + megerősítő logika ---
def detect_pullback_recovery(df):
    if len(df) < 3:
        return False
    prev2 = df.iloc[-3]
    prev1 = df.iloc[-2]
    current = df.iloc[-1]

    pullback = prev1["close"] < prev1["open"] and ((prev1["open"] - prev1["close"]) / prev1["open"] > 0.003)
    recovery = current["close"] > current["open"] and current["close"] > prev1["close"]
    prev_trend = prev2["close"] > prev2["open"]

    return pullback and recovery and prev_trend

# --- Visszatesztelő és értesítő logika ---
last_alert_price = {}

# --- Main loop ---
for coin in COINS:
    df = fetch_candles(coin)
    if df is None or len(df) < 30:
        continue

    score = calculate_score(df)

    if detect_pullback_recovery(df):
        send_telegram_message(f"📈 *Pullback utáni megerősítés* a következő párra:\n`{coin}`")
        last_alert_price[coin] = df["close"].iloc[-1]
    elif score >= 4:
        send_telegram_message(f"📈 *Vételi jelzés* a következő párra:\n`{coin}`\nBullish score: {score}/6")
        last_alert_price[coin] = df["close"].iloc[-1]
