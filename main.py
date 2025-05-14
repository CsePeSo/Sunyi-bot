import requests
import pandas as pd
import os

# 🚀 API és Telegram beállítások (Render környezeti változókból)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GATE_API_KEY = os.getenv("GATE_API_KEY")
GATE_SECRET_KEY = os.getenv("GATE_SECRET_KEY")

# 🚀 Gate.io API URL
API_URL = "https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=PI_USDT&limit=100&interval=1h"

# 🚀 Telegram értesítés küldése
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, data=data)

# 🚀 Deploy sikeres értesítés
send_telegram_message("✅ Kereskedési rendszer sikeresen elindult!")

# 🚀 Gate.io API adatlekérés és numerikus konverzió
def fetch_gateio_data():
    """Lekéri az aktuális árfolyamokat a Gate.io API-ról és konvertálja numerikus értékekre"""
    headers = {"KEY": GATE_API_KEY, "SECRET": GATE_SECRET_KEY}
    response = requests.get(API_URL, headers=headers)
    data = response.json()

    # Alakítsuk át pandas DataFrame-mé a teljes JSON struktúra alapján
    df = pd.DataFrame(data)

    # Kiírjuk az oszlopokat teszteléshez
    print("📊 API által küldött oszlopok:", df.columns)

    # 🚀 Konvertáljuk az árfolyamokat numerikus formába
    numeric_columns = ["open", "high", "low", "close", "volume"]
    df[numeric_columns] = df[numeric_columns].astype(float)

    return df

# 🚀 Piaci adatok beolvasása dinamikus oszlopkezeléssel
market_data = fetch_gateio_data()

# 🚀 EMA indikátorok számítása
market_data['EMA12'] = market_data['close'].ewm(span=12, adjust=False).mean()
market_data['EMA26'] = market_data['close'].ewm(span=26, adjust=False).mean()
market_data['EMA50'] = market_data['close'].ewm(span=50, adjust=False).mean()

# 🚀 MACD indikátor
market_data['MACD'] = market_data['EMA12'] - market_data['EMA26']
market_data['Signal'] = market_data['MACD'].ewm(span=9, adjust=False).mean()

# 🚀 RSI indikátor (numerikus konverzió beépítve)
def calculate_rsi(data, period=14):
    data = data.astype(float)  # 🚀 Biztosan numerikus értékek lesznek
    delta = data.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

market_data['RSI'] = calculate_rsi(market_data['close'])

# 🚀 Bollinger Bands számítása
market_data['BB_Middle'] = market_data['close'].rolling(window=20).mean()
market_data['BB_Upper'] = market_data['BB_Middle'] + (market_data['close'].rolling(window=20).std() * 2)
market_data['BB_Lower'] = market_data['BB_Middle'] - (market_data['close'].rolling(window=20).std() * 2)

# 🚀 Jelzések beállítása
buy_signal = (market_data['EMA12'] > market_data['EMA26']) & (market_data['RSI'] > 50) & (market_data['MACD'] > market_data['Signal'])
sell_signal = (market_data['EMA12'] < market_data['EMA26']) & (market_data['RSI'] < 50) & (market_data['MACD'] < market_data['Signal'])

# 🚀 Ha jelzés van, küldjük Telegramra
if buy_signal.iloc[-1]:  
    send_telegram_message("🚀 Vételi jel! Az indikátorok bullish jelet mutatnak.")
elif sell_signal.iloc[-1]:  
    send_telegram_message("🔻 Eladási jel! Az indikátorok bearish jelet mutatnak.")
