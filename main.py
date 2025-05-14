import requests

API_URL = "https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=PI_USDT&limit=5&interval=1h"

response = requests.get(API_URL)
print(response.json())  # Kiírja az API által visszaadott adatokat
