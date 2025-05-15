import requests
import pandas as pd
import os
import logging

# --- Logging beállítások ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- Környezeti változók ---
TOKEN = os.getenv("TG_API_KEY")
CHAT_ID = os.getenv("TG_CHAT_ID")
GATE_API_KEY = os.getenv("GATEI_KEY")
GATE_SECRET_KEY = os.getenv("GATEI_SECRET")


# --- Telegram üzenet küldése ---
def send_telegram_message(message):
    if not TOKEN or not CHAT_ID:
        logging.warning("Hiányzó Telegram beállítások (TG_API_KEY vagy TG_CHAT_ID)!")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"} # Hozzáadtam a parse_mode-ot a jobb formázásért
    try:
        r = requests.post(url, data=data)
        r.raise_for_status() # Hiba esetén kivételt dob
        logging.info("Telegram üzenet sikeresen elküldve.")
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"Telegram HTTP hiba: {http_err} - Válasz: {r.text}")
    except Exception as e:
        logging.error(f"Telegram hiba: {e}")

# --- Coinpárok ---
PAIRS = ["PI_USDT", "SOL_USDT", "XRP_USDT", "PEPE_USDT", "TRUMP_USDT"]

# --- Üdvözlő üzenet ---
# Ellenőrizzük, hogy a kulcsok léteznek-e, mielőtt bármilyen API hívást indítanánk
if GATE_API_KEY and GATE_SECRET_KEY:
    send_telegram_message("🤖 A több coin figyelő bot elindult!")
else:
    error_message = "A bot nem tud elindulni a hiányzó Gate.io API kulcsok miatt (GATEIO_KEY vagy GATEIO_SECRET). Kérlek, állítsd be őket."
    logging.critical(error_message)
    send_telegram_message(error_message) # Értesítés Telegramon is, ha lehet
    # Fontos lehet itt leállítani a script futását, ha a kulcsok nélkül nem tud működni.
    # exit() vagy raise SystemExit(error_message)

# --- Adatok lekérése ---
def fetch_data(pair):
    if not GATE_API_KEY or not GATE_SECRET_KEY:
        logging.error(f"{pair} lekérés hiba: Hiányzó Gate.io API kulcsok.")
        return None

    url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&limit=30&interval=1h"
    # Fontos: A Gate.io API v4 nem használja a KEY és SECRET headereket így közvetlenül a GET kéréseknél.
    # A hitelesítés általában aláírással történik, ami bonyolultabb.
    # Ha ez egy publikus végpont, akkor nincs szükség header-re.
    # Ha privát, akkor az aláírási mechanizmust kell implementálni.
    # Jelenleg feltételezem, hogy ez a végpont nem igényel hitelesítést, vagy a hiba máshol volt.
    # Ha mégis kell hitelesítés, a requests library nem fogja automatikusan kezelni a 'KEY', 'SECRET' headereket.
    # A hibaüzenet ("Invalid leading whitespace...") a header *értékére* vonatkozott, nem a header nevére.
    # Tehát a tisztítás továbbra is releváns, ha ezeket a kulcsokat máshol használod hitelesítésre.
    
    # Mivel a hiba a header értékében volt, és a Gate.io API kulcsok kerültek bele,
    # a javítás azokra fókuszál. Ha ez a specifikus végpont nem is használja őket headerben,
    # a kulcsok tisztítása akkor is helyes gyakorlat.
    headers = {
        "Accept": "application/json", # Ajánlott header
        # "KEY": GATE_API_KEY, # Ezt a Gate.io v4 GET kérések általában nem így használják
        # "SECRET": GATE_SECRET_KEY # Ezt sem
    }
    try:
        logging.info(f"Adatok lekérése a következőhöz: {pair}")
        r = requests.get(url, headers=headers, timeout=10) # Timeout hozzáadva
        r.raise_for_status() # HTTP hibák elfogása
        data = r.json()
        if not isinstance(data, list) or not all(isinstance(item, list) for item in data):
            logging.error(f"{pair} lekérés hiba: Váratlan adatstruktúra a Gate.io-tól: {data}")
            return None

        columns = ["timestamp", "volume", "close", "high", "low", "open", "currency_volume"] # Gate.io v4 sorrend: t,v,c,h,l,o + currency_volume
        df = pd.DataFrame(data, columns=columns)
        df["timestamp"] = pd.to_numeric(df["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        # Biztosítjuk, hogy a megfelelő oszlopok legyenek numerikusak
        numeric_cols = ["open", "high", "low", "close", "volume", "currency_volume"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce') # errors='coerce' a hibás értékeket NaN-ra cseréli

        df = df.sort_values("timestamp").reset_index(drop=True)
        logging.info(f"Adatok sikeresen feldolgozva: {pair}, sorok száma: {len(df)}")
        return df
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"{pair} lekérés HTTP hiba: {http_err} - URL: {url} - Válasz: {r.text if 'r' in locals() else 'N/A'}")
        return None
    except requests.exceptions.Timeout:
        logging.error(f"{pair} lekérés időtúllépés: {url}")
        return None
    except requests.exceptions.RequestException as req_err:
        logging.error(f"{pair} lekérés hálózati hiba: {req_err} - URL: {url}")
        return None
    except ValueError as json_err: # JSON dekódolási hiba
        logging.error(f"{pair} lekérés JSON dekódolási hiba: {json_err} - Válasz: {r.text if 'r' in locals() else 'N/A'}")
        return None
    except Exception as e:
        logging.error(f"{pair} lekérés általános hiba: {e}")
        return None

# --- RSI számítása ---
def calculate_rsi(series, period=14):
    if not isinstance(series, pd.Series) or series.empty:
        return pd.Series(dtype=float) # Üres Series-t ad vissza, ha a bemenet érvénytelen
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period, min_periods=1).mean() # min_periods=1 hozzáadva
    loss = -delta.where(delta < 0, 0.0).rolling(window=period, min_periods=1).mean() # min_periods=1 hozzáadva
    
    # Kerüljük a nullával való osztást
    rs = gain / loss
    rs = rs.replace([float('inf'), -float('inf')], float('nan')) # Végtelen értékek cseréje NaN-ra

    rsi = 100 - (100 / (1 + rs))
    return rsi

# --- Score számítás ---
def calculate_score(df):
    score = 0
    # Ellenőrizzük, hogy van-e elég adat a számításokhoz
    if len(df) < 2: # Legalább 2 adatpont kell az iloc[-2] működéséhez
        logging.warning("Nem elegendő adat a score számításhoz.")
        return 0

    # 🚀 EMA trend megerősítés
    if df["EMA12"].iloc[-1] > df["EMA26"].iloc[-1] and df["EMA26"].iloc[-1] > df["EMA26"].iloc[-2]:
        score += 1

    # 🚀 MACD keresztvizsgálat
    if df["MACD"].iloc[-1] > df["Signal"].iloc[-1] and df["MACD"].iloc[-2] < df["Signal"].iloc[-2]:
        score += 1

    # 🚀 RSI szűrés
    if df["RSI"].iloc[-1] > 60:
        score += 1

    # 🚀 EMA50 távolságszűrés
    current_price = df["close"].iloc[-1]
    ema50 = df["EMA50"].iloc[-1]
    if ema50 != 0: # Nullával való osztás elkerülése
        distance_pct = abs((current_price - ema50) / ema50) * 100
        if current_price > ema50 and 2 <= distance_pct <= 3:
            score += 1
    else:
        logging.warning("EMA50 értéke nulla, a távolságszűrés kihagyva.")


    # 🚀 Volumen megerősítés
    # Biztosítjuk, hogy van elég adat az átlaghoz (-6:-1 szeleteléshez legalább 6 elem kell)
    if len(df) >= 6:
        inflow = (df["close"].iloc[-1] - df["open"].iloc[-1]) * df["volume"].iloc[-1]
        avg_inflow = ((df["close"] - df["open"]) * df["volume"]).iloc[-6:-1].mean()
        if pd.notna(avg_inflow) and inflow > avg_inflow: # Ellenőrizzük, hogy avg_inflow ne legyen NaN
            score += 1
    else:
        logging.warning("Nem elegendő adat a volumen megerősítéshez (átlaghoz).")

    return round(score, 2)

# --- Coinok értékelése ---
report = []
# Csak akkor fusson a ciklus, ha az API kulcsok rendben vannak
if GATE_API_KEY and GATE_SECRET_KEY:
    for pair in PAIRS:
        logging.info(f"Feldolgozás indul: {pair}")
        df = fetch_data(pair)
        if df is not None and not df.empty and len(df) >= 50: # Növeltem a minimum adatszámot az EMA50 miatt
            try:
                df["EMA12"] = df["close"].ewm(span=12, adjust=False, min_periods=12).mean()
                df["EMA26"] = df["close"].ewm(span=26, adjust=False, min_periods=26).mean()
                df["EMA50"] = df["close"].ewm(span=50, adjust=False, min_periods=50).mean()
                
                # MACD számítás csak ha az EMA-k léteznek
                if "EMA12" in df.columns and "EMA26" in df.columns:
                    df["MACD"] = df["EMA12"] - df["EMA26"]
                    df["Signal"] = df["MACD"].ewm(span=9, adjust=False, min_periods=9).mean()
                else:
                    logging.warning(f"EMA12 vagy EMA26 hiányzik {pair}-hez, MACD kihagyva.")
                    continue # Kihagyja a score számítást, ha nincs MACD

                df["RSI"] = calculate_rsi(df["close"])

                # Csak akkor számolunk score-t, ha minden szükséges oszlop létezik és nem csak NaN értékeket tartalmaznak
                required_cols_for_score = ["EMA12", "EMA26", "EMA50", "MACD", "Signal", "RSI", "close", "open", "volume"]
                if all(col in df.columns for col in required_cols_for_score) and not df[required_cols_for_score].iloc[-1].isnull().any():
                    s = calculate_score(df.tail(50)) # Csak az utolsó 50 adatpontot használjuk a score-hoz, ha az indikátorok is ezek alapján számolódnak
                    if s >= 3.5:
                        report.append((pair, s))
                        logging.info(f"Erős jelzés találva: {pair}, Score: {s}")
                else:
                    logging.warning(f"Nem minden szükséges oszlop áll rendelkezésre vagy NaN értékeket tartalmaznak a score számításhoz {pair}-nél az utolsó sorban.")

            except Exception as e:
                logging.error(f"Hiba {pair} indikátorainak számítása vagy score értékelése közben: {e}")
        elif df is None or df.empty:
            logging.warning(f"Nincs adat, vagy üres DataFrame érkezett {pair}-hez. Kihagyva.")
        else:
            logging.warning(f"Nem elegendő adat ({len(df)} sor) {pair}-hez a megbízható indikátor számításhoz (min 50 szükséges). Kihagyva.")


# --- Jelentés ---
if report:
    ranked = sorted(report, key=lambda x: x[1], reverse=True)
    message = "📈 *Bullish score alapján erős coinok:*\n\n" # Extra sortörés a jobb olvashatóságért
    for pair, sc in ranked:
        message += f"• `{pair}` — score: *{sc}*\n"
    send_telegram_message(message)
    logging.info("Jelentés elküldve Telegramra.")
else:
    # Küldjünk üzenetet akkor is, ha nincs erős jelzés, de a bot futott
    if GATE_API_KEY and GATE_SECRET_KEY: # Csak ha a botnak volt esélye futni
        send_telegram_message("ℹ️ A bot lefutott, de nem talált erős bullish jelzést a figyelt coinok között.")
        logging.info("Nincs erős jelzés, erről üzenet küldve.")

