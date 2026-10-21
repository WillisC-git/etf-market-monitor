
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

SYMBOLS = ["GLD", "SLV", "IBIT"]

key = os.environ.get("ALPACA_API_KEY_ID")
secret = os.environ.get("ALPACA_SECRET_KEY")

if not key or not secret:
    raise RuntimeError("Missing Alpaca API credentials")

end = datetime.now(timezone.utc) + timedelta(days=1)
start = end - timedelta(days=15)

params = urllib.parse.urlencode({
    "symbols": ",".join(SYMBOLS),
    "timeframe": "1Day",
    "start": start.strftime("%Y-%m-%dT00:00:00Z"),
    "end": end.strftime("%Y-%m-%dT00:00:00Z"),
    "feed": os.environ.get("ALPACA_FEED", "iex"),
    "limit": 1000
})

url = "https://data.alpaca.markets/v2/stocks/bars?" + params

request = urllib.request.Request(url, headers={
    "APCA-API-KEY-ID": key,
    "APCA-API-SECRET-KEY": secret
})

with urllib.request.urlopen(request, timeout=30) as response:
    data = json.load(response)

bars = data.get("bars", {})

for symbol in SYMBOLS:
    records = bars.get(symbol, [])
    if not records:
        print(f"{symbol}: No data returned")
        continue

    last = records[-1]
    print(
        f"{symbol} | Date: {last['t']} | "
        f"Close: ${last['c']:.2f} | "
        f"Volume: {last['v']:,}"
    )

if not all(bars.get(s) for s in SYMBOLS):
    raise RuntimeError("One or more symbols returned no bars")

print("Alpaca API test completed successfully.")
