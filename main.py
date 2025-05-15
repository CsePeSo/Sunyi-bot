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

# --- Paraméterek több timeframe-hez ---
PRIMARY_INTERVAL   = "30m"
SECONDARY_INTERVAL = "5m"
LIMIT              = 100
PRIMARY_THRESHOLD   = 3.5
SECONDARY_THRESHOLD = 2.0

# --- Adatok lekérése ---
def fetch_data(pair, interval="1h", limit=100):
    url = (
        f"https://api.gateio.ws/api/v4/spot/candlesticks?"
        f"currency_pair={pair}&limit={limit}&interval={interval}"
    )
    try:
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        logging.error(f"{pair} ({interval}) lekérési hiba: {e}")
        return None

    valid = []
    for i, row in enumerate(raw):
        if isinstance(row, list) and len(row) >= 7:
            valid.append(row[:7])
    if not valid:
        logging.error(f"{pair} ({interval}): nincs használható adat.")
        return None

    cols = ["timestamp","volume","close","high","low","open","currency_volume"]
    df = pd.DataFrame(valid, columns=cols)
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"], errors="coerce"), unit="s")
    for c in ["open","high","low","close","volume","currency_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("timestamp").reset_index(drop=True)

# --- RSI és indikátorok ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period, min_periods=1).mean()
    loss = -delta.where(delta < 0, 0).rolling(period, min_periods=1).mean()
    rs = gain / loss
    rs.replace([float('inf'), -float('inf')], pd.NA, inplace=True)
    return 100 - (100 / (1 + rs))

# --- OBV számítása ---
def calculate_obv(df):
    obv = [0]
    for i in range(1, len(df)):
        if df['close'].iloc[i] > df['close'].iloc[i-1]:
            obv.append(obv[-1] + df['volume'].iloc[i])
        elif df['close'].iloc[i] < df['close'].iloc[i-1]:
            obv.append(obv[-1] - df['volume'].iloc[i])
        else:
            obv.append(obv[-1])
    return pd.Series(obv, index=df.index)

# --- Score számítása ---
def calculate_score(df):
    if len(df) < 2:
        return 0
    score = 0
    # EMA trend
    if df['EMA12'].iloc[-1] > df['EMA26'].iloc[-1] > df['EMA26'].iloc[-2]: score += 1
    # MACD friss kereszt
    if df['MACD'].iloc[-1] > df['Signal'].iloc[-1] and df['MACD'].iloc[-2] < df['Signal'].iloc[-2]: score += 1
    # RSI friss áttörés
    if df['RSI'].iloc[-1] > 60 and df['RSI'].iloc[-2] < 60: score += 1
    # Ár-EMA50 távolság 2–3%
    ema50 = df['EMA50'].iloc[-1]; price = df['close'].iloc[-1]
    if ema50 and 2 <= abs((price-ema50)/ema50)*100 <= 3: score += 1
    # Volumen inflow
    if len(df) >= 6:
        inflow = (price - df['open'].iloc[-1]) * df['volume'].iloc[-1]
        avg = ((df['close']-df['open'])*df['volume']).iloc[-6:-1].mean()
        if pd.notna(avg) and inflow > avg: score += 1
    # Smart Money Spike: OBV spike + volumen
    if 'OBV' in df.columns:
        obv_now = df['OBV'].iloc[-1]
        ma_obv = df['OBV'].rolling(10).mean().iloc[-1]
        vol_now = df['volume'].iloc[-1]
        avg_vol = df['volume'].rolling(20).mean().iloc[-1]
        if obv_now > ma_obv and vol_now > 1.5 * avg_vol:
            score += 0.5  # finom plusz pontozás a kitörésre
    return score

# --- Jelzési logika ---
report = []
for pair in PAIRS:
    df30 = fetch_data(pair, interval=PRIMARY_INTERVAL, limit=LIMIT)
    if df30 is None or len(df30) < 50:
        continue
    df30['EMA12'] = df30['close'].ewm(span=12, min_periods=12).mean()
    df30['EMA26'] = df30['close'].ewm(span=26, min_periods=26).mean()
    df30['EMA50'] = df30['close'].ewm(span=50, min_periods=50).mean()
    df30['MACD']   = df30['EMA12'] - df30['EMA26']
    df30['Signal'] = df30['MACD'].ewm(span=9, min_periods=9).mean()
    df30['RSI']    = calculate_rsi(df30['close'])
    df30['OBV']    = calculate_obv(df30)
    score30 = calculate_score(df30.tail(50))
    if score30 < PRIMARY_THRESHOLD:
        continue

    df5 = fetch_data(pair, interval=SECONDARY_INTERVAL, limit=LIMIT)
    if df5 is None or len(df5) < 50:
        continue
    df5['EMA12'] = df5['close'].ewm(span=12, min_periods=12).mean()
    df5['EMA26'] = df5['close'].ewm(span=26, min_periods=26).mean()
    df5['EMA50'] = df5['close'].ewm(span=50, min_periods=50).mean()
    df5['MACD']   = df5['EMA12'] - df5['EMA26']
    df5['Signal'] = df5['MACD'].ewm(span=9, min_periods=9).mean()
    df5['RSI']    = calculate_rsi(df5['close'])
    df5['OBV']    = calculate_obv(df5)
    score5 = calculate_score(df5.tail(50))
    if score5 >= SECONDARY_THRESHOLD:
        report.append((pair, score30, score5))

# --- Jelentés küldése ---
if report:
    msg = "📈 *Bullish jelzések (30m + 5m + OBV spike):*\n\n"
    for pair, s30, s5 in report:
        msg += f"• `{pair}` — 30m: *{s30}*, 5m: *{s5}*\n"
    send_telegram_message(msg)
else:
    logging.info("Nincs belépési jelzés egyik időkereten sem.")

