"""
Fetch BTC research data from 2019-01-01 to now (Binance, public endpoints, no keys).

  1) Funding history of the BTC/USDT:USDT perpetual -> btc_funding_binance.csv
     Binance is used as a proxy for BloFin (the live venue): BloFin only exposes
     a short funding history. The Binance perpetual starts on 2019-09-10, so
     there are no funding rows before that date.
  2) BTC/USDT spot 4H OHLCV -> btc_4h_2019_cache.pkl (same format as the other
     caches: DataFrame indexed by UTC 'dt', columns open/high/low/close/volume).
     The still-forming last candle is dropped.

Existing caches (ohlcv_4h_cache.pkl, btc_1d_*.pkl) are not touched.
"""
import os
import time
import ccxt
import pandas as pd

HERE     = os.path.dirname(os.path.abspath(__file__))
SINCE    = '2019-01-01T00:00:00Z'
BAR_MS   = 4 * 3600 * 1000

exchange = ccxt.binance()
since_ms = exchange.parse8601(SINCE)
now_ms   = exchange.milliseconds()

# -- 1) FUNDING ----------------------------------------------------------------

print("Fetching BTC/USDT:USDT funding history...")
rows, cursor = [], since_ms
while cursor < now_ms:
    batch = exchange.fetch_funding_rate_history('BTC/USDT:USDT', since=cursor, limit=1000)
    if not batch:
        break
    rows.extend(batch)
    cursor = batch[-1]['timestamp'] + 1
    if len(batch) < 1000:
        break
    time.sleep(exchange.rateLimit / 1000)

fund = pd.DataFrame({
    'timestamp_ms': [r['timestamp'] for r in rows],
    'funding_rate': [r['fundingRate'] for r in rows],
    'mark_price':   [r['info'].get('markPrice') or None for r in rows],
})
fund = fund.drop_duplicates('timestamp_ms').sort_values('timestamp_ms').reset_index(drop=True)
fund_dt = pd.to_datetime(fund['timestamp_ms'], unit='ms', utc=True)
fund.insert(1, 'datetime_utc', fund_dt.dt.floor('s').dt.strftime('%Y-%m-%d %H:%M:%S'))   # exact ms kept in timestamp_ms
fund['mark_price'] = pd.to_numeric(fund['mark_price'])
fund.to_csv(os.path.join(HERE, 'btc_funding_binance.csv'), index=False)

hours = fund_dt.dt.floor('h').dt.hour.value_counts().sort_index()
print(f"  {len(fund)} rows  {fund_dt.iloc[0]} -> {fund_dt.iloc[-1]}")
print(f"  settlement hours (UTC, floored): {hours.to_dict()}")

# -- 2) 4H OHLCV ---------------------------------------------------------------

print("Fetching BTC/USDT 4H spot...")
candles, cursor = [], since_ms
while True:
    batch = exchange.fetch_ohlcv('BTC/USDT', '4h', since=cursor, limit=1000)
    if not batch:
        break
    candles.extend(batch)
    cursor = batch[-1][0] + 1
    if len(batch) < 1000:
        break

df = pd.DataFrame(candles, columns=['ts','open','high','low','close','volume'])
df = df.drop_duplicates('ts')
df = df[df['ts'] + BAR_MS <= now_ms]                 # drop the still-forming candle
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts').sort_index()
df.to_pickle(os.path.join(HERE, 'btc_4h_2019_cache.pkl'))

expected = int((df.index[-1] - df.index[0]) / pd.Timedelta(hours=4)) + 1
print(f"  {len(df)} candles  {df.index[0]} -> {df.index[-1]}  (missing vs continuous grid: {expected - len(df)})")
