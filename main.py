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

PAIRS = ["PI_USDT", "SOL_USDT", "TRUMP_USDT", "PEPE_USDT", "XRP_USDT"]  # Pi token hozzáadva

# --- Telegram üzenet küldése ---
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

# --- Adatlekérés Gate.io-ról (robosztus oszlopszám-kezelés) ---
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

    # Csak az első 7 oszlopot használjuk fel
    rows = [row[:7] for row in raw if isinstance(row, list) and len(row) >= 7]
    if not rows:
        logging.error(f"{pair} ({interval}): nincs használható adat.")
        return None

    cols = ["timestamp","volume","close","high","low","open","currency_volume"]
    df = pd.DataFrame(rows, columns=cols)
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"], errors="coerce"), unit="s")
    for c in ["open","high","low","close","volume","currency_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("timestamp").reset_index(drop=True)

# --- Indikátorok számítása ---
def calculate_indicators(df):
    df["EMA12"]  = df["close"].ewm(span=12, adjust=False, min_periods=12).mean()
    df["EMA26"]  = df["close"].ewm(span=26, adjust=False, min_periods=26).mean()
    df["EMA50"]  = df["close"].ewm(span=50, adjust=False, min_periods=50).mean()
    df["MACD"]   = df["EMA12"] - df["EMA26"]
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False, min_periods=9).mean()
    delta         = df["close"].diff()
    gain          = delta.where(delta > 0, 0.0).rolling(14, min_periods=1).mean()
    loss          = -delta.where(delta < 0, 0.0).rolling(14, min_periods=1).mean()
    rs            = gain / loss
    df["RSI"]   = 100 - (100 / (1 + rs))
    # On-Balance Volume
    obv = [0]
    for i in range(1, len(df)):
        obv.append(obv[-1] + (df["volume"].iat[i] if df["close"].iat[i] > df["close"].iat[i-1] else -df["volume"].iat[i]))
    df["OBV"] = obv
    return df

# --- Mikro-kitörés szűrő ---
def is_valid_micro_breakout(df):
    return all([
        df["EMA12"].iat[-1] > df["EMA26"].iat[-1] > df["EMA50"].iat[-1],        # ema bull
        df["MACD"].iat[-1] > df["Signal"].iat[-1] and df["MACD"].iat[-2] < df["Signal"].iat[-2],  # macd cross
        df["RSI"].iat[-1] > 55 and df["RSI"].iat[-2] > 50,                                  # rsi
        df["OBV"].iat[-1] > df["OBV"].rolling(10).mean().iat[-1],                           # obv > ma
        df["volume"].iat[-1] > df["volume"].iat[-2],                                        # volumen rise
        df["close"].iat[-1] > df["open"].iat[-1] and df["close"].iat[-2] > df["open"].iat[-2],  # 2 green
        df["low"].iat[-1] > df["low"].iat[-2]                                               # higher low
    ])

# --- Bálna manipuláció szűrő ---
def is_whale_manipulation(df):
    return sum([
        (df["high"].iat[-1] - df["close"].iat[-1]) > 2 * (df["close"].iat[-1] - df["open"].iat[-1]),  # wick
        df["RSI"].iat[-2] > 70 and df["RSI"].iat[-1] < 50,     # rsi dump
        df["OBV"].iat[-1] < df["OBV"].iat[-2]                  # obv fall
    ]) >= 2

# --- Fő futtató ---
def main():
    logging.info("🚀 Mikro-kitöréses sniper bot v2.0 elindult!")
    report_long = []

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
        if score30 >= 3:
            report_long.append((pair, score30))
        else:
            logging.info(f"{pair} (30m): score {score30} < 3, kihagyva trend long.")

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
            logging.info(f"{pair} (5m): score {score5} < 2, kihagyva scalp.")
            continue

        # 3) Mikro-kitörés + whale-szűrés
        if is_valid_micro_breakout(df5) and not is_whale_manipulation(df5):
            msg  = f"🚀 *Mikro-kitörés észlelve!*\n\n• `{pair}` — 30m score: *{score30}*, 5m score: *{score5}*\n\n"
            msg += "Belépési jelek:\n✔️ EMA bull trend\n✔️ MACD bull cross\n✔️ OBV & volumen spike\n✔️ RSI emelkedés\n"
            msg += "\nEz egy friss bull trend eleje lehet!"
            send_telegram_message(msg)
        else:
            logging.info(f"{pair}: mikro-kitörés nem validálva vagy whale-manipuláció.")

    # --- Trendkövető long jelzések ---
    if report_long:
        ranked = sorted(report_long, key=lambda x: x[1], reverse=True)
        msg = "📈 *Bullish trendforduló / long lehetőségek:*\n\n"
        for pair, sc in ranked:
            msg += f"• `{pair}` — 30m score: *{sc}*\n"
        send_telegram_message(msg)

if __name__ == "__main__":
    main()
```
