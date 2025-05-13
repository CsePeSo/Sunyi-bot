import pandas as pd
import time
import requests
import logging
import os
import ccxt
from ta.volume import OnBalanceVolumeIndicator
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator

# --- Beállítások ---
SYMBOL = 'PI/USDT'
SCORE_THRESHOLD = 3
CANDLE_SECONDS = 5
RIASZTAS_COOLDOWN = 60

# --- Telegram ---
BOT_TOKEN = os.getenv("TG_API_KEY")
CHAT_ID = os.getenv("TG_CHAT_ID")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
        logging.info("Riasztás elküldve")
    except Exception as e:
        logging.error(f"Telegram hiba: {e}")

# --- Loggolás ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Tőzsde kapcsolat ---
def get_exchange():
    return ccxt.gateio({
        'apiKey': os.getenv("GATEIO_API_KEY"),
        'secret': os.getenv("GATEIO_SECRET"),
        'enableRateLimit': True
    })

# --- Tickből gyertya ---
def fetch_tick_data(exchange, symbol, limit=100):
    try:
        trades = exchange.fetch_trades(symbol, limit=limit)
        df = pd.DataFrame(trades)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        logging.error(f"Tick hiba: {e}")
        return None

def create_candle(df):
    if df is None or df.empty: return None
    end = df.index[-1]
    start = end - pd.Timedelta(seconds=CANDLE_SECONDS)
    window = df.loc[start:end]
    if window.empty: return None
    return pd.DataFrame({
        'open': [window['price'].iloc[0]],
        'high': [window['price'].max()],
        'low': [window['price'].min()],
        'close': [window['price'].iloc[-1]],
        'volume': [window['amount'].sum()]}, index=[end])

# --- Indikátorok ---
def compute_indicators(df):
    if len(df) < 30: return None
    df = df.copy()
    df['ema10'] = df['close'].ewm(span=10).mean()
    df['ema30'] = df['close'].ewm(span=30).mean()
    df['obv'] = OnBalanceVolumeIndicator(close=df['close'], volume=df['volume']).on_balance_volume()
    df['maobv'] = df['obv'].rolling(window=10).mean()
    df['macd_hist'] = MACD(close=df['close']).macd_diff()
    df['rsi'] = RSIIndicator(close=df['close']).rsi()
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    return df.dropna()

# --- Pullback + trend check ---
def is_pullback(df):
    closes = df['close'].iloc[-5:]
    pullback = closes.diff().iloc[1:-1].lt(0).sum() >= 2
    recovery = closes.iloc[-1] > closes.max()
    trend_ok = df['ema10'].iloc[-1] > df['ema30'].iloc[-1]
    return pullback and recovery and trend_ok

# --- Pontszám ---
def compute_score(df):
    score = 0
    avg_vol = df['volume'].tail(20).mean()
    if df['volume'].iloc[-1] > avg_vol * 1.07: score += 1
    if df['obv'].iloc[-1] > df['maobv'].iloc[-1]: score += 1
    if df['macd_hist'].iloc[-1] > 0: score += 1
    if df['rsi'].iloc[-1] > 50: score += 1
    if df['close'].iloc[-1] > df['vwap'].iloc[-1]: score += 1
    return score

# --- Trigger check ---
last_alert = 0

def check_trigger(df):
    global last_alert
    now = time.time()
    if now - last_alert < RIASZTAS_COOLDOWN: return
    if not is_pullback(df): return
    score = compute_score(df)
    if score >= SCORE_THRESHOLD:
        price = df['close'].iloc[-1]
        msg = f"[SCALP PI]
Ár: {price:.4f} USDT\nPontszám: {score}/5"
        send_telegram_alert(msg)
        last_alert = now

# --- Fő ciklus ---
def run():
    exchange = get_exchange()
    candles = pd.DataFrame()
    send_telegram_alert("PI figyelés elindult")
    while True:
        try:
            ticks = fetch_tick_data(exchange, SYMBOL)
            candle = create_candle(ticks)
            if candle is not None:
                candles = pd.concat([candles, candle])
                if len(candles) > 200:
                    candles = candles.tail(200)
                df = compute_indicators(candles)
                if df is not None:
                    check_trigger(df)
            time.sleep(5)
        except Exception as e:
            logging.error(f"Fő hurokhiba: {e}")
            time.sleep(10)

if __name__ == '__main__':
    run()
