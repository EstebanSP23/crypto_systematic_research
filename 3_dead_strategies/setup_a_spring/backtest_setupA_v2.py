"""
SETUP A v2 — Compression Breakout multi-asset scanner
Tests THREE score thresholds in one run: 5, 6, 7.
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ASSETS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT',
    'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'NEAR/USDT', 'MATIC/USDT', 'ATOM/USDT',
    'ARB/USDT', 'OP/USDT', 'APT/USDT', 'SUI/USDT',
    'LTC/USDT', 'ADA/USDT', 'TIA/USDT', 'SEI/USDT', 'FET/USDT',
]
INITIAL_CAPITAL = 1839.17
RISK_PCT        = 0.02
MAX_POSITIONS   = 3

exchange = ccxt.binance()
since = exchange.parse8601('2023-01-01T00:00:00Z')

def fetch_full(symbol, timeframe, since_ms, exchange):
    all_candles = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        all_candles.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return all_candles

print("Fetching daily data for 18 assets...")
data = {}
for asset in ASSETS:
    try:
        raw = fetch_full(asset, '1d', since, exchange)
        if not raw or len(raw) < 220:
            continue
        df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
        df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        df = df.set_index('dt').drop(columns='ts').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        data[asset] = df
    except Exception:
        pass
print(f"Loaded {len(data)} assets.")

print("Computing indicators...")
def compute_indicators(df):
    df = df.copy()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    df['ema20']  = df['close'].ewm(span=20, adjust=False).mean()

    prev_close = df['close'].shift(1)
    tr = pd.concat([df['high']-df['low'], (df['high']-prev_close).abs(), (df['low']-prev_close).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()

    basis = df['close'].rolling(13).mean()
    df['bbw'] = 2 * df['close'].rolling(13).std(ddof=0) / basis
    bbw_arr = df['bbw'].values
    bbwp = np.full(len(df), np.nan)
    for i in range(13, len(df)):
        start = max(13, i - 252)
        h = bbw_arr[start:i]
        valid = h[~np.isnan(h)]
        if len(valid) > 0:
            bbwp[i] = np.sum(valid <= bbw_arr[i]) / len(valid) * 100
    df['bbwp'] = bbwp

    df['vol_sma20'] = df['volume'].rolling(20).mean()
    df['high_20']   = df['high'].rolling(20).max().shift(1)
    df['low_14']    = df['low'].rolling(14).min().shift(1)
    return df

for asset in list(data.keys()):
    data[asset] = compute_indicators(data[asset])

def score_setup(df, i):
    """Relaxed scoring system. Returns total 0-10."""
    if i < 200: return 0
    if pd.isna(df['bbwp'].iloc[i]) or pd.isna(df['sma200'].iloc[i]) or pd.isna(df['high_20'].iloc[i]):
        return 0

    score = 0
    bbwp = df['bbwp'].iloc[i]
    close = df['close'].iloc[i]
    sma50 = df['sma50'].iloc[i]
    sma200 = df['sma200'].iloc[i]

    # COMPRESSION (0-3)
    if bbwp < 30:  score += 1
    if bbwp < 15:  score += 1                                    # extra for extreme
    atr_slice = df['atr14'].iloc[i-5:i+1].values
    if not np.isnan(atr_slice).any():
        if all(atr_slice[j] <= atr_slice[j-1] for j in range(1, len(atr_slice))):
            score += 1

    # TREND (0-4)
    if close > sma50: score += 1
    if sma50 > sma200: score += 1
    if i >= 20 and not pd.isna(df['sma50'].iloc[i-20]):
        if sma50 > df['sma50'].iloc[i-20]: score += 1
    ath = df['high'].iloc[:i+1].max()
    if close / ath > 0.80: score += 1

    # BREAKOUT (0-3) — REQUIRES breakout to score any
    if close > df['high_20'].iloc[i]:
        score += 1
        if not pd.isna(df['vol_sma20'].iloc[i]) and df['volume'].iloc[i] > df['vol_sma20'].iloc[i] * 1.5:
            score += 1
        bar_range = df['high'].iloc[i] - df['low'].iloc[i]
        if bar_range > 0 and (close - df['low'].iloc[i]) / bar_range > 0.7:
            score += 1

    return score

def run_backtest(threshold):
    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    account = INITIAL_CAPITAL
    positions = {}
    trades = []
    eq = []

    for date in all_dates:
        # Manage open positions
        for sym in list(positions.keys()):
            if date not in data[sym].index: continue
            df = data[sym]
            idx = df.index.get_loc(date)
            high, low = df['high'].iloc[idx], df['low'].iloc[idx]
            pos = positions[sym]

            if low <= pos['stop_price']:
                exit_px = pos['stop_price']
                size    = pos['size'] * pos['size_remaining']
                exit_pnl = (exit_px - pos['entry_price']) * size
                total_pnl = exit_pnl + pos.get('partial_pnl', 0)
                account += exit_pnl
                trades.append({
                    'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': date,
                    'entry_price': pos['entry_price'], 'exit_price': exit_px,
                    'pnl_usd': total_pnl, 'pnl_pct': total_pnl/pos['acct_at_entry']*100,
                    'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
                    'exit_reason': 'trailing_stop' if pos.get('scaled_out') else 'stop_loss',
                    'duration_days': (date - pos['entry_date']).days,
                    'score': pos['score'], 'account': account,
                })
                del positions[sym]
                continue

            if not pos.get('scaled_out') and high >= pos['first_target']:
                partial_size = pos['size'] * 0.5
                partial_pnl  = (pos['first_target'] - pos['entry_price']) * partial_size
                account     += partial_pnl
                pos['partial_pnl'] = partial_pnl
                pos['size_remaining'] = 0.5
                pos['stop_price'] = pos['entry_price']
                pos['scaled_out'] = True

            if pos.get('scaled_out'):
                low_8 = df['low'].iloc[max(0, idx-8):idx].min()
                ema20 = df['ema20'].iloc[idx]
                trailing = max(low_8, ema20) if not pd.isna(ema20) else low_8
                if trailing > pos['stop_price']:
                    pos['stop_price'] = trailing

        # New entries
        if len(positions) < MAX_POSITIONS:
            candidates = []
            for sym, df in data.items():
                if sym in positions or date not in df.index: continue
                idx = df.index.get_loc(date)
                sc = score_setup(df, idx)
                if sc >= threshold:
                    candidates.append((sym, idx, sc))
            candidates.sort(key=lambda x: -x[2])

            for sym, idx, sc in candidates:
                if len(positions) >= MAX_POSITIONS: break
                df = data[sym]
                if idx + 1 >= len(df): continue
                entry_price = df['open'].iloc[idx+1]
                atr = df['atr14'].iloc[idx]
                consol_low = df['low_14'].iloc[idx]
                stop_2atr = entry_price - 2 * atr
                stop_price = max(stop_2atr, consol_low) if not pd.isna(consol_low) else stop_2atr
                if stop_price >= entry_price or pd.isna(stop_price): continue
                stop_distance = entry_price - stop_price
                size = (account * RISK_PCT) / stop_distance
                first_target = entry_price + 2 * stop_distance
                positions[sym] = {
                    'entry_date': df.index[idx+1], 'entry_price': entry_price,
                    'stop_price': stop_price, 'first_target': first_target,
                    'size': size, 'size_remaining': 1.0, 'acct_at_entry': account,
                    'score': sc, 'partial_pnl': 0,
                }

        eq.append({'date': date, 'equity': account})

    # Close at end
    for sym, pos in positions.items():
        df = data[sym]
        last_close = df['close'].iloc[-1]
        size = pos['size'] * pos['size_remaining']
        exit_pnl = (last_close - pos['entry_price']) * size
        total_pnl = exit_pnl + pos.get('partial_pnl', 0)
        account += exit_pnl
        trades.append({
            'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': data[sym].index[-1],
            'entry_price': pos['entry_price'], 'exit_price': last_close,
            'pnl_usd': total_pnl, 'pnl_pct': total_pnl/pos['acct_at_entry']*100,
            'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
            'exit_reason': 'open_at_end',
            'duration_days': (data[sym].index[-1] - pos['entry_date']).days,
            'score': pos['score'], 'account': account,
        })
    return trades, account, pd.DataFrame(eq).set_index('date')

# Run 3 thresholds
results = {}
for t in [5, 6, 7]:
    print(f"\nThreshold ≥ {t}...")
    trades, final, eq = run_backtest(t)
    df_t = pd.DataFrame(trades)
    if len(df_t) > 0:
        df_t['win'] = df_t['R'] > 0
        df_t['entry_date'] = pd.to_datetime(df_t['entry_date'])
        df_t['exit_date']  = pd.to_datetime(df_t['exit_date'])
    results[t] = {'trades': df_t, 'final': final, 'eq': eq}
    print(f"  Trades: {len(df_t)}  Final: ${final:,.2f}  Return: {(final/INITIAL_CAPITAL-1)*100:+.1f}%")

# Print comparison
sep = "─" * 100
print(f"\n{'═'*100}")
print(f"  SETUP A — Compression Breakout — 18-asset crypto universe   Jan 2023 → today")
print(f"{'═'*100}")
print(f"  {'Threshold':<12}{'Trades':>8}{'Win %':>8}{'Avg win R':>12}{'Avg loss R':>12}{'Exp R':>10}{'Max DD %':>10}{'Final $':>12}{'Return %':>10}")
print(sep)

for t in [5, 6, 7]:
    r = results[t]['trades']
    final = results[t]['final']
    eq = results[t]['eq']
    if len(r) == 0:
        print(f"  ≥ {t}         No trades")
        continue
    wins, losses = r[r['win']], r[~r['win']]
    peak = INITIAL_CAPITAL; mdd = 0
    for v in [INITIAL_CAPITAL] + list(eq['equity']):
        if v > peak: peak = v
        d = (v-peak)/peak*100
        if d < mdd: mdd = d
    aw = wins['R'].mean() if len(wins) else 0
    al = losses['R'].mean() if len(losses) else 0
    print(f"  ≥ {t}         {len(r):>8}{len(wins)/len(r)*100:>7.1f}%{aw:>+12.2f}{al:>+12.2f}{r['R'].mean():>+10.3f}{mdd:>+10.2f}{final:>12,.2f}{(final/INITIAL_CAPITAL-1)*100:>+10.1f}")

# Show top performing variant in detail
best_t = max([(t, results[t]['final']) for t in [5,6,7]], key=lambda x: x[1])[0]
r = results[best_t]['trades']
print(f"\n{sep}\n  DETAILED RESULTS — BEST VARIANT (threshold ≥ {best_t})\n{sep}")

if len(r) > 0:
    print(f"  PER-ASSET BREAKDOWN")
    print(f"  {'Asset':<12}{'Trades':>8}{'Win%':>8}{'Avg R':>10}{'Total $':>14}")
    for sym, grp in r.groupby('symbol'):
        wr = len(grp[grp['win']])/len(grp)*100
        ar = grp['R'].mean()
        tot = grp['pnl_usd'].sum()
        print(f"  {sym:<12}{len(grp):>8}{wr:>7.1f}%{ar:>+10.2f}{tot:>+14,.2f}")

    print(f"\n  YEAR-BY-YEAR")
    r['year'] = r['exit_date'].dt.year
    print(f"  {'Year':<8}{'Trades':>8}{'Win%':>8}{'Avg R':>10}{'PnL $':>14}")
    for yr, grp in r.groupby('year'):
        wr = len(grp[grp['win']])/len(grp)*100
        ar = grp['R'].mean()
        tot = grp['pnl_usd'].sum()
        print(f"  {yr:<8}{len(grp):>8}{wr:>7.1f}%{ar:>+10.2f}{tot:>+14,.2f}")

    print(f"\n  EXIT REASONS")
    for reason, cnt in r['exit_reason'].value_counts().items():
        grp = r[r['exit_reason']==reason]
        wr = len(grp[grp['win']])/len(grp)*100
        ar = grp['R'].mean()
        print(f"    {reason:<20} {cnt:>4} trades  {wr:>5.1f}% win  avg R: {ar:+.3f}")

# Chart
fig, ax = plt.subplots(figsize=(15, 7))
colors = {5: '#9467bd', 6: '#2ca02c', 7: '#ff7f0e'}
for t in [5, 6, 7]:
    eq = results[t]['eq']
    final = results[t]['final']
    n = len(results[t]['trades'])
    if len(eq) > 0:
        ax.plot(eq.index, eq['equity'], label=f"Threshold ≥ {t}  ({(final/INITIAL_CAPITAL-1)*100:+.0f}%, {n} trades)",
                color=colors[t], linewidth=1.4)
ax.axhline(INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.5)
ax.set_ylabel('Account ($)')
ax.set_title('Setup A — Compression Breakout — Threshold Comparison', fontweight='bold')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
plt.tight_layout()
plt.savefig('setupA_v2.png', dpi=120, bbox_inches='tight')
print(f"\nChart -> setupA_v2.png")
