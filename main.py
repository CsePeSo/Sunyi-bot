import asyncio
import logging
import pandas as pd
import time
import requests
import os
import ccxt.async_support as ccxt
import numpy as np
from ta.volume import OnBalanceVolumeIndicator
from ta.momentum import RSIIndicator
from datetime import datetime

# --- Beállítások ---
SYMBOL = 'PI/USDT'
SCORE_THRESHOLD = 3  # Pontküszöb
TIMEFRAME = '5m'    # Időkeret
RIASZTAS_COOLDOWN = 300  # Másodperc
FETCH_INTERVAL = 60      # Másodpercenként lekérdezés

# --- Telegram értesítés ---
BOT_TOKEN = os.getenv("TG_API_KEY")
CHAT_ID = os.getenv("TG_CHAT_ID")

def send_telegram_alert(message):
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("Telegram adatok hiányoznak, riasztás nem lett elküldve")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
        logging.info("Riasztás elküldve")
    except Exception as e:
        logging.error(f"Telegram hiba: {e}")

# --- Loggolás beállítása ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Aszinkron tőzsde kapcsolat ---
def get_exchange():
    return ccxt.gateio({
        'apiKey': os.getenv("GATEIO_API_KEY"),
        'secret': os.getenv("GATEIO_SECRET"),
        'enableRateLimit': True
    })

# --- Legutóbbi gyertya lekérése ---
async def fetch_latest_candle(exchange, symbol, timeframe=TIMEFRAME):
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=1)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        logging.error(f"Hiba az utolsó gyertya lekérésénél: {e}")
        return pd.DataFrame()

# --- Indikátorok számítása pandas ewm-mel ---
def compute_indicators(df):
    if df.empty or len(df) < 30:
        return None
    df = df.copy()
    # EMA-k
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
    df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
    # OBV
    df['obv'] = OnBalanceVolumeIndicator(close=df['close'], volume=df['volume']).on_balance_volume()
    df['maobv'] = df['obv'].rolling(window=10).mean()
    # MACD (kézi számítás)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    # RSI (kézi számítás)
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ema_up = up.ewm(span=14, adjust=False).mean()
    ema_down = down.ewm(span=14, adjust=False).mean()
    rs = ema_up / ema_down
    df['rsi'] = 100 - (100 / (1 + rs))
    # További indikátorok
    df['close_change_pct'] = df['close'].pct_change() * 100
    df['high_low_range'] = (df['high'] - df['low']) / df['low'] * 100
    df['uptrend_score'] = (df['close'] > df['open']).rolling(window=5).sum()
    df['candle_body'] = (df['close'] - df['open']) / df['open'] * 100
    return df.dropna()

# --- Pullback detektálás ---
def is_pullback(df):
    last_n = 10
    min_idx = df['close'].iloc[-last_n:].idxmin()
    min_pos = df.index.get_loc(min_idx)
    recent_min_pos = len(df) - min_pos <= last_n
    significant_drop = False
    if recent_min_pos:
        pre_min_high = df['high'].iloc[max(0, min_pos-last_n):min_pos].max()
        drop_pct = (pre_min_high - df['close'].iloc[min_pos]) / pre_min_high * 100
        significant_drop = drop_pct > 1.5
    recent_recovery = (df['close'].iloc[-3:] > df['open'].iloc[-3:]).sum() >= 2
    closing_strength = df['close'].iloc[-1] > df['close'].iloc[-3:-1].mean()
    ema_bullish = df['ema5'].iloc[-1] > df['ema10'].iloc[-1]
    ema_turning = df['ema5'].diff().iloc[-1] > 0
    rsi_recovery = df['rsi'].iloc[-1] > 45 and df['rsi'].diff().iloc[-1] > 0
    is_valid = (significant_drop and recent_recovery and closing_strength and (ema_bullish or ema_turning) and rsi_recovery)
    if significant_drop and recent_recovery:
        logging.debug(f"Pullback: drop={drop_pct:.2f}%, EMAbull={ema_bullish}, RSI={df['rsi'].iloc[-1]:.1f}")
    return is_valid

# --- Pontszám számítás ---
def compute_score(df):
    score = 0
    avg_vol = df['volume'].tail(20).mean()
    if df['volume'].iloc[-1] > avg_vol * 1.2:
        score += 1
    if df['obv'].iloc[-1] > df['obv'].iloc[-2] and df['obv'].iloc[-1] > df['maobv'].iloc[-1]:
        score += 1
    if df['macd_hist'].iloc[-1] > 0 and df['macd_hist'].iloc[-1] > df['macd_hist'].iloc[-2]:
        score += 1
    if df['rsi'].iloc[-1] > 50 and df['rsi'].iloc[-1] < 70:
        score += 1
    elif df['rsi'].iloc[-1] > 45 and df['rsi'].diff().iloc[-1] > 1:
        score += 0.5
    if df['close'].iloc[-1] > df['ema5'].iloc[-1] and df['close'].iloc[-1] > df['ema10'].iloc[-1]:
        score += 1
    if df['candle_body'].iloc[-1] > 0.5:
        score += 0.5
    if df['close_change_pct'].iloc[-1] > 0 and df['close_change_pct'].iloc[-2] > 0:
        score += 0.5
    return score

last_alert = 0

def check_trigger(df):
    global last_alert
    now = time.time()
    if now - last_alert < RIASZTAS_COOLDOWN:
        return
    if not is_pullback(df):
        return
    score = compute_score(df)
    if score >= SCORE_THRESHOLD:
        price = df['close'].iloc[-1]
        msg = (f"🚀 [SCALP PI EMELKEDÉS]\nÁr: {price:.5f} USDT\nPontszám: {score:.1f}/{SCORE_THRESHOLD}\n"
               f"RSI: {df['rsi'].iloc[-1]:.1f}\nEMA5/10: {df['ema5'].iloc[-1]:.5f}/{df['ema10'].iloc[-1]:.5f}")
        send_telegram_alert(msg)
        last_alert = now
        logging.info(f"Riasztás: {msg}")

# --- Fő aszinkron ciklus ---
async def run():
    exchange = get_exchange()
    await exchange.load_markets()
    initial = "PI figyelés elindult és figyel, mint egy CIA ügynök Red Bull után."
    logging.info(initial)
    send_telegram_alert(initial)
    while True:
        df = await fetch_latest_candle(exchange, SYMBOL, TIMEFRAME)
        indicators = compute_indicators(df)
        if indicators is not None:
            check_trigger(indicators)
        await asyncio.sleep(FETCH_INTERVAL)

if __name__ == '__main__':
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logging.info('Bot leállítva')

