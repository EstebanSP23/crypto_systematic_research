import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# Fetch 1H BTC candles from Binance (public, no auth needed)
exchange = ccxt.binance()

# Fetch 600 candles to ensure enough warmup for EMA(13) + 300 lookback
ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=600)
df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
df = df.set_index('datetime')

# --- PMARP Implementation ---
# Step 1: EMA(close, 13) — matches Pine Script ta.ema()
df['ema13'] = df['close'].ewm(span=13, adjust=False).mean()

# Step 2: PMAR = abs(close / EMA(close, 13))
df['pmar'] = (df['close'] / df['ema13']).abs()

# Step 3: PMARP = percentile rank of current PMAR among previous 300 bars
# Pine Script loop: for i = 1 to 300 — excludes current bar (i=0)
lookback = 300
pmarp_values = []
for i in range(len(df)):
    if i < lookback:
        pmarp_values.append(np.nan)
    else:
        historical = df['pmar'].iloc[i - lookback:i]  # 300 bars BEFORE current, not including current
        current = df['pmar'].iloc[i]
        rank = (historical <= current).sum() / lookback * 100
        pmarp_values.append(rank)

df['pmarp'] = pmarp_values

# --- Find the target candle: close at 17:00 UTC (= 11:00 UTC-6) on May 16, 2026 ---
# Binance candle open_time: candle that opens at 16:00 UTC closes at 17:00 UTC
target = df[df.index.strftime('%Y-%m-%d %H:%M') == '2026-05-16 16:00']

if target.empty:
    print("Target candle not found. Available last 5 candles:")
    print(df[['close', 'pmar', 'pmarp']].tail())
else:
    row = target.iloc[0]
    print(f"Candle:    2026-05-16 16:00-17:00 UTC  (= 10:00-11:00 UTC-6)")
    print(f"Close:     ${row['close']:,.2f}")
    print(f"EMA(13):   ${row['ema13']:,.2f}")
    print(f"PMAR:      {row['pmar']:.6f}")
    print(f"PMARP:     {row['pmarp']:.2f}")
    print()
    print(f"TradingView reference: 36.67")
    print(f"My calculation:        {row['pmarp']:.2f}")
    diff = abs(row['pmarp'] - 36.67)
    print(f"Difference:            {diff:.2f}")
    if diff < 1.0:
        print("MATCH — implementation is valid.")
    else:
        print("MISMATCH — needs investigation.")
