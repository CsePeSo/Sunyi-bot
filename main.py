import ccxt
import pandas as pd
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volume import ChaikinMoneyFlowIndicator
import requests
import os
import time

# Exchange setup
exchange = ccxt.gateio({'enableRateLimit': True})
symbol = 'SOL/USDT'
check_interval = 5

# Telegram
def send_telegram_alert(message):
    token = os.getenv("TG_API_KEY")
    chat_id = os.getenv("TG_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Hiba az üzenetküldésnél: {e}")

# Tick alapú adat lekérés
def fetch_tick_data(limit=100):
    trades = exchange.fetch_trades(symbol, limit=limit)
    df = pd.DataFrame(trades)[['timestamp', 'price', 'amount']]
    df.rename(columns={'price': 'close', 'amount': 'volume'}, inplace=True)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# Indikátorok kiszámítása
def calculate_indicators(df):
    ema5 = EMAIndicator(close=df['close'], window=5).ema_indicator()
    ema10 = EMAIndicator(close=df['close'], window=10).ema_indicator()
    rsi = RSIIndicator(close=df['close'], window=14).rsi()
    cmf = ChaikinMoneyFlowIndicator(
        high=df['close'],
        low=df['close'],
        close=df['close'],
        volume=df['volume'],
        window=20
    ).chaikin_money_flow()
    return ema5, ema10, rsi, cmf

# Riasztási logika
last_alert_price = None

def check_alert(df, ema5, ema10, rsi, cmf):
    global last_alert_price
    if len(ema5) < 10 or len(rsi) < 10 or len(cmf) < 10:
        return False

    price = df['close'].iloc[-1]
    diff_ema = (ema5.iloc[-1] - ema10.iloc[-1]) / ema10.iloc[-1] * 100
    rsi_value = rsi.iloc[-1]
    cmf_value = cmf.iloc[-1]

    # Duplikált riasztás elkerülése
    if last_alert_price:
        price_diff = ((price - last_alert_price) / last_alert_price) * 100
        if price_diff < 0.2:
            return False

    # Riasztási feltételek (egyszerűsítve)
    if diff_ema > 0.05 and rsi_value > 58 and cmf_value > 0.05:
        message = (
            f"*Scalp LONG jelzés!*\n"
            f"Ár: {price:.2f} USDT\n"
            f"EMA diff: {diff_ema:.2f}%\n"
            f"RSI: {rsi_value:.2f}\n"
            f"CMF: {cmf_value:.4f}"
        )
        send_telegram_alert(message)
        last_alert_price = price
        return True

    return False

# Indítás
print("Bot aktiv.")
send_telegram_alert("Bot elindult és figyel!")

while True:
    try:
        df = fetch_tick_data()
        ema5, ema10, rsi, cmf = calculate_indicators(df)
        check_alert(df, ema5, ema10, rsi, cmf)
        time.sleep(check_interval)
    except Exception as e:
        print(f"Hiba történt: {e}")
        time.sleep(check_interval)
