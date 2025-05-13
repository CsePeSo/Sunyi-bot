import ccxt
import pandas as pd
from ta.trend import EMAIndicator, MACD
from ta.volume import OnBalanceVolumeIndicator
from ta.momentum import RSIIndicator
import requests
import time

# Tőzsde inicializálása
exchange = ccxt.gateio({'enableRateLimit': True})
symbol = 'SOL/USDT'

# Küszöbértékek
base_threshold_ema = 0.1
base_threshold_obv = 0.5
check_interval = 5
volatility_factor = 1.5

# Telegram riasztás
import os

def send_telegram_alert(message):
    bot_token = os.getenv("TG_API_KEY")
    chat_id = os.getenv("TG_CHAT_ID")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Hiba az üzenetküldésnél: {e}")

# Tick adatok lekérése
def fetch_tick_data(limit=100):
    trades = exchange.fetch_trades(symbol, limit=limit)
    df = pd.DataFrame(trades)[['timestamp', 'price', 'amount']]
    df.rename(columns={'price': 'close', 'amount': 'volume'}, inplace=True)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# Order book adatok
def fetch_order_book(symbol):
    order_book = exchange.fetch_order_book(symbol)
    bid_wall = sum([order[1] for order in order_book['bids'][:10]])
    ask_wall = sum([order[1] for order in order_book['asks'][:10]])
    spread = order_book['asks'][0][0] - order_book['bids'][0][0]
    return bid_wall, ask_wall, spread

# Indikátorok számítása
def calculate_indicators(df):
    ema5 = EMAIndicator(close=df['close'], window=5).ema_indicator()
    ema10 = EMAIndicator(close=df['close'], window=10).ema_indicator()
    ema50 = EMAIndicator(close=df['close'], window=50).ema_indicator()
    obv = OnBalanceVolumeIndicator(close=df['close'], volume=df['volume']).on_balance_volume()
    maobv = EMAIndicator(close=obv, window=10).ema_indicator()
    macd_obj = MACD(close=df['close'])
    macd = macd_obj.macd()
    macd_signal = macd_obj.macd_signal()
    rsi = RSIIndicator(close=df['close'], window=14).rsi()
    return ema5, ema10, ema50, obv, maobv, macd, macd_signal, rsi

# Volatilitás-alapú küszöbök
def adjust_thresholds(df):
    volatility = df['close'].pct_change().std()
    adaptive_threshold_ema = base_threshold_ema * volatility_factor * volatility
    adaptive_threshold_obv = base_threshold_obv * volatility_factor * volatility
    return adaptive_threshold_ema, adaptive_threshold_obv

# Legutóbbi riasztás ár
last_alert_price = None

# Riasztás logika
def check_alerts(df, ema5, ema10, ema50, obv, maobv, macd, macd_signal, rsi):
    global last_alert_price

    if len(ema5) < 10 or len(obv) < 10 or len(macd) < 9:
        return False

    bid_wall, ask_wall, _ = fetch_order_book(symbol)
    adaptive_ema, adaptive_obv = adjust_thresholds(df)

    diff_ema = (ema5.iloc[-1] - ema10.iloc[-1]) / ema10.iloc[-1] * 100
    diff_obv = (obv.iloc[-1] - maobv.iloc[-1]) / maobv.iloc[-1] * 100
    macd_condition = macd.iloc[-1] > macd_signal.iloc[-1]
    rsi_value = rsi.iloc[-1]
    current_price = df['close'].iloc[-1]

    if last_alert_price:
        price_drop = ((current_price - last_alert_price) / last_alert_price) * 100
        if price_drop < 0.3:
            return False

    if diff_ema < 0.05 or diff_obv < 5 or rsi_value < 60:
        return False

    if diff_ema < adaptive_ema and diff_obv > adaptive_obv and macd_condition and bid_wall > ask_wall:
        message = (
            f"*Trendfordulás jele (RSI megerősítés!)*\n"
            f"Ár: {current_price:.2f} USDT\n"
            f"EMA diff: {diff_ema:.2f}%\n"
            f"OBV diff: {diff_obv:.2f}%\n"
            f"RSI: {rsi_value:.2f}"
        )
        send_telegram_alert(message)
        last_alert_price = current_price
        return True

    return False

# Indítás
print("Bot aktiv.")

while True:
    try:
        df = fetch_tick_data()
        ema5, ema10, ema50, obv, maobv, macd, macd_signal, rsi = calculate_indicators(df)
        check_alerts(df, ema5, ema10, ema50, obv, maobv, macd, macd_signal, rsi)
        time.sleep(check_interval)
    except Exception as e:
        print(f"Hiba történt: {e}")
        time.sleep(check_interval)
