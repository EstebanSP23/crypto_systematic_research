"""
Fetch BTC/USDT spot 4H OHLCV from Binance's first candle (2017-08-17) to now
-> btc_4h_2017_cache.pkl (DataFrame indexed by UTC 'dt', columns open/high/low/close/volume).
The still-forming last candle is dropped. Other caches are not touched.
"""
import os
import ccxt
import pandas as pd

HERE   = os.path.dirname(os.path.abspath(__file__))
BAR_MS = 4 * 3600 * 1000

exchange = ccxt.binance()
cursor   = exchange.parse8601('2017-08-17T00:00:00Z')
now_ms   = exchange.milliseconds()

print("Fetching BTC/USDT 4H spot from 2017-08-17...")
candles = []
while True:
    batch = exchange.fetch_ohlcv('BTC/USDT', '4h', since=cursor, limit=1000)
    if not batch:
        break
    candles.extend(batch)
    cursor = batch[-1][0] + 1
    if len(batch) < 1000:
        break

df = pd.DataFrame(candles, columns=['ts','open','high','low','close','volume']).drop_duplicates('ts')
df = df[df['ts'] + BAR_MS <= now_ms]                 # drop the still-forming candle
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts').sort_index()
df.to_pickle(os.path.join(HERE, 'btc_4h_2017_cache.pkl'))

gaps = df.index.to_series().diff()
gaps = gaps[gaps > pd.Timedelta(hours=4)]
expected = int((df.index[-1] - df.index[0]) / pd.Timedelta(hours=4)) + 1
print(f"  {len(df)} candles  {df.index[0]} -> {df.index[-1]}  (missing vs continuous grid: {expected - len(df)})")
for t, g in gaps.items():
    print(f"    gap before {t}: {g}")
