"""
SETUP B & C — 4H and 1D backtests on the Spring universe.

SETUP B: Pullback to Moving Average in Uptrend
  - Trend:    close > 50 SMA > 200 SMA
  - Pullback: in last 5 bars, low touched/penetrated 20 EMA
  - Reversal: today close > open, close > prev close, close in upper half of range
  - Entry:    stop-buy at high of reversal candle (next bar's high must exceed trigger)
  - Stop:     lowest low of last 5 bars
  - Manage:   50% off at 2R, trail rest with 20-bar low

SETUP C: 6-Month (~1-Year-ish) High Breakout
  - Lookback: 180 days on 1D, 1080 bars on 4H
  - Breakout: today close > max of previous N bars
  - Trend:    close > 50 SMA > 200 SMA
  - Volume:   > 1.5× 20-bar avg
  - Entry:    next bar's open
  - Stop:     entry - 2*ATR(14)
  - Manage:   50% off at 2R, trail rest with 20-bar low

Universe: BTC, ETH, SOL, LINK, ADA, ARB, SUI, SEI
Period:   Jan 2022 → now (includes 2022 bear market)
Capital:  $1,839 starting, 2% risk per trade, max 3 concurrent positions
Fees:     0.10% per leg
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ASSETS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT',
          'ADA/USDT', 'ARB/USDT', 'SUI/USDT', 'SEI/USDT']

INITIAL_CAPITAL = 1839.17
RISK_PCT        = 0.02
MAX_POSITIONS   = 3
FEE_PER_LEG     = 0.0010

exchange = ccxt.binance()
since = exchange.parse8601('2022-01-01T00:00:00Z')

def fetch_full(symbol, timeframe, since_ms, exchange):
    all_candles = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        all_candles.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return all_candles

def fetch_universe(tf):
    print(f"  Fetching {tf}...")
    out = {}
    for asset in ASSETS:
        try:
            raw = fetch_full(asset, tf, since, exchange)
            if not raw or len(raw) < 220: continue
            df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
            df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            df = df.set_index('dt').drop(columns='ts').sort_index()
            df = df[~df.index.duplicated(keep='last')]
            out[asset] = df
        except Exception as e:
            print(f"    {asset}: failed - {e}")
    return out

print("Fetching data for 8 assets...")
data_4h = fetch_universe('4h')
data_1d = fetch_universe('1d')
print(f"  Loaded 4H: {len(data_4h)} assets, 1D: {len(data_1d)} assets\n")

def compute_indicators(df):
    df = df.copy()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    df['ema20']  = df['close'].ewm(span=20, adjust=False).mean()
    prev_close = df['close'].shift(1)
    tr = pd.concat([df['high']-df['low'], (df['high']-prev_close).abs(), (df['low']-prev_close).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()
    df['vol_sma20'] = df['volume'].rolling(20).mean()
    df['low_5']     = df['low'].rolling(5).min()
    return df

print("Computing indicators...")
for asset in list(data_4h.keys()):
    data_4h[asset] = compute_indicators(data_4h[asset])
for asset in list(data_1d.keys()):
    data_1d[asset] = compute_indicators(data_1d[asset])

# ── SETUP B SIGNAL DETECTION ─────────────────────────────────────────────────

def setup_b_signal(df, i):
    """Returns (is_signal, stop_price) if all conditions met, else (False, None)."""
    if i < 200: return False, None
    close, open_ = df['close'].iloc[i], df['open'].iloc[i]
    high, low    = df['high'].iloc[i], df['low'].iloc[i]
    sma50, sma200 = df['sma50'].iloc[i], df['sma200'].iloc[i]
    ema20         = df['ema20'].iloc[i]
    if any(pd.isna(x) for x in [sma50, sma200, ema20]): return False, None

    # Trend
    if not (close > sma50 > sma200): return False, None
    # Pullback in last 5 bars touched/penetrated 20 EMA
    pullback_hit = False
    for k in range(1, 6):
        if (i-k) >= 0 and df['low'].iloc[i-k] <= df['ema20'].iloc[i-k]:
            pullback_hit = True; break
    if not pullback_hit: return False, None
    # Reversal candle today
    if not (close > open_ and i > 0 and close > df['close'].iloc[i-1]): return False, None
    bar_range = high - low
    if bar_range <= 0: return False, None
    if (close - low) / bar_range < 0.5: return False, None     # close in upper half

    stop = df['low_5'].iloc[i]
    if pd.isna(stop) or stop >= close: return False, None
    return True, stop

# ── SETUP C SIGNAL DETECTION ─────────────────────────────────────────────────

def setup_c_signal(df, i, lookback):
    """Returns (is_signal, stop_price) if all conditions met."""
    if i < max(200, lookback): return False, None
    close = df['close'].iloc[i]
    sma50, sma200 = df['sma50'].iloc[i], df['sma200'].iloc[i]
    atr           = df['atr14'].iloc[i]
    vol_sma       = df['vol_sma20'].iloc[i]
    volume        = df['volume'].iloc[i]
    if any(pd.isna(x) for x in [sma50, sma200, atr, vol_sma]): return False, None

    # Trend
    if not (close > sma50 > sma200): return False, None
    # New N-bar high
    prev_high = df['high'].iloc[i-lookback:i].max()
    if not (close > prev_high): return False, None
    # Volume confirmation
    if not (volume > vol_sma * 1.5): return False, None

    stop = close - 2 * atr      # We use close as entry approximation for stop calc
    if stop >= close: return False, None
    return True, stop

# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────

def run_backtest(data, setup_type, lookback=None):
    """
    setup_type: 'B' or 'C'
    lookback: required for setup C (bars or days)
    """
    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    account = INITIAL_CAPITAL
    positions = {}
    trades = []
    pending_entries = {}    # for Setup B stop-buy logic

    for date in all_dates:
        # ── Process pending entries (Setup B) ──
        for sym in list(pending_entries.keys()):
            if date not in data[sym].index:
                continue
            df = data[sym]
            idx = df.index.get_loc(date)
            pending = pending_entries[sym]
            high = df['high'].iloc[idx]
            # Cancel if too old (signal expires)
            if (date - pending['signal_date']).total_seconds() > pending['expiry_seconds']:
                del pending_entries[sym]
                continue
            # Fill if high touches trigger
            if high >= pending['trigger']:
                if len(positions) >= MAX_POSITIONS or sym in positions:
                    del pending_entries[sym]
                    continue
                entry_price = pending['trigger']
                stop_price  = pending['stop']
                if stop_price >= entry_price:
                    del pending_entries[sym]
                    continue
                stop_distance = entry_price - stop_price
                size = (account * RISK_PCT) / stop_distance
                entry_fee = entry_price * size * FEE_PER_LEG
                account -= entry_fee
                positions[sym] = {
                    'entry_date': date, 'entry_price': entry_price,
                    'stop_price': stop_price,
                    'first_target': entry_price + 2 * stop_distance,
                    'size': size, 'size_remaining': 1.0,
                    'acct_at_entry': account + entry_fee,
                    'setup_score': pending.get('score'),
                    'partial_pnl_net': -entry_fee,
                }
                del pending_entries[sym]

        # ── Manage open positions ──
        for sym in list(positions.keys()):
            if date not in data[sym].index: continue
            df = data[sym]
            idx = df.index.get_loc(date)
            high, low = df['high'].iloc[idx], df['low'].iloc[idx]
            pos = positions[sym]

            if low <= pos['stop_price']:
                exit_px = pos['stop_price']
                size = pos['size'] * pos['size_remaining']
                exit_pnl = (exit_px - pos['entry_price']) * size - exit_px * size * FEE_PER_LEG
                total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
                account += exit_pnl
                trades.append({
                    'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': date,
                    'entry_price': pos['entry_price'], 'exit_price': exit_px,
                    'pnl_usd': total_pnl,
                    'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
                    'exit_reason': 'trailing_stop' if pos.get('scaled_out') else 'stop_loss',
                    'duration_h': (date - pos['entry_date']).total_seconds()/3600,
                    'account': account,
                })
                del positions[sym]
                continue

            if not pos.get('scaled_out') and high >= pos['first_target']:
                partial_size = pos['size'] * 0.5
                partial_pnl_net = (pos['first_target'] - pos['entry_price']) * partial_size - pos['first_target']*partial_size*FEE_PER_LEG
                account += partial_pnl_net
                pos['partial_pnl_net'] = pos.get('partial_pnl_net', 0) + partial_pnl_net
                pos['size_remaining'] = 0.5
                pos['stop_price'] = pos['entry_price']
                pos['scaled_out'] = True

            if pos.get('scaled_out'):
                low_20 = df['low'].iloc[max(0, idx-20):idx].min()
                if low_20 > pos['stop_price']:
                    pos['stop_price'] = low_20

        # ── Look for new signals ──
        if len(positions) + len(pending_entries) < MAX_POSITIONS:
            for sym, df in data.items():
                if sym in positions or sym in pending_entries: continue
                if date not in df.index: continue
                idx = df.index.get_loc(date)
                if setup_type == 'B':
                    sig, stop = setup_b_signal(df, idx)
                    if sig:
                        # Place stop-buy at high of reversal candle, expires next bar
                        timeframe_seconds = (df.index[idx] - df.index[idx-1]).total_seconds() if idx > 0 else 14400
                        pending_entries[sym] = {
                            'signal_date': date,
                            'trigger': df['high'].iloc[idx],
                            'stop':    stop,
                            'expiry_seconds': timeframe_seconds * 2,
                        }
                elif setup_type == 'C':
                    sig, stop = setup_c_signal(df, idx, lookback)
                    if sig and idx + 1 < len(df):
                        # Enter at next bar's open
                        entry_price = df['open'].iloc[idx + 1]
                        # Use entry price to recompute stop
                        atr = df['atr14'].iloc[idx]
                        stop_price = entry_price - 2 * atr
                        if stop_price >= entry_price: continue
                        if len(positions) >= MAX_POSITIONS: break
                        stop_distance = entry_price - stop_price
                        size = (account * RISK_PCT) / stop_distance
                        entry_fee = entry_price * size * FEE_PER_LEG
                        account -= entry_fee
                        positions[sym] = {
                            'entry_date': df.index[idx + 1], 'entry_price': entry_price,
                            'stop_price': stop_price,
                            'first_target': entry_price + 2 * stop_distance,
                            'size': size, 'size_remaining': 1.0,
                            'acct_at_entry': account + entry_fee,
                            'partial_pnl_net': -entry_fee,
                        }

    # Close any remaining
    for sym, pos in positions.items():
        df = data[sym]
        last_close = df['close'].iloc[-1]
        size = pos['size'] * pos['size_remaining']
        exit_pnl = (last_close - pos['entry_price']) * size - last_close*size*FEE_PER_LEG
        total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
        account += exit_pnl
        trades.append({
            'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': data[sym].index[-1],
            'entry_price': pos['entry_price'], 'exit_price': last_close,
            'pnl_usd': total_pnl, 'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
            'exit_reason': 'open_at_end',
            'duration_h': (data[sym].index[-1] - pos['entry_date']).total_seconds()/3600,
            'account': account,
        })
    return pd.DataFrame(trades), account

# ── RUN ALL 4 BACKTESTS ──────────────────────────────────────────────────────

print("Running Setup B on 4H...")
r_b4, f_b4 = run_backtest(data_4h, 'B')
print(f"  {len(r_b4)} trades, final ${f_b4:,.2f}")

print("Running Setup B on 1D...")
r_b1, f_b1 = run_backtest(data_1d, 'B')
print(f"  {len(r_b1)} trades, final ${f_b1:,.2f}")

print("Running Setup C on 4H (lookback 1080 bars = ~180 days)...")
r_c4, f_c4 = run_backtest(data_4h, 'C', lookback=1080)
print(f"  {len(r_c4)} trades, final ${f_c4:,.2f}")

print("Running Setup C on 1D (lookback 180 days)...")
r_c1, f_c1 = run_backtest(data_1d, 'C', lookback=180)
print(f"  {len(r_c1)} trades, final ${f_c1:,.2f}")

def stats(r, final):
    if len(r) == 0:
        return {'trades':0,'wr':0,'aw':0,'al':0,'exp':0,'dd':0,'final':final,'ret':0,'apy':0,'r':r}
    r['win'] = r['R'] > 0
    r['entry_date'] = pd.to_datetime(r['entry_date'])
    r['exit_date'] = pd.to_datetime(r['exit_date'])
    r['year'] = r['exit_date'].dt.year
    wins, losses = r[r['win']], r[~r['win']]
    curve = [INITIAL_CAPITAL] + list(r['account'])
    peak = INITIAL_CAPITAL; mdd = 0
    for v in curve:
        if v > peak: peak = v
        d = (v-peak)/peak*100
        if d < mdd: mdd = d
    days = (r['exit_date'].iloc[-1] - r['entry_date'].iloc[0]).days
    apy = ((final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    return {
        'trades': len(r), 'wr': len(wins)/len(r)*100,
        'aw': wins['R'].mean() if len(wins) else 0,
        'al': losses['R'].mean() if len(losses) else 0,
        'exp': r['R'].mean(),
        'dd': mdd, 'final': final,
        'ret': (final/INITIAL_CAPITAL-1)*100,
        'apy': apy, 'r': r,
    }

s_b4 = stats(r_b4, f_b4)
s_b1 = stats(r_b1, f_b1)
s_c4 = stats(r_c4, f_c4)
s_c1 = stats(r_c1, f_c1)

sep = "─" * 110
print(f"\n{'═'*110}")
print(f"  SETUP B & C — 8-ASSET CRYPTO UNIVERSE — Jan 2022 → {pd.Timestamp.utcnow().date()}")
print(f"  Risk 2%/trade, max 3 positions, fees 0.10%/leg")
print(f"{'═'*110}")
print(f"  {'Strategy':<30}{'Trades':>8}{'Win%':>8}{'Avg Win R':>12}{'Avg Loss R':>12}{'Exp R':>10}{'Max DD %':>10}{'Final $':>12}{'APY %':>10}")
print(sep)
for label, s in [('Setup B - Pullback 4H', s_b4),
                  ('Setup B - Pullback 1D', s_b1),
                  ('Setup C - 6M High Brk 4H', s_c4),
                  ('Setup C - 6M High Brk 1D', s_c1)]:
    if s['trades'] == 0:
        print(f"  {label:<30}{0:>8}  no trades")
        continue
    print(f"  {label:<30}{s['trades']:>8}{s['wr']:>7.1f}%{s['aw']:>+12.2f}{s['al']:>+12.2f}{s['exp']:>+10.3f}{s['dd']:>+10.2f}{s['final']:>12,.2f}{s['apy']:>+10.1f}")

# Reference rows
print(sep)
print(f"  {'(Reference) Spring 4H thr8':<30}{31:>8}{41.9:>7.1f}%{2.85:>+12.2f}{-1.06:>+12.2f}{0.576:>+10.3f}{-13.0:>+10.2f}{2523:>12,.2f}{9.8:>+10.1f}")
print(f"  {'(Reference) USDT lending 6%':<30}{'-':>8}{'-':>8}{'-':>12}{'-':>12}{'-':>10}{0.00:>+10.2f}{2400:>12,.2f}{6.0:>+10.1f}")

# Year-by-year and per-asset
for label, s in [('Setup B 4H', s_b4), ('Setup B 1D', s_b1),
                  ('Setup C 4H', s_c4), ('Setup C 1D', s_c1)]:
    if s['trades'] == 0: continue
    print(f"\n{sep}\n  {label} — DETAILED")
    print(sep)
    r = s['r']
    print(f"  Year-by-year:")
    for yr, grp in r.groupby('year'):
        wr = len(grp[grp['win']])/len(grp)*100
        print(f"    {yr}: {len(grp):>3} trades, {wr:>5.1f}% win, P&L ${grp['pnl_usd'].sum():>+9,.2f}, expectancy {grp['R'].mean():+.3f}R")
    print(f"\n  Per-asset:")
    for sym, grp in r.groupby('symbol'):
        wr = len(grp[grp['win']])/len(grp)*100
        print(f"    {sym:<12} {len(grp):>3} trades, {wr:>5.1f}% win, avg R {grp['R'].mean():+.2f}, P&L ${grp['pnl_usd'].sum():>+9,.2f}")
    print(f"\n  Exit reasons:")
    for reason, cnt in r['exit_reason'].value_counts().items():
        grp = r[r['exit_reason']==reason]
        wr = len(grp[grp['win']])/len(grp)*100
        print(f"    {reason:<22} {cnt:>4} trades  {wr:>5.1f}% win  avg R: {grp['R'].mean():+.3f}")

# Equity charts
fig, ax = plt.subplots(figsize=(15, 7))
for label, s, color in [('Setup B 4H', s_b4, '#1f77b4'),
                         ('Setup B 1D', s_b1, '#2ca02c'),
                         ('Setup C 4H', s_c4, '#ff7f0e'),
                         ('Setup C 1D', s_c1, '#d62728')]:
    if s['trades'] == 0: continue
    r = s['r']
    eq_x = [r['entry_date'].iloc[0] - pd.Timedelta(days=1)] + r['exit_date'].tolist()
    eq_y = [INITIAL_CAPITAL] + r['account'].tolist()
    ax.plot(eq_x, eq_y, color=color, linewidth=1.4,
            label=f"{label}  ({s['ret']:+.0f}%, {s['apy']:+.1f}% APY, DD {s['dd']:.0f}%, {s['trades']} trades)")
ax.axhline(INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.5)
ax.set_ylabel('Account ($)')
ax.set_title('Setup B & C — Backtests on 8-Asset Universe (Jan 2022 → now)', fontweight='bold')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
plt.tight_layout()
plt.savefig('setups_BC.png', dpi=120, bbox_inches='tight')
print(f"\nChart -> setups_BC.png")
