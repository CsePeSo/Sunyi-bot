import time
import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

GATEIO_API = os.getenv("GATEIO_KEY")
GATEIO_SECRET = os.getenv("GATEIO_SECRET")
TG_API_KEY = os.getenv("TG_API_KEY")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# In-memory alert timing storage
last_alert_times = {}

# Simulated price/indicator fetch (replace with real Gate.io API calls)
def fetch_coin_data(pair):
    # Dummy values to simulate conditions
    return {
        "ema_5": 1.01,
        "ema_9": 1.00,
        "ema_12": 0.99,
        "ema_21": 0.98,
        "macd_dif": 0.002,
        "macd_dea": 0.001,
        "obv": [1000, 1100],
        "close": 1.02,
        "psar": 1.00,
        "volume_now": 50000,
        "volume_prev": 30000
    }

def check_bullish_triggers(data):
    triggers = {
        "ema_5_9": data["ema_5"] > data["ema_9"],
        "ema_9_12": data["ema_9"] > data["ema_12"],
        "ema_12_21": data["ema_12"] > data["ema_21"],
        "macd": data["macd_dif"] > data["macd_dea"],
        "obv_up": data["obv"][-1] > data["obv"][-2],
        "psar": data["close"] > data["psar"]
    }
    score = sum(triggers.values())
    return score, triggers

def check_exit_signal(data):
    return (
        data["macd_dif"] < data["macd_dea"] or
        data["obv"][-1] < data["obv"][-2] or
        data["close"] < data["psar"] or
        data["volume_now"] < 0.7 * data["volume_prev"]
    )

def should_send_alert(pair):
    now = datetime.utcnow()
    last = last_alert_times.get(pair)
    if last is None or (now - last > timedelta(minutes=15)):
        last_alert_times[pair] = now
        return True
    return False

def send_telegram_message(msg):
    url = f"https://api.telegram.org/bot{TG_API_KEY}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram error: {e}")

def evaluate_and_alert(pair):
    data = fetch_coin_data(pair)
    score, triggers = check_bullish_triggers(data)
    exit_signal = check_exit_signal(data)

    if score >= 5 and should_send_alert(pair):
        msg = f"[BULLISH ALERT] {pair}\nScore: {score}/6\nTriggers: {triggers}"
        send_telegram_message(msg)
    elif exit_signal:
        msg = f"[EXIT WARNING] {pair} - Trend kifulladhat!"
        send_telegram_message(msg)

def main():
    tracked_pairs = ["SOL_USDT", "TRUMP_USDT", "PEPE_USDT", "XRP_USDT", "PI_USDT"]
    while True:
        for pair in tracked_pairs:
            evaluate_and_alert(pair)
        time.sleep(60)

if __name__ == "__main__":
    send_telegram_message("[INDULÁS] Bullish Alert rendszer aktív.")
    main()
