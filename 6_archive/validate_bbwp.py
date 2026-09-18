import ccxt
import pandas as pd
import numpy as np

exchange = ccxt.binance()
ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=600)
df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
df = df.set_index('datetime')

# --- BBWP Implementation ---
# Settings: SMA basis, length 13, lookback 252, MA SMA 5
basis_len = 13
lookback  = 252
ma_len    = 5

# Step 1: SMA(close, 13)
df['basis'] = df['close'].rolling(basis_len).mean()

# Step 2: BBW = 2 * stdev(close, 13) / SMA(close, 13)
# Pine Script ta.stdev uses population std (ddof=0)
df['bbw'] = 2 * df['close'].rolling(basis_len).std(ddof=0) / df['basis']

# Step 3: BBWP — percentile rank of current BBW among previous 252 BBW values
# Matches Pine Script: calculate BEFORE adding current bar to the window
# (binary_search_rightmost on existing sorted array, then push current value)
bbwp_values = []
for i in range(len(df)):
    bbw_i = df['bbw'].iloc[i]
    if pd.isna(bbw_i) or i < basis_len:
        bbwp_values.append(np.nan)
        continue
    # Previous values only (not current) — same as Pine Script sorted array logic
    start = max(basis_len, i - lookback)
    historical = df['bbw'].iloc[start:i].dropna()
    if len(historical) == 0:
        bbwp_values.append(np.nan)
        continue
    count = (historical <= bbw_i).sum()
    bbwp_values.append(count / len(historical) * 100)

df['bbwp'] = bbwp_values

# Step 4: BBWP MA — SMA(bbwp, 5)
df['bbwp_ma'] = df['bbwp'].rolling(ma_len).mean()

# --- Validate against May 16 16:00 UTC (= 10:00 UTC-6) ---
target = df[df.index.strftime('%Y-%m-%d %H:%M') == '2026-05-16 16:00']

if target.empty:
    print("Target candle not found")
else:
    row = target.iloc[0]
    print("Candle:            2026-05-16 16:00 UTC (= 10:00 UTC-6)")
    print("Close:             $" + f"{row['close']:,.2f}")
    print("BBW:               " + f"{row['bbw']:.6f}")
    print()
    print("BBWP calculated:   " + f"{row['bbwp']:.2f}%")
    print("BBWP TV reference: 67.06%")
    print("Difference:        " + f"{abs(row['bbwp'] - 67.06):.2f}")
    print()
    print("BBWP MA calculated:   " + f"{row['bbwp_ma']:.2f}%")
    print("BBWP MA TV reference: 78.33%")
    print("Difference:           " + f"{abs(row['bbwp_ma'] - 78.33):.2f}")
    print()
    diff_bbwp = abs(row['bbwp'] - 67.06)
    diff_ma   = abs(row['bbwp_ma'] - 78.33)
    if diff_bbwp < 1.0 and diff_ma < 1.0:
        print("MATCH — both BBWP and MA valid.")
    else:
        print("MISMATCH — investigating...")
        # Try with sample std (ddof=1) to compare
        df['bbw_s'] = 2 * df['close'].rolling(basis_len).std(ddof=1) / df['basis']
        bbwp2 = []
        for i in range(len(df)):
            bbw_i = df['bbw_s'].iloc[i]
            if pd.isna(bbw_i) or i < basis_len:
                bbwp2.append(np.nan)
                continue
            start = max(basis_len, i - lookback)
            historical = df['bbw_s'].iloc[start:i].dropna()
            if len(historical) == 0:
                bbwp2.append(np.nan)
                continue
            count = (historical <= bbw_i).sum()
            bbwp2.append(count / len(historical) * 100)
        df['bbwp2'] = bbwp2
        df['bbwp2_ma'] = df['bbwp2'].rolling(ma_len).mean()
        row2 = df[df.index.strftime('%Y-%m-%d %H:%M') == '2026-05-16 16:00'].iloc[0]
        print("With sample std (ddof=1):")
        print("  BBWP: " + f"{row2['bbwp2']:.2f}%  (diff: {abs(row2['bbwp2'] - 67.06):.2f})")
        print("  MA:   " + f"{row2['bbwp2_ma']:.2f}%  (diff: {abs(row2['bbwp2_ma'] - 78.33):.2f})")
