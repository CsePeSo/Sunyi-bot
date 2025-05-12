
import ccxt
import pandas as pd
import time
import requests
from ta.trend import MACD
from ta.momentum import RSIIndicator
import logging
import os

# LOG fájl beállítás
logging.basicConfig(level=logging.INFO)

# TELEGRAM riasztás
def send_alert(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        logging.error(f"Telegram üzenetküldési hiba: {e}")

# Tőzsde kapcsolat
exchange = ccxt.gateio({
    'apiKey': os.getenv("GATEIO_API_KEY"),
    'secret': os.getenv("GATEIO_SECRET"),
    'enableRateLimit': True
})

symbol = 'SOL/USDT'
timeframe = '1m'

# Adatok lekérése
def fetch_data():
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=50)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

# Indikátorok kiszámítása
def compute_indicators(df):
    macd = MACD(close=df['close'])
    df['macd'] = macd.macd()
    df['signal'] = macd.macd_signal()
    df['rsi'] = RSIIndicator(close=df['close']).rsi()
    return df

# BULL jelzés logika
def is_bullish(df, last_price, last_volume):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    return (
        last_price > prev['close'] and
        latest['macd'] > latest['signal'] and
        latest['macd'] > 0 and
        latest['rsi'] > 65 and
        last_volume > latest['volume'] * 1.5
    )

# Fő ciklus
def run():
    cooldown = 0
    status_log_time = time.time() + 1800  # 30 percenként logol
    while True:
        try:
            df = fetch_data()
            df = compute_indicators(df)

            ticker = exchange.fetch_ticker(symbol)
            last_price = ticker['last']
            last_volume = ticker['quoteVolume']

            if time.time() > cooldown:
                if is_bullish(df, last_price, last_volume):
                    send_alert(f"BULL jelzés: {symbol} ár: {last_price} USDT")
                    cooldown = time.time() + 90  # 90 mp cooldown

            if time.time() > status_log_time:
                logging.info("Figyelés aktív, nincs jelzés.")
                status_log_time = time.time() + 1800

            time.sleep(3)

        except Exception as e:
            logging.error(f"Hiba történt: {e}")
            time.sleep(10)

if __name__ == '__main__':
    run()

Tudod mit csinálj most?

1. Töltsd fel ezt a fájlt GitHubra (pl. main.py).

