import requests
import pandas as pd
import os
import time
import logging

# --- Beállítások ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- Környezeti változók ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- Figyelni kívánt párok ---
TRADING_PAIRS = ["PI_USDT", "SOL_USDT", "XRP_USDT", "PEPE_USDT", "TRUMP_USDT"]

# --- Telegram üzenetküldés ---
def send_telegram_message(message):
    if not TOKEN or not CHAT_ID:
        logging.warning("Hiányzó Telegram beállítások.")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    try:
        r = requests.post(url, data=data)
        r.raise_for_status()
        logging.info("Telegram üzenet elküldve.")
    except Exception as e:
        logging.error(f"Telegram hiba: {e}")

# --- RSI számítás ---
def calculate_rsi(data, period=14):
    delta = data.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- Egy coin adatainak elemzése ---
def analyze_pair(symbol):
    url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={symbol}&limit=100&interval=1h"
    try:
        response = requests.get(url)
        data = response.json()

        columns = ["timestamp", "quote_volume", "open", "high", "low", "close", "trade_count", "completed"]
        df = pd.DataFrame(data, columns=columns)
        df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="s")
        for col in ["open", "high", "low", "close", "quote_volume"]:
            df[col] = df[col].astype(float)

        df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = df['EMA12'] - df['EMA26']
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['RSI'] = calculate_rsi(df['close'])

        buy = (df['EMA12'].iloc[-1] > df['EMA26'].iloc[-1]) and \
              (df['RSI'].iloc[-1] > 50) and \
              (df['MACD'].iloc[-1] > df['Signal'].iloc[-1])

        sell = (df['EMA12'].iloc[-1] < df['EMA26'].iloc[-1]) and \
               (df['RSI'].iloc[-1] < 50) and \
               (df['MACD'].iloc[-1] < df['Signal'].iloc[-1])

        if buy:
            send_telegram_message(f"🚀 Vételi jelzés a következő párra: {symbol}")
        elif sell:
            send_telegram_message(f"🔻 Eladási jelzés a következő párra: {symbol}")

    except Exception as e:
        logging.error(f"Hiba a(z) {symbol} párnál: {e}")

# --- Indítási üzenet ---
send_telegram_message("🤖 Több coin figyelés elindult! A bot aktív Renderen.")

# --- Fő ciklus ---
while True:
    for pair in TRADING_PAIRS:
        analyze_pair(pair)
        time.sleep(2)  # API limit védelme

    time.sleep(60)  # Újraellenőrzés 1 percenként

