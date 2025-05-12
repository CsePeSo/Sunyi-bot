
import ccxt
import pandas as pd
from ta.trend import EMAIndicator, MACD
from ta.volume import OnBalanceVolumeIndicator
from ta.momentum import RSIIndicator
import requests
import time
import os

# Telegram beállítások
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=data)

exchange = ccxt.gateio({'enableRateLimit': True})
symbol = 'SOL/USDT'
check_interval = 5

def fetch_tick_data(limit=100):
    trades = exchange.fetch_trades(symbol, limit=limit)
    df = pd.DataFrame(trades)
    df = df[['timestamp', 'price', 'amount']].rename(columns={'price': 'close', 'amount': 'volume'})
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def fetch_order_book(symbol):
    order_book = exchange.fetch_order_book(symbol)
    bid_wall = sum([order[1] for order in order_book['bids'][:10]])
    ask_wall = sum([order[1] for order in order_book['asks'][:10]])
    return bid_wall, ask_wall

def calculate_indicators(df):
    ema5 = EMAIndicator(close=df['close'], window=5).ema_indicator()
    ema10 = EMAIndicator(close=df['close'], window=10).ema_indicator()
    obv = OnBalanceVolumeIndicator(close=df['close'], volume=df['volume']).on_balance_volume()
    maobv = EMAIndicator(close=obv, window=10).ema_indicator()
    macd_obj = MACD(close=df['close'])
    macd = macd_obj.macd()
    macd_signal = macd_obj.macd_signal()
    rsi = RSIIndicator(close=df['close']).rsi()
    return ema5, ema10, obv, maobv, macd, macd_signal, rsi

def check_alerts(df, ema5, ema10, obv, maobv, macd, macd_signal, rsi):
    bid_wall, ask_wall = fetch_order_book(symbol)
    diff_ema = (ema5.iloc[-1] - ema10.iloc[-1]) / ema10.iloc[-1] * 100
    diff_obv = (obv.iloc[-1] - maobv.iloc[-1]) / maobv.iloc[-1] * 100
    macd_condition = macd.iloc[-1] > macd_signal.iloc[-1]
    rsi_value = rsi.iloc[-1]

    if diff_ema < 0.3 and diff_obv > 0.5 and macd_condition and rsi_value > 60 and bid_wall > ask_wall:
        message = (
            f"*Trendfordulás jele (RSI megerősítés!)*\n"
            f"Ár: {df['close'].iloc[-1]:.2f} USDT\n"
            f"EMA diff: {diff_ema:.2f}%\n"
            f"OBV diff: {diff_obv:.2f}%\n"
            f"RSI: {rsi_value:.2f}"
        )
        send_telegram_alert(message)
        return True
    return False

print("Bot aktiv.")

while True:
    try:
        df = fetch_tick_data()
        ema5, ema10, obv, maobv, macd, macd_signal, rsi = calculate_indicators(df)
        check_alerts(df, ema5, ema10, obv, maobv, macd, macd_signal, rsi)
        time.sleep(check_interval)
    except Exception as e:
        print(f"Hiba történt: {e}")
        time.sleep(check_interval)

