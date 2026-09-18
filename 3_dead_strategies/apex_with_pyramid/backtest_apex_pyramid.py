"""
APEX with Pyramiding — 4H Multi-Lookback Test

CURATED UNIVERSE (ARB and SEI dropped):
  BTC, ETH, SOL, LINK, ADA, SUI

PYRAMIDING (Quattro-style, adapted for Apex):
  - Unit 1: Initial breakout entry (close > N-day high, vol > 1.5×avg, trend)
  - Unit 2: Add at +1×ATR favorable move
  - Unit 3: Add at +2×ATR favorable
  - Unit 4: Add at +3×ATR favorable (max 4 units)
  - All units share common trailing stop (newest unit entry - 2×ATR)
  - Plus: trail with max(common_stop, 20-bar low) as price moves up
  - Exit: trailing stop hit (no partial scale-outs)
  - Hard backstop: 5% account loss

LOOKBACK VARIANTS:
  A: 90 days  (540 bars on 4H)  — frequent but lower-quality highs
  B: 180 days (1080 bars)        — current default
  C: 252 days (1512 bars)        — traditional 1 trading year
  D: 365 days (2190 bars)        — full calendar year
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ASSETS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT', 'ADA/USDT', 'SUI/USDT']

INITIAL_CAPITAL  = 1839.17
RISK_PCT         = 0.02
HARD_STOP_PCT    = 0.05
PYRAMID_N_STEP   = 1.0    # add unit every +1*ATR favorable
MAX_UNITS        = 4
MAX_POSITIONS    = 3
MAX_LEVERAGE     = 20
FEE_PER_LEG      = 0.0010

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

print("Fetching 4H data for 6 curated assets...")
data = {}
for asset in ASSETS:
    raw = fetch_full(asset, '4h', since, exchange)
    if not raw or len(raw) < 220: continue
    df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
    df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.set_index('dt').drop(columns='ts').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    data[asset] = df
    print(f"  {asset}: {len(df)} bars from {df.index[0].date()}")
print()

def compute_indicators(df):
    df = df.copy()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    prev_close = df['close'].shift(1)
    tr = pd.concat([df['high']-df['low'], (df['high']-prev_close).abs(), (df['low']-prev_close).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()
    df['vol_sma20'] = df['volume'].rolling(20).mean()
    return df

for asset in list(data.keys()):
    data[asset] = compute_indicators(data[asset])

def is_breakout(df, i, lookback_bars):
    """Check if bar i is a valid breakout: close > N-bar high, trend OK, volume confirmed."""
    if i < max(200, lookback_bars): return False
    close = df['close'].iloc[i]
    sma50, sma200 = df['sma50'].iloc[i], df['sma200'].iloc[i]
    atr = df['atr14'].iloc[i]
    vol_sma = df['vol_sma20'].iloc[i]
    volume = df['volume'].iloc[i]
    if any(pd.isna(x) for x in [sma50, sma200, atr, vol_sma]): return False
    if not (close > sma50 > sma200): return False
    prev_high = df['high'].iloc[i-lookback_bars:i].max()
    if not (close > prev_high): return False
    if not (volume > vol_sma * 1.5): return False
    return True

def run_pyramid_backtest(data, lookback_bars):
    """Run Apex with pyramiding for given lookback."""
    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    account = INITIAL_CAPITAL
    positions = {}    # sym -> {units, original_entry, original_atr, common_stop, hard_stop, ...}
    trades = []
    eq_history = []

    for date in all_dates:
        # ── Manage existing positions ──
        for sym in list(positions.keys()):
            if date not in data[sym].index: continue
            df = data[sym]
            idx = df.index.get_loc(date)
            high = df['high'].iloc[idx]
            low  = df['low'].iloc[idx]
            close = df['close'].iloc[idx]
            pos = positions[sym]

            # Check hard 5% stop (catastrophe)
            total_size_now = sum(u['size'] for u in pos['units'])
            wavg_entry = sum(u['entry_price']*u['size'] for u in pos['units']) / total_size_now
            unrealized_at_low = (low - wavg_entry) * total_size_now
            if unrealized_at_low <= -HARD_STOP_PCT * pos['acct_at_entry']:
                # Calculate exit price that gives -5% account loss
                target_loss = -HARD_STOP_PCT * pos['acct_at_entry']
                exit_px = wavg_entry + target_loss / total_size_now
                exit_fee = exit_px * total_size_now * FEE_PER_LEG
                exit_pnl = (exit_px - wavg_entry) * total_size_now - exit_fee
                total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
                account += exit_pnl
                trades.append({
                    'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': date,
                    'entry_price': pos['original_entry'], 'exit_price': exit_px,
                    'units': len(pos['units']), 'pnl_usd': total_pnl,
                    'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
                    'exit_reason': 'hard_stop_5pct',
                    'duration_h': (date - pos['entry_date']).total_seconds()/3600,
                    'account': account,
                })
                del positions[sym]
                continue

            # Check trailing stop (intrabar via low)
            if low <= pos['common_stop']:
                exit_px = pos['common_stop']
                exit_fee = exit_px * total_size_now * FEE_PER_LEG
                exit_pnl = (exit_px - wavg_entry) * total_size_now - exit_fee
                total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
                account += exit_pnl
                trades.append({
                    'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': date,
                    'entry_price': pos['original_entry'], 'exit_price': exit_px,
                    'units': len(pos['units']), 'pnl_usd': total_pnl,
                    'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
                    'exit_reason': 'trailing_stop',
                    'duration_h': (date - pos['entry_date']).total_seconds()/3600,
                    'account': account,
                })
                del positions[sym]
                continue

            # Check pyramid additions
            while len(pos['units']) < MAX_UNITS:
                next_trigger = pos['original_entry'] + len(pos['units']) * PYRAMID_N_STEP * pos['original_atr']
                if high < next_trigger: break
                unit_entry = next_trigger
                r_amt = pos['acct_at_entry'] * RISK_PCT
                unit_size = r_amt / (2 * pos['original_atr'])
                # Check leverage
                total_notional = sum(u['size']*close for u in pos['units']) + unit_size*close
                if total_notional / account > MAX_LEVERAGE: break
                # Add unit (pay entry fee)
                entry_fee = unit_entry * unit_size * FEE_PER_LEG
                account -= entry_fee
                pos['partial_pnl_net'] = pos.get('partial_pnl_net', 0) - entry_fee
                pos['units'].append({'entry_price': unit_entry, 'size': unit_size})
                # Trail common stop up: newest entry - 2*ATR
                new_stop = unit_entry - 2 * pos['original_atr']
                if new_stop > pos['common_stop']:
                    pos['common_stop'] = new_stop

            # Trail with 20-bar low (only goes up)
            low_20 = df['low'].iloc[max(0, idx-20):idx].min()
            if low_20 > pos['common_stop']:
                pos['common_stop'] = low_20

        # ── Look for new entries ──
        if len(positions) < MAX_POSITIONS:
            for sym, df in data.items():
                if sym in positions: continue
                if date not in df.index: continue
                idx = df.index.get_loc(date)
                if not is_breakout(df, idx, lookback_bars): continue
                if idx + 1 >= len(df): continue

                entry_price = df['open'].iloc[idx + 1]
                atr = df['atr14'].iloc[idx]
                stop_price = entry_price - 2 * atr
                if stop_price >= entry_price: continue
                r_amt = account * RISK_PCT
                unit_size = r_amt / (entry_price - stop_price)
                notional = unit_size * entry_price
                if notional / account > MAX_LEVERAGE: continue
                entry_fee = entry_price * unit_size * FEE_PER_LEG
                account -= entry_fee
                positions[sym] = {
                    'entry_date': df.index[idx + 1],
                    'original_entry': entry_price,
                    'original_atr': atr,
                    'common_stop': stop_price,
                    'hard_stop': entry_price - (HARD_STOP_PCT * account / unit_size),
                    'acct_at_entry': account + entry_fee,
                    'units': [{'entry_price': entry_price, 'size': unit_size}],
                    'partial_pnl_net': -entry_fee,
                }
                if len(positions) >= MAX_POSITIONS: break

        eq_history.append({'date': date, 'equity': account})

    # Close any open at end
    for sym, pos in positions.items():
        df = data[sym]
        last_close = df['close'].iloc[-1]
        total_size = sum(u['size'] for u in pos['units'])
        wavg = sum(u['entry_price']*u['size'] for u in pos['units']) / total_size
        exit_fee = last_close * total_size * FEE_PER_LEG
        exit_pnl = (last_close - wavg) * total_size - exit_fee
        total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
        account += exit_pnl
        trades.append({
            'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': data[sym].index[-1],
            'entry_price': pos['original_entry'], 'exit_price': last_close,
            'units': len(pos['units']), 'pnl_usd': total_pnl,
            'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
            'exit_reason': 'open_at_end',
            'duration_h': (data[sym].index[-1] - pos['entry_date']).total_seconds()/3600,
            'account': account,
        })

    return pd.DataFrame(trades), account, pd.DataFrame(eq_history).set_index('date')

# ── RUN VARIANTS ─────────────────────────────────────────────────────────────

LOOKBACKS = {
    'A: 90d (540 bars)':  540,
    'B: 180d (1080 bars)':1080,
    'C: 252d (1512 bars)':1512,
    'D: 365d (2190 bars)':2190,
}

results = {}
for name, bars in LOOKBACKS.items():
    print(f"Running {name}...")
    r, final, eq = run_pyramid_backtest(data, bars)
    if len(r) > 0:
        r['win'] = r['R'] > 0
        r['entry_date'] = pd.to_datetime(r['entry_date'])
        r['exit_date'] = pd.to_datetime(r['exit_date'])
        r['year'] = r['exit_date'].dt.year
    results[name] = {'trades': r, 'final': final, 'eq': eq}
    print(f"  {len(r)} trades, final ${final:,.2f}")

def stats(r, final, eq):
    if len(r) == 0:
        return {'trades':0,'wr':0,'aw':0,'al':0,'exp':0,'dd':0,'final':final,'ret':0,'apy':0,'big':0,'avgU':0}
    wins, losses = r[r['win']], r[~r['win']]
    curve = [INITIAL_CAPITAL] + list(eq['equity'])
    peak = INITIAL_CAPITAL; mdd = 0
    for v in curve:
        if v > peak: peak = v
        d = (v-peak)/peak*100
        if d < mdd: mdd = d
    days = (eq.index[-1] - eq.index[0]).days
    apy = ((final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    return {
        'trades': len(r), 'wr': len(wins)/len(r)*100,
        'aw': wins['R'].mean() if len(wins) else 0,
        'al': losses['R'].mean() if len(losses) else 0,
        'exp': r['R'].mean(),
        'big': r['R'].max(), 'dd': mdd,
        'final': final, 'ret': (final/INITIAL_CAPITAL-1)*100, 'apy': apy,
        'avgU': r['units'].mean() if 'units' in r else 0,
    }

# ── REPORT ──────────────────────────────────────────────────────────────────

sep = "─" * 110
print(f"\n{'═'*110}")
print(f"  APEX with PYRAMIDING — 6-asset curated universe (no ARB/SEI) — Jan 2022 → now")
print(f"{'═'*110}")
print(f"  {'Variant':<24}{'Trades':>8}{'Win%':>8}{'Avg Win R':>12}{'Avg Loss R':>12}{'Exp R':>10}{'Biggest R':>11}{'Avg Units':>11}{'Max DD %':>10}{'APY %':>8}")
print(sep)
for name in LOOKBACKS:
    s = stats(results[name]['trades'], results[name]['final'], results[name]['eq'])
    print(f"  {name:<24}{s['trades']:>8}{s['wr']:>7.1f}%{s['aw']:>+12.2f}{s['al']:>+12.2f}{s['exp']:>+10.3f}{s['big']:>+11.2f}{s['avgU']:>11.2f}{s['dd']:>+10.2f}{s['apy']:>+8.1f}")

# Reference
print(sep)
print(f"  (Ref) Apex 4H no pyramid {65:>8}{44.6:>7.1f}%{2.48:>+12.2f}{-1.04:>+12.2f}{0.529:>+10.3f}{'?':>11}{1.0:>11.2f}{-14.04:>+10.2f}{27.0:>+8.1f}")
print(f"  (Ref) Quattro pyramid    {94:>8}{26.6:>7.1f}%{13.42:>+12.2f}{-2.01:>+12.2f}{2.097:>+10.3f}{76.67:>+11.2f}{3.13:>11.2f}{-37.50:>+10.2f}{91.0:>+8.1f}")
print(f"  (Ref) USDT lending 6%        {'-':>8}{'-':>8}{'-':>12}{'-':>12}{'-':>10}{'-':>11}{'-':>11}{0.00:>+10.2f}{6.0:>+8.1f}")

# Best variant details
best_name = max(LOOKBACKS, key=lambda n: results[n]['final'])
r = results[best_name]['trades']
print(f"\n{sep}\n  BEST VARIANT: {best_name}")
print(sep)
if len(r) > 0:
    print(f"  Year-by-year:")
    for yr, grp in r.groupby('year'):
        wr = len(grp[grp['win']])/len(grp)*100
        avgU = grp['units'].mean()
        print(f"    {yr}: {len(grp):>3} trades, {wr:>5.1f}% win, P&L ${grp['pnl_usd'].sum():>+10,.2f}, exp {grp['R'].mean():+.3f}R, avg {avgU:.2f} units")
    print(f"\n  Per-asset:")
    for sym, grp in r.groupby('symbol'):
        wr = len(grp[grp['win']])/len(grp)*100
        print(f"    {sym:<12} {len(grp):>3} trades, {wr:>5.1f}% win, avg R {grp['R'].mean():+.2f}, P&L ${grp['pnl_usd'].sum():>+9,.2f}, avg units {grp['units'].mean():.2f}")
    print(f"\n  Unit count distribution:")
    for u in sorted(r['units'].unique()):
        grp = r[r['units']==u]
        wr = len(grp[grp['win']])/len(grp)*100
        print(f"    {u} unit(s): {len(grp):>3} trades, {wr:>5.1f}% win, avg R {grp['R'].mean():+.2f}")
    print(f"\n  Exit reasons:")
    for reason, cnt in r['exit_reason'].value_counts().items():
        grp = r[r['exit_reason']==reason]
        wr = len(grp[grp['win']])/len(grp)*100
        print(f"    {reason:<22} {cnt:>4} trades  {wr:>5.1f}% win  avg R: {grp['R'].mean():+.3f}")

# Chart
fig, ax = plt.subplots(figsize=(15, 7))
colors = {'A: 90d (540 bars)':'#9467bd', 'B: 180d (1080 bars)':'#2ca02c',
          'C: 252d (1512 bars)':'#ff7f0e', 'D: 365d (2190 bars)':'#d62728'}
for name in LOOKBACKS:
    eq = results[name]['eq']
    s = stats(results[name]['trades'], results[name]['final'], eq)
    if len(eq) > 0:
        ax.plot(eq.index, eq['equity'], color=colors[name], linewidth=1.4,
                label=f"{name}  ({s['ret']:+.0f}%, {s['apy']:+.1f}% APY, DD {s['dd']:.0f}%, {s['trades']} trades)")
ax.axhline(INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.5)
ax.set_ylabel('Account ($)')
ax.set_title('APEX with Pyramiding — Lookback Sweep (4H)', fontweight='bold')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
plt.tight_layout()
plt.savefig('apex_pyramid.png', dpi=120, bbox_inches='tight')
print(f"\nChart -> apex_pyramid.png")
