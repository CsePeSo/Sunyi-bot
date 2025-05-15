

import requests
import pandas as pd
import os
import logging

# --- Logging beállítások ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- Környezeti változók ---
TOKEN           = os.getenv("TG_API_KEY", "").strip()
CHAT_ID         = os.getenv("TG_CHAT_ID", "").strip()
GATE_API_KEY    = os.getenv("GATEIO_KEY", "").strip()
GATE_SECRET_KEY = os.getenv("GATEIO_SECRET", "").strip()

def send_telegram_message(message):
    if not TOKEN or not CHAT_ID:
        logging.warning("Hiányzó Telegram beállítások!")
        return
    url  = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=data)
        r.raise_for_status()
        logging.info("Telegram üzenet elküldve.")
    except Exception as e:
        logging.error(f"Telegram hiba: {e}")

PAIRS = ["SOL_USDT", "TRUMP_USDT", "PEPE_USDT", "XRP_USDT"]

def fetch_data(pair, interval="5m", limit=100):
    url = (
        f"https://api.gateio.ws/api/v4/spot/candlesticks"
        f"?currency_pair={pair}&interval={interval}&limit={limit}"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        logging.error(f"Adatlekérés hiba {pair} ({interval}): {e}")
        return None

    rows = []
    for i, row in enumerate(raw):
        if isinstance(row, list) and len(row) >= 7:
            rows.append(row[:7])
        else:
            logging.debug(f"{pair} {interval}, sor idx={i} kihagyva (elemszám={len(row) if isinstance(row, list) else 'N/A'})")

    if not rows:
        logging.error(f"{pair} ({interval}): nincs használható adat.")
        return None

    cols = ["timestamp","volume","close","high","low","open","currency_volume"]
    df = pd.DataFrame(rows, columns=cols)
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"], errors="coerce"), unit="s")
    for c in ["open","high","low","close","volume","currency_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("timestamp").reset_index(drop=True)

def calculate_indicators(df):
    df["EMA12"]  = df["close"].ewm(span=12, adjust=False, min_periods=12).mean()
    df["EMA26"]  = df["close"].ewm(span=26, adjust=False, min_periods=26).mean()
    df["EMA50"]  = df["close"].ewm(span=50, adjust=False, min_periods=50).mean()
    df["MACD"]   = df["EMA12"] - df["EMA26"]
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False, min_periods=9).mean()
    delta       = df["close"].diff()
    gain        = delta.where(delta > 0, 0.0).rolling(14, min_periods=1).mean()
    loss        = -delta.where(delta < 0, 0.0).rolling(14, min_periods=1).mean()
    rs          = gain / loss
    df["RSI"]   = 100 - (100 / (1 + rs))

    # On-Balance Volume (OBV)
    obv = [0]
    for i in range(1, len(df)):
        obv.append(
            obv[-1]
            + (df["volume"].iat[i] if df["close"].iat[i] > df["close"].iat[i-1] else -df["volume"].iat[i])
        )
    df["OBV"] = obv
    return df

def is_valid_micro_breakout(df):
    ema_bull     = df["EMA12"].iat[-1] > df["EMA26"].iat[-1] > df["EMA50"].iat[-1]
    macd_cross   = df["MACD"].iat[-1] > df["Signal"].iat[-1] and df["MACD"].iat[-2] < df["Signal"].iat[-2]
    rsi_ok       = df["RSI"].iat[-1] > 55 and df["RSI"].iat[-2] > 50
    obv_ma       = (
        df["OBV"].iat[-1] > df["OBV"].rolling(10).mean().iat[-1]
        and
        df["OBV"].iat[-2] > df["OBV"].rolling(10).mean().iat[-2]
    )
    vol_rise     = df["volume"].iat[-1] > df["volume"].iat[-2]
    green_candles= df["close"].iat[-1] > df["open"].iat[-1] and df["close"].iat[-2] > df["open"].iat[-2]
    higher_low   = df["low"].iat[-1] > df["low"].iat[-2]
    return all([ema_bull, macd_cross, rsi_ok, obv_ma, vol_rise, green_candles, higher_low])

def is_whale_manipulation(df):
    wick_ratio = (df["high"].iat[-1] - df["close"].iat[-1]) > 2 * (df["close"].iat[-1] - df["open"].iat[-1])
    rsi_dump   = df["RSI"].iat[-2] > 70 and df["RSI"].iat[-1] < 50
    obv_fall   = df["OBV"].iat[-1] < df["OBV"].iat[-2]
    return sum([wick_ratio, rsi_dump, obv_fall]) >= 2

def main():
    logging.info("🚀 Mikro-kitöréses sniper bot v2.0 elindult!")
    for pair in PAIRS:
        # 1) 30m trendfilter
        df30 = fetch_data(pair, interval="30m", limit=100)
        if df30 is None or len(df30) < 50:
            logging.info(f"{pair} (30m): nem elég adat.")
            continue
        df30 = calculate_indicators(df30)
        score30 = sum([
            df30["EMA12"].iat[-1] > df30["EMA26"].iat[-1],
            df30["MACD"].iat[-1] > df30["Signal"].iat[-1],
            df30["RSI"].iat[-1] > 60,
        ])
        if score30 < 3:
            logging.info(f"{pair} (30m): score {score30} < 3, kihagyva.")
            continue

        # 2) 5m scalpelés
        df5 = fetch_data(pair, interval="5m", limit=100)
        if df5 is None or len(df5) < 50:
            logging.info(f"{pair} (5m): nem elég adat.")
            continue
        df5 = calculate_indicators(df5)
        score5 = sum([
            df5["EMA12"].iat[-1] > df5["EMA26"].iat[-1],
            df5["MACD"].iat[-1] > df5["Signal"].iat[-1],
            df5["RSI"].iat[-1] > 55,
        ])
        if score5 < 2:
            logging.info(f"{pair} (5m): score {score5} < 2, kihagyva.")
            continue

        # 3) Mikro-kitörés + whale-szűrés
        if is_valid_micro_breakout(df5) and not is_whale_manipulation(df5):
            msg  = f"🚀 *Mikro-kitörés észlelve!*\\n\\n• `{pair}` — 30m score: *{score30}*, 5m score: *{score5}*\\n\\n"
            msg += "Belépési jelek:\\n✔️ EMA bull trend\\n✔️ MACD bull cross\\n✔️ OBV & volumen spike\\n✔️ RSI emelkedés\\n"
            msg += "\\nEz egy friss bull trend eleje lehet!"
            send_telegram_message(msg)
        else:
            logging.info(f"{pair}: mikro-kitörés nem validálva vagy whale-manipuláció.")

if __name__ == "__main__":
    main()
