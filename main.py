
import asyncio
import logging
import pandas as pd
import time
import requests
import os
import ccxt.async_support as ccxt
import numpy as np
from ta.volume import OnBalanceVolumeIndicator
from datetime import datetime

# --- Konfiguráció ---
SYMBOL = 'PI/USDT'
TIMEFRAME = '1m'
RIASZTAS_COOLDOWN = 180
FETCH_INTERVAL = 30
SCORE_THRESHOLD = 3

TG_API_KEY = os.getenv("TG_API_KEY")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# --- Telegram ---
def send_telegram_alert(message):
    if not TG_API_KEY or not TG_CHAT_ID:
        logging.warning("Telegram adatok hiányoznak, riasztás nem lett elküldve")
        return
    url = f"https://api.telegram.org/bot{TG_API_KEY}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
        logging.info("Riasztás elküldve")
    except Exception as e:
        logging.error(f"Telegram hiba: {e}")

# --- Loggolás ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Exchange ---
def get_exchange():
    return ccxt.gateio({
        'apiKey': os.getenv("GATEIO_API_KEY"),
        'secret': os.getenv("GATEIO_SECRET"),
        'enableRateLimit': True
    })

# --- Candle fetch ---
async def fetch_latest_candle(exchange, symbol, timeframe=TIMEFRAME):
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=30)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        logging.error(f"Hiba a gyertyák lekérésénél: {e}")
        return pd.DataFrame()

# --- Indikátor számítás ---
def compute_indicators(df):
    if df.empty or len(df) < 30:
        return None
    df = df.copy()
    df['ema5'] = df['close'].ewm(span=5).mean()
    df['ema10'] = df['close'].ewm(span=10).mean()
    df['ema30'] = df['close'].ewm(span=30).mean()
    df['obv'] = OnBalanceVolumeIndicator(close=df['close'], volume=df['volume']).on_balance_volume()
    df['maobv'] = df['obv'].rolling(window=10).mean()
    ema12 = df['close'].ewm(span=12).mean()
    ema26 = df['close'].ewm(span=26).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ema_up = up.ewm(span=14).mean()
    ema_down = down.ewm(span=14).mean()
    rs = ema_up / ema_down
    df['rsi'] = 100 - (100 / (1 + rs))
    df['close_change_pct'] = df['close'].pct_change() * 100
    df['candle_body'] = (df['close'] - df['open']) / df['open'] * 100
    return df.dropna()

# --- Pullback logika ---
def is_pullback(df):
    last_n = 10
    min_idx = df['close'].iloc[-last_n:].idxmin()
    min_pos = df.index.get_loc(min_idx)
    recent_min_pos = len(df) - min_pos <= last_n
    significant_drop = False
    if recent_min_pos:
        pre_min_high = df['high'].iloc[max(0, min_pos-last_n):min_pos].max()
        drop_pct = (pre_min_high - df['close'].iloc[min_pos]) / pre_min_high * 100
        significant_drop = drop_pct > 1.0
    recent_recovery = (df['close'].iloc[-3:] > df['open'].iloc[-3:]).sum() >= 2
    closing_strength = df['close'].iloc[-1] > df['close'].iloc[-3:-1].mean()
    ema_bullish = df['ema5'].iloc[-1] > df['ema10'].iloc[-1]
    rsi_recovery = df['rsi'].iloc[-1] > 45 and df['rsi'].diff().iloc[-1] > 0
    return (significant_drop and recent_recovery and closing_strength and ema_bullish and rsi_recovery)

# --- Smart Money Early Trigger ---
monitor_active = False

def smart_money_trigger(df):
    global monitor_active
    last = df.iloc[-1]
    if (
        last['obv'] > df['maobv'].iloc[-1] and
        last['ema5'] > last['ema10'] and
        last['volume'] > df['volume'].tail(20).mean() * 1.5
    ):
        if not monitor_active:
            msg = f"🧠 [PI/USDT SCALP ÉBERSÉG] – *Előzetes aktivitás érzékelve*\nÁr: {last['close']:.5f}"
            send_telegram_alert(msg)
            monitor_active = True
    else:
        monitor_active = False

# --- Breakout pontszám ---
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
    if df['close'].iloc[-1] > df['ema5'].iloc[-1] and df['close'].iloc[-1] > df['ema10'].iloc[-1]:
        score += 1
    if df['candle_body'].iloc[-1] > 0.5:
        score += 0.5
    if df['close_change_pct'].iloc[-1] > 0 and df['close_change_pct'].iloc[-2] > 0:
        score += 0.5
    return score

last_alert = 0

def check_main_trigger(df):
    global last_alert
    now = time.time()
    if now - last_alert < RIASZTAS_COOLDOWN:
        return
    score = compute_score(df)
    pullback = is_pullback(df)
    if score >= SCORE_THRESHOLD or pullback:
        price = df['close'].iloc[-1]
        msg = (f"🚀 [PI/USDT SCALP ÉBERSÉG] – *Megerősített breakout trigger*\n"
               f"Ár: {price:.5f} USDT\n"
               f"Pontszám: {score:.1f}/{SCORE_THRESHOLD}\n"
               f"RSI: {df['rsi'].iloc[-1]:.1f} | EMA5/10: {df['ema5'].iloc[-1]:.5f}/{df['ema10'].iloc[-1]:.5f}")
        send_telegram_alert(msg)
        last_alert = now

# --- Fő ciklus ---
async def run():
    exchange = get_exchange()
    await exchange.load_markets()
    logging.info("PI breakout + smart money figyelés elindult.")
    send_telegram_alert("✅ PI/USDT 2-lépcsős scalp figyelő ELINDULT – várja a jeleket!")
    while True:
        df = await fetch_latest_candle(exchange, SYMBOL, TIMEFRAME)
        indicators = compute_indicators(df)
        if indicators is not None:
            smart_money_trigger(indicators)
            check_main_trigger(indicators)
        await asyncio.sleep(FETCH_INTERVAL)

if __name__ == '__main__':
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logging.info('Figyelés leállítva.')

