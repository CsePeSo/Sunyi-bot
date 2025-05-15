
import requests
import pandas as pd
import os
import logging

# --- Logging beállítások ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- Környezeti változók (strip a véletlen whitespace eltávolításához) ---
TOKEN           = os.getenv("TG_API_KEY", "").strip()
CHAT_ID         = os.getenv("TG_CHAT_ID", "").strip()
GATE_API_KEY    = os.getenv("GATEIO_KEY", "").strip()
GATE_SECRET_KEY = os.getenv("GATEIO_SECRET", "").strip()

# --- Telegram üzenet küldése ---
def send_telegram_message(message):
    if not TOKEN or not CHAT_ID:
        logging.warning("Hiányzó Telegram beállítások (TG_API_KEY vagy TG_CHAT_ID)!")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=data)
        r.raise_for_status()
        logging.info("Telegram üzenet sikeresen elküldve.")
    except Exception as e:
        logging.error(f"Telegram hiba: {e}")

# --- Coinpárok ---
PAIRS = ["PI_USDT", "SOL_USDT", "XRP_USDT", "PEPE_USDT", "TRUMP_USDT"]

# --- Üdvözlő üzenet ---
if GATE_API_KEY and GATE_SECRET_KEY:
    send_telegram_message("🤖 A több coin figyelő bot elindult!")
else:
    msg = (
        "A bot nem tud elindulni a hiányzó Gate.io API kulcsok miatt "
        "(GATEIO_KEY vagy GATEIO_SECRET). Kérlek, állítsd be őket."
    )
    logging.critical(msg)
    send_telegram_message(msg)

# --- Adatok lekérése ---
def fetch_data(pair):
    if not GATE_API_KEY or not GATE_SECRET_KEY:
        logging.error(f"{pair} lekérés hiba: Hiányzó Gate.io API kulcsok.")
        return None

    url = (
        f"https://api.gateio.ws/api/v4/spot/candlesticks?"
        f"currency_pair={pair}&limit=30&interval=1h"
    )
    try:
        logging.info(f"Adatok lekérése: {pair}")
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
        r.raise_for_status()
        raw = r.json()

        # Csak azok a sorok kerülnek be, ahol legalább 7 elem van,
        # és minden sorból csak az első 7 mezőt használjuk
        valid_rows = []
        for i, row in enumerate(raw):
            if not isinstance(row, list) or len(row) < 7:
                logging.warning(f"{pair}: váratlan sor hossz ({len(row)}) az indexen {i}, kihagyva.")
                continue
            valid_rows.append(row[:7])

        if not valid_rows:
            logging.error(f"{pair}: egyetlen használható sor sem érkezett.")
            return None

        columns = [
            "timestamp",
            "volume",
            "close",
            "high",
            "low",
            "open",
            "currency_volume",
        ]
        df = pd.DataFrame(valid_rows, columns=columns)

        # Típuskonverziók
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        for c in ["open", "high", "low", "close", "volume", "currency_volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        df = df.sort_values("timestamp").reset_index(drop=True)
        logging.info(f"{pair}: {len(df)} sor adat sikeresen feldolgozva.")
        return df

    except Exception as e:
        logging.error(f"{pair} lekérési hiba: {e}")
        return None

# --- RSI számítása ---
def calculate_rsi(series, period=14):
    if not isinstance(series, pd.Series) or series.empty:
        return pd.Series(dtype=float)
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period, min_periods=1).mean()
    loss = -delta.where(delta < 0, 0.0).rolling(window=period, min_periods=1).mean()
    rs = gain / loss
    rs = rs.replace([float('inf'), -float('inf')], float('nan'))
    return 100 - (100 / (1 + rs))

# --- Score számítása ---
def calculate_score(df):
    if len(df) < 2:
        return 0
    score = 0
    # EMA trend megerősítés
    if df["EMA12"].iloc[-1] > df["EMA26"].iloc[-1] and df["EMA26"].iloc[-1] > df["EMA26"].iloc[-2]:
        score += 1
    # MACD kereszteződés
    if df["MACD"].iloc[-1] > df["Signal"].iloc[-1] and df["MACD"].iloc[-2] < df["Signal"].iloc[-2]:
        score += 1
    # RSI szűrés
    if df["RSI"].iloc[-1] > 60:
        score += 1
    # EMA50 távolságszűrés
    ema50 = df["EMA50"].iloc[-1]
    price = df["close"].iloc[-1]
    if ema50 and 2 <= abs((price - ema50) / ema50) * 100 <= 3:
        score += 1
    # Volumen megerősítés
    if len(df) >= 6:
        inflow = (price - df["open"].iloc[-1]) * df["volume"].iloc[-1]
        avg_inflow = ((df["close"] - df["open"]) * df["volume"]).iloc[-6:-1].mean()
        if pd.notna(avg_inflow) and inflow > avg_inflow:
            score += 1
    return score

# --- Fő ciklus, riport és Telegram ---
report = []
if GATE_API_KEY and GATE_SECRET_KEY:
    for pair in PAIRS:
        df = fetch_data(pair)
        if df is None or len(df) < 50:
            logging.warning(f"{pair}: nincs elég adat, kihagyva.")
            continue

        # Indikátorok számítása
        df["EMA12"] = df["close"].ewm(span=12, adjust=False, min_periods=12).mean()
        df["EMA26"] = df["close"].ewm(span=26, adjust=False, min_periods=26).mean()
        df["EMA50"] = df["close"].ewm(span=50, adjust=False, min_periods=50).mean()
        df["MACD"]   = df["EMA12"] - df["EMA26"]
        df["Signal"] = df["MACD"].ewm(span=9, adjust=False, min_periods=9).mean()
        df["RSI"]    = calculate_rsi(df["close"])

        # Score és gyűjtés
        s = calculate_score(df.tail(50))
        if s >= 3.5:
            report.append((pair, s))

# Jelentés összeállítása és küldése
if report:
    report.sort(key=lambda x: x[1], reverse=True)
    msg = "📈 *Bullish score alapján erős coinok:*\n\n"
    for p, s in report:
        msg += f"• `{p}` — score: *{s}*\n"
else:
    msg = "ℹ️ A bot lefutott, de nem talált erős bullish jelzést."
send_telegram_message(msg)
