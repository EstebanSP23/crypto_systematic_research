"""
SETUP A — Compression Breakout — multi-asset daily scanner backtest.

Universe: 18 liquid crypto pairs
Period: Jan 2023 → May 2026 (≈ 40 months; newer coins have less history)
Capital: $1,839 starting
Risk: 2% per trade
Max concurrent positions: 3
Score threshold: 8 of 10

SCORING (0-10):
  Compression (0-4):
    +2 if BBWP < 15  (else +1 if BBWP < 25)
    +1 if 14-bar range < 8% of price
    +1 if ATR(14) contracting for 7+ consecutive bars

  Trend (0-3):
    +1 if close > 50 SMA > 200 SMA
    +1 if 50 SMA slope positive over 20 days
    +1 if price within 15% of all-time high

  Breakout (0-3) — REQUIRES close > 20-day high to score any:
    +1 close > 20-day high
    +1 volume > 1.5× 20-day avg
    +1 close in top 30% of bar's range

POSITION MANAGEMENT:
  Entry:    next bar's open after signal
  Stop:     max( entry - 2*ATR , consolidation low )  — whichever is tighter
  Target:  2R first scale-out (50%), stop moves to breakeven
  Trail:   remaining 50% with max(8-day low, 20 EMA)
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ── UNIVERSE & SETTINGS ──────────────────────────────────────────────────────

ASSETS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT',
    'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'NEAR/USDT', 'MATIC/USDT', 'ATOM/USDT',
    'ARB/USDT', 'OP/USDT', 'APT/USDT', 'SUI/USDT',
    'LTC/USDT', 'ADA/USDT',
    'TIA/USDT', 'SEI/USDT', 'FET/USDT',
]

INITIAL_CAPITAL  = 1839.17
RISK_PCT         = 0.02
MAX_POSITIONS    = 3
SCORE_THRESHOLD  = 8

# ── DATA FETCH ───────────────────────────────────────────────────────────────

exchange = ccxt.binance()
since    = exchange.parse8601('2023-01-01T00:00:00Z')

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
            print(f"  {asset:<12}: skipped ({len(raw) if raw else 0} bars)")
            continue
        df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
        df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        df = df.set_index('dt').drop(columns='ts').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        data[asset] = df
        print(f"  {asset:<12}: {len(df):>4} bars from {df.index[0].date()} → {df.index[-1].date()}")
    except Exception as e:
        print(f"  {asset:<12}: FAILED — {e}")

print(f"\nLoaded {len(data)} assets.")

# ── INDICATORS ───────────────────────────────────────────────────────────────

print("Computing indicators...")
def compute_indicators(df):
    df = df.copy()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    df['ema20']  = df['close'].ewm(span=20, adjust=False).mean()

    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low']  - prev_close).abs(),
    ], axis=1).max(axis=1)
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
    df['high_14']   = df['high'].rolling(14).max().shift(1)
    return df

for asset in list(data.keys()):
    data[asset] = compute_indicators(data[asset])

# ── SCORING ──────────────────────────────────────────────────────────────────

def score_setup(df, i):
    """Returns (total_score, breakdown_dict). 0 if invalid."""
    if i < 200: return 0, {}
    if pd.isna(df['bbwp'].iloc[i]) or pd.isna(df['sma200'].iloc[i]):
        return 0, {}

    breakdown = {}
    score = 0

    # COMPRESSION (0-4)
    bbwp = df['bbwp'].iloc[i]
    if bbwp < 15: score += 2; breakdown['bbwp'] = 2
    elif bbwp < 25: score += 1; breakdown['bbwp'] = 1
    else: breakdown['bbwp'] = 0

    range_14 = (df['high'].iloc[i-14:i].max() - df['low'].iloc[i-14:i].min()) / df['close'].iloc[i]
    if range_14 < 0.08: score += 1; breakdown['range'] = 1
    else: breakdown['range'] = 0

    atr_slice = df['atr14'].iloc[i-7:i+1].values
    if not np.isnan(atr_slice).any():
        if all(atr_slice[j] <= atr_slice[j-1] for j in range(1, len(atr_slice))):
            score += 1; breakdown['atr_contract'] = 1
        else: breakdown['atr_contract'] = 0

    # TREND (0-3)
    close, sma50, sma200 = df['close'].iloc[i], df['sma50'].iloc[i], df['sma200'].iloc[i]
    if close > sma50 > sma200: score += 1; breakdown['trend_align'] = 1
    else: breakdown['trend_align'] = 0

    if i >= 20 and not pd.isna(df['sma50'].iloc[i-20]):
        if sma50 > df['sma50'].iloc[i-20]:
            score += 1; breakdown['sma50_rising'] = 1
        else: breakdown['sma50_rising'] = 0

    ath = df['high'].iloc[:i+1].max()
    if close / ath > 0.85:
        score += 1; breakdown['near_ath'] = 1
    else: breakdown['near_ath'] = 0

    # BREAKOUT (0-3)
    if pd.isna(df['high_20'].iloc[i]):
        return score, breakdown

    if close > df['high_20'].iloc[i]:
        score += 1; breakdown['breakout'] = 1
        if not pd.isna(df['vol_sma20'].iloc[i]) and df['volume'].iloc[i] > df['vol_sma20'].iloc[i] * 1.5:
            score += 1; breakdown['volume'] = 1
        else: breakdown['volume'] = 0
        bar_range = df['high'].iloc[i] - df['low'].iloc[i]
        if bar_range > 0 and (close - df['low'].iloc[i]) / bar_range > 0.7:
            score += 1; breakdown['close_strong'] = 1
        else: breakdown['close_strong'] = 0
    else:
        breakdown['breakout'] = 0; breakdown['volume'] = 0; breakdown['close_strong'] = 0

    return score, breakdown

# ── BACKTEST ENGINE ──────────────────────────────────────────────────────────

print("\nRunning cross-asset backtest...")

# All dates across all assets
all_dates = sorted(set().union(*[df.index for df in data.values()]))

account = INITIAL_CAPITAL
positions = {}
trades = []
equity_history = []

for date in all_dates:
    # 1. Manage existing positions
    for sym in list(positions.keys()):
        if date not in data[sym].index:
            continue
        df = data[sym]
        idx = df.index.get_loc(date)
        high = df['high'].iloc[idx]
        low  = df['low'].iloc[idx]
        pos = positions[sym]

        # Check stop hit (intrabar via low)
        if low <= pos['stop_price']:
            exit_px = pos['stop_price']
            size    = pos['size'] * pos['size_remaining']
            exit_pnl = (exit_px - pos['entry_price']) * size
            total_pnl = exit_pnl + pos.get('partial_pnl', 0)
            account += exit_pnl
            trades.append({
                'symbol': sym,
                'entry_date': pos['entry_date'], 'exit_date': date,
                'entry_price': pos['entry_price'], 'exit_price': exit_px,
                'pnl_usd': total_pnl,
                'pnl_pct': total_pnl / pos['acct_at_entry'] * 100,
                'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
                'exit_reason': 'trailing_stop' if pos.get('scaled_out') else 'stop_loss',
                'duration_days': (date - pos['entry_date']).days,
                'score': pos['score'],
                'account': account,
            })
            del positions[sym]
            continue

        # Check 2R target (50% scale-out)
        if not pos.get('scaled_out') and high >= pos['first_target']:
            partial_size  = pos['size'] * 0.5
            partial_pnl   = (pos['first_target'] - pos['entry_price']) * partial_size
            account      += partial_pnl
            pos['partial_pnl'] = partial_pnl
            pos['size_remaining'] = 0.5
            pos['stop_price'] = pos['entry_price']     # breakeven
            pos['scaled_out'] = True

        # Trail stop on remaining half
        if pos.get('scaled_out'):
            low_8 = df['low'].iloc[max(0, idx-8):idx].min()
            ema20 = df['ema20'].iloc[idx]
            trailing = max(low_8, ema20) if not pd.isna(ema20) else low_8
            if trailing > pos['stop_price']:
                pos['stop_price'] = trailing

    # 2. Look for new entries
    if len(positions) < MAX_POSITIONS:
        candidates = []
        for sym, df in data.items():
            if sym in positions or date not in df.index:
                continue
            idx = df.index.get_loc(date)
            score, brk = score_setup(df, idx)
            if score >= SCORE_THRESHOLD:
                candidates.append((sym, idx, score, brk))
        candidates.sort(key=lambda x: -x[2])

        for sym, idx, score, brk in candidates:
            if len(positions) >= MAX_POSITIONS: break
            df = data[sym]
            if idx + 1 >= len(df): continue
            entry_price = df['open'].iloc[idx + 1]
            atr = df['atr14'].iloc[idx]
            consol_low = df['low_14'].iloc[idx]
            stop_2atr  = entry_price - 2 * atr
            stop_price = max(stop_2atr, consol_low) if not pd.isna(consol_low) else stop_2atr
            if stop_price >= entry_price or pd.isna(stop_price):
                continue
            stop_distance = entry_price - stop_price
            risk_amt = account * RISK_PCT
            size = risk_amt / stop_distance
            first_target = entry_price + 2 * stop_distance
            positions[sym] = {
                'entry_date': df.index[idx + 1],
                'entry_price': entry_price,
                'stop_price': stop_price,
                'first_target': first_target,
                'size': size,
                'size_remaining': 1.0,
                'acct_at_entry': account,
                'score': score,
                'partial_pnl': 0,
            }

    equity_history.append({'date': date, 'equity': account, 'open_positions': len(positions)})

# Close any open positions at end
for sym, pos in positions.items():
    df = data[sym]
    last_close = df['close'].iloc[-1]
    size = pos['size'] * pos['size_remaining']
    exit_pnl  = (last_close - pos['entry_price']) * size
    total_pnl = exit_pnl + pos.get('partial_pnl', 0)
    account += exit_pnl
    trades.append({
        'symbol': sym,
        'entry_date': pos['entry_date'], 'exit_date': data[sym].index[-1],
        'entry_price': pos['entry_price'], 'exit_price': last_close,
        'pnl_usd': total_pnl,
        'pnl_pct': total_pnl / pos['acct_at_entry'] * 100,
        'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
        'exit_reason': 'open_at_end',
        'duration_days': (data[sym].index[-1] - pos['entry_date']).days,
        'score': pos['score'],
        'account': account,
    })

# ── RESULTS ──────────────────────────────────────────────────────────────────

r = pd.DataFrame(trades)
if len(r) == 0:
    print("\nNo trades generated.")
else:
    r['entry_date'] = pd.to_datetime(r['entry_date'])
    r['exit_date']  = pd.to_datetime(r['exit_date'])
    r['win']        = r['R'] > 0
    wins, losses = r[r['win']], r[~r['win']]
    eq = pd.DataFrame(equity_history).set_index('date')
    peak = INITIAL_CAPITAL; max_dd = 0
    for v in [INITIAL_CAPITAL] + list(eq['equity']):
        if v > peak: peak = v
        dd = (v-peak)/peak*100
        if dd < max_dd: max_dd = dd

    sep = "─" * 86
    print(f"\n{'═'*86}")
    print(f"  SETUP A — COMPRESSION BREAKOUT — 18-ASSET CRYPTO UNIVERSE")
    print(f"  Period: Jan 2023 → {all_dates[-1].date()}   Start: ${INITIAL_CAPITAL:,.2f}")
    print(f"{'═'*86}")
    print(f"  Total trades:          {len(r)}")
    print(f"  Win rate:              {len(wins)/len(r)*100:.1f}%")
    print(f"  Avg win (R):           {wins['R'].mean():+.2f}" if len(wins) else "  Avg win: -")
    print(f"  Avg loss (R):          {losses['R'].mean():+.2f}" if len(losses) else "  Avg loss: -")
    print(f"  Expectancy (R):        {r['R'].mean():+.3f}")
    print(f"  Best winner (R):       {r['R'].max():+.2f}")
    print(f"  Worst loser (R):       {r['R'].min():+.2f}")
    print(f"  Avg duration (days):   {r['duration_days'].mean():.1f}")
    print(f"  Final balance ($):     {account:,.2f}")
    print(f"  Total return %:        {(account/INITIAL_CAPITAL-1)*100:+.1f}")
    print(f"  Max drawdown %:        {max_dd:+.2f}")

    print(f"\n{sep}\n  PER-ASSET BREAKDOWN")
    print(sep)
    print(f"  {'Asset':<12}{'Trades':>8}{'Win%':>8}{'Avg R':>10}{'Total $':>14}")
    for sym, grp in r.groupby('symbol'):
        w = grp[grp['win']]
        wr = len(w)/len(grp)*100
        ar = grp['R'].mean()
        tot = grp['pnl_usd'].sum()
        print(f"  {sym:<12}{len(grp):>8}{wr:>7.1f}%{ar:>+10.2f}{tot:>+14,.2f}")

    print(f"\n{sep}\n  YEAR-BY-YEAR")
    print(sep)
    r['year'] = r['exit_date'].dt.year
    print(f"  {'Year':<8}{'Trades':>8}{'Win%':>8}{'Avg R':>10}{'PnL $':>14}{'Exp R':>10}")
    for yr, grp in r.groupby('year'):
        w = grp[grp['win']]
        wr = len(w)/len(grp)*100
        ar = grp['R'].mean()
        tot = grp['pnl_usd'].sum()
        exp = grp['R'].mean()
        print(f"  {yr:<8}{len(grp):>8}{wr:>7.1f}%{ar:>+10.2f}{tot:>+14,.2f}{exp:>+10.3f}")

    print(f"\n{sep}\n  EXIT REASON BREAKDOWN")
    print(sep)
    for reason, cnt in r['exit_reason'].value_counts().items():
        grp = r[r['exit_reason']==reason]
        wr = len(grp[grp['win']])/len(grp)*100
        ar = grp['R'].mean()
        print(f"  {reason:<22} {cnt:>4} trades  {wr:>5.1f}% win  avg R: {ar:+.3f}")

    print(f"\n{sep}\n  SCORE DISTRIBUTION")
    print(sep)
    for sc in sorted(r['score'].unique()):
        grp = r[r['score']==sc]
        wr = len(grp[grp['win']])/len(grp)*100 if len(grp) else 0
        ar = grp['R'].mean() if len(grp) else 0
        print(f"  Score {sc}: {len(grp):>4} trades  {wr:>5.1f}% win  avg R: {ar:+.3f}")

    # ── EQUITY CURVE ─────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(15, 7))
    ax.plot(eq.index, eq['equity'], color='#1f77b4', linewidth=1.4,
            label=f"Setup A scanner  ({(account/INITIAL_CAPITAL-1)*100:+.0f}%, DD {max_dd:.1f}%, {len(r)} trades)")
    ax.axhline(INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.5)
    ax.set_ylabel('Account ($)')
    ax.set_title('Setup A — Compression Breakout Scanner  (18 alts daily)', fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig('setupA_equity.png', dpi=120, bbox_inches='tight')
    print(f"\nChart -> setupA_equity.png")
    r.to_csv('setupA_trades.csv', index=False)
    print(f"Trades log -> setupA_trades.csv")
