
import os
import requests
import logging
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime
from ta.volume import OnBalanceVolumeIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, MACD

# --- Alapbeállítások ---
logging.basicConfig(level=logging.INFO)

# --- Telegram küldés ---
TG_API_KEY = os.getenv("TG_API_KEY")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

def send_telegram_alert(message: str):
    if not TG_API_KEY or not TG_CHAT_ID:
        logging.warning("Telegram adatok hiányoznak, riasztás nem lett elküldve")
        return
    url = f"https://api.telegram.org/bot{TG_API_KEY}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            logging.error(f"Telegram API hiba: {response.text}")
        else:
            logging.info("Riasztás elküldve.")
    except Exception as e:
        logging.error(f"Telegram hiba: {e}")

# --- Indikátorok kiszámítása ---
def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna().copy()
    df = df.astype({'close': 'float32', 'volume': 'float32', 'high': 'float32', 'low': 'float32'})

    df['ema5'] = EMAIndicator(close=df['close'], window=5).ema_indicator().astype('float32')
    df['ema10'] = EMAIndicator(close=df['close'], window=10).ema_indicator().astype('float32')

    macd = MACD(close=df['close'], window_slow=26, window_fast=12, window_sign=9)
    df['macd'] = macd.macd().astype('float32')
    df['macd_signal'] = macd.macd_signal().astype('float32')
    df['dif'] = df['macd']
    df['dea'] = df['macd_signal']
    df['macd_pct'] = (df['macd'] / df['close'] * 100).astype('float32')

    kdj = StochasticOscillator(high=df['high'], low=df['low'], close=df['close'], window=9, smooth_window=3)
    df['k'] = kdj.stoch().astype('float32')
    df['d'] = kdj.stoch_signal().astype('float32')
    df['j'] = (3 * df['k'] - 2 * df['d']).astype('float32')
    df['j_smooth'] = df['j'].rolling(window=3).mean().astype('float32')

    obv = OnBalanceVolumeIndicator(close=df['close'], volume=df['volume'])
    df['obv'] = obv.on_balance_volume().astype('float32')
    df['wmaobv'] = df['obv'].ewm(span=10, adjust=False).mean().astype('float32')

    df = df[['close', 'volume', 'ema5', 'ema10', 'macd', 'macd_signal', 'macd_pct',
             'dif', 'dea', 'k', 'd', 'j', 'j_smooth', 'obv', 'wmaobv']]
    return df.dropna()

# --- Adatok előfeldolgozása ---
def process_indicators(df_1m, df_5m):
    if df_1m.empty or df_5m.empty:
        logging.warning("Hiba: Üres adatkeret érkezett.")
        return df_1m, df_5m
    return calculate_indicators(df_1m), calculate_indicators(df_5m)

# --- Snapshot építés ---
def safe_get_last(df, column):
    return np.float32(df[column].iloc[-1]) if not df.empty and column in df else None

def build_snapshot(df_1m: pd.DataFrame, df_5m: pd.DataFrame) -> dict:
    snapshot = {
        "timestamp": pd.Timestamp.utcnow(),
        "ema5_avg": np.float32((safe_get_last(df_1m, "ema5") + safe_get_last(df_5m, "ema5")) / 2),
        "ema10_avg": np.float32((safe_get_last(df_1m, "ema10") + safe_get_last(df_5m, "ema10")) / 2),
        "ema_gap_avg": np.float32(((safe_get_last(df_1m, "ema5") - safe_get_last(df_1m, "ema10")) +
                                   (safe_get_last(df_5m, "ema5") - safe_get_last(df_5m, "ema10"))) / 2),
        "dif_avg": np.float32((safe_get_last(df_1m, "dif") + safe_get_last(df_5m, "dif")) / 2),
        "dea_avg": np.float32((safe_get_last(df_1m, "dea") + safe_get_last(df_5m, "dea")) / 2),
        "macd_pct_avg": np.float32((safe_get_last(df_1m, "macd_pct") + safe_get_last(df_5m, "macd_pct")) / 2),
        "k_avg": np.float32((safe_get_last(df_1m, "k") + safe_get_last(df_5m, "k")) / 2),
        "d_avg": np.float32((safe_get_last(df_1m, "d") + safe_get_last(df_5m, "d")) / 2),
        "j_avg": np.float32((safe_get_last(df_1m, "j") + safe_get_last(df_5m, "j")) / 2),
        "j_smooth_avg": np.float32((safe_get_last(df_1m, "j_smooth") + safe_get_last(df_5m, "j_smooth")) / 2),
        "obv_avg": np.float32((safe_get_last(df_1m, "obv") + safe_get_last(df_5m, "obv")) / 2),
        "wmaobv_avg": np.float32((safe_get_last(df_1m, "wmaobv") + safe_get_last(df_5m, "wmaobv")) / 2),
    }
    snapshot = {k: 0.0 if v is None or (isinstance(v, float) and np.isnan(v)) else v for k, v in snapshot.items()}
    return snapshot

# --- Értékelés ---
def evaluate_snapshot(snapshot: dict, score_threshold: float = 3.0) -> tuple:
    score = 0.0
    log = []

    if snapshot["k_avg"] > snapshot["d_avg"] and snapshot["j_avg"] > 55:
        score += 1.2
        log.append("KDJ bullish")
    if snapshot["dif_avg"] > snapshot["dea_avg"]:
        score += 1.2
        log.append("MACD DIF > DEA")
    if snapshot["macd_pct_avg"] > 0.05:
        score += 0.5
        log.append("MACD % pozitív")
    if snapshot["ema5_avg"] > snapshot["ema10_avg"]:
        score += 1.0
        log.append("EMA5 > EMA10")
    if snapshot["ema_gap_avg"] > 0.0004:
        score += 0.3
        log.append("EMA GAP pozitív")
    if snapshot["wmaobv_avg"] > 0:
        obv_diff = (snapshot["obv_avg"] - snapshot["wmaobv_avg"]) / snapshot["wmaobv_avg"]
        if obv_diff > 0.01:
            score += 1.0
            log.append("OBV jelentős növekedés")

    score = round(score, 2)
    signal = "BUY" if score >= score_threshold else "HOLD" if score >= score_threshold * 0.8 else "NO_SIGNAL"
    print(f"[DEBUG] Signal: {signal}, Score: {score}, Log: {log}")
    return signal, score, log

# --- Feldolgozás + Jelzés küldése ---
def process_snapshot(snapshot: dict):
    signal, score, reasons = evaluate_snapshot(snapshot)

    if signal == "BUY":
        msg = (
            f"🚀 *PI/USDT SCALP JELZÉS*\n"
            f"EMA5 átlag: {snapshot['ema5_avg']:.5f}\n"
            f"Pontszám: {score}/3.0\n"
            f"Indokok:\n- " + "\n- ".join(reasons)
        )
        send_telegram_alert(msg)
    elif signal == "HOLD":
        msg = f"⏸️ *PI HOLD jelzés*\nPontszám: {score}/3.0\nIndok: {', '.join(reasons)}"
        send_telegram_alert(msg)

# --- CCXT és adathívás ---
def get_exchange():
    return ccxt.gateio({
        'apiKey': os.getenv("GATEIO_API_KEY"),
        'secret': os.getenv("GATEIO_SECRET"),
        'enableRateLimit': True
    })

async def fetch_ohlcv(exchange, symbol, timeframe, limit=50, retries=3):
    for attempt in range(retries):
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
            logging.error(f"[{timeframe}] Hiba: {e}")
            await asyncio.sleep(2)
    return pd.DataFrame()

# --- Fő ciklus ---
async def main_loop():
    SYMBOL = 'PI/USDT'
    TIMEFRAME_1M = '1m'
    TIMEFRAME_5M = '5m'
    INTERVAL = 30

    exchange = get_exchange()
    await exchange.load_markets()
    send_telegram_alert("✅ *PI/USDT figyelés elindult!*")

    while True:
        df_1m = await fetch_ohlcv(exchange, SYMBOL, TIMEFRAME_1M)
        df_5m = await fetch_ohlcv(exchange, SYMBOL, TIMEFRAME_5M)

        df_1m, df_5m = process_indicators(df_1m, df_5m)
        if not df_1m.empty and not df_5m.empty:
            snapshot = build_snapshot(df_1m, df_5m)
            process_snapshot(snapshot)

        await asyncio.sleep(INTERVAL)

# --- Indítás ---
if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logging.info("Figyelés manuálisan leállítva.")

