import ccxt
import pandas as pd
import numpy as np

exchange = ccxt.binance()
ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=600)
df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
df = df.set_index('datetime')
df['ema13'] = df['close'].ewm(span=13, adjust=False).mean()
df['pmar'] = (df['close'] / df['ema13']).abs()

pmarp_values = []
for i in range(len(df)):
    if i < 300:
        pmarp_values.append(float('nan'))
    else:
        hist = df['pmar'].iloc[i-300:i]
        pmarp_values.append((hist <= df['pmar'].iloc[i]).sum() / 300 * 100)
df['pmarp'] = pmarp_values

# May 13, 10:00 UTC-6 = 16:00 UTC
target = df[df.index.strftime('%Y-%m-%d %H:%M') == '2026-05-13 16:00']
if target.empty:
    print('Candle not found')
else:
    row = target.iloc[0]
    print("Candle: 2026-05-13 16:00-17:00 UTC (= 10:00-11:00 UTC-6)")
    print("Close:  $" + f"{row['close']:,.2f}")
    print("PMARP:  " + f"{row['pmarp']:.2f}")
