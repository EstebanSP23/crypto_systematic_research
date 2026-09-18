"""
Donchian Pyramid (4-unit) — test 3 chop-avoidance filters:
  1. EMA slope filter:   daily 200 EMA must be sloping up over 20 days
  2. ADX > 25 filter:    4H ADX(14) must show trend strength
  3. ATR compression:    current 4H ATR <= its 50-period SMA (no chop entries)
  4. All three combined
Compare against baseline (no extra filter).
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ── DATA ──────────────────────────────────────────────────────────────────────

def fetch_full(symbol, timeframe, since_ms, exchange):
    all_candles = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        all_candles.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return all_candles

exchange = ccxt.binance()
since    = exchange.parse8601('2022-01-01T00:00:00Z')
since_d  = exchange.parse8601('2021-01-01T00:00:00Z')

print("Fetching data...")
raw_4h = fetch_full('BTC/USDT', '4h', since, exchange)
df = pd.DataFrame(raw_4h, columns=['ts','open','high','low','close','volume'])
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts')

raw_d = fetch_full('BTC/USDT', '1d', since_d, exchange)
df_d = pd.DataFrame(raw_d, columns=['ts','open','high','low','close','volume'])
df_d['dt'] = pd.to_datetime(df_d['ts'], unit='ms', utc=True)
df_d = df_d.set_index('dt').drop(columns='ts')

# ── INDICATORS ────────────────────────────────────────────────────────────────

print("Calculating indicators...")

# Core Donchian indicators
df['donch_high_20'] = df['high'].rolling(20).max().shift(1)
df['donch_low_10']  = df['low'].rolling(10).min().shift(1)

# 4H ATR(14) — Wilder
prev_close = df['close'].shift(1)
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - prev_close).abs(),
    (df['low']  - prev_close).abs(),
], axis=1).max(axis=1)
df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()

# Filter 3 base: ATR_50_SMA on 4H
df['atr_sma50'] = df['atr14'].rolling(50).mean()

# Filter 2 base: 4H ADX(14)  (Wilder)
prev_high = df['high'].shift(1)
prev_low  = df['low'].shift(1)
up_move   = df['high'] - prev_high
down_move = prev_low - df['low']
plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
plus_dm_s  = pd.Series(plus_dm,  index=df.index).ewm(alpha=1/14, adjust=False).mean()
minus_dm_s = pd.Series(minus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean()
plus_di   = 100 * plus_dm_s  / df['atr14']
minus_di  = 100 * minus_dm_s / df['atr14']
dx        = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
df['adx14'] = dx.ewm(alpha=1/14, adjust=False).mean()

# Daily 200 EMA + slope
df_d['ema200']        = df_d['close'].ewm(span=200, adjust=False).mean()
df_d['ema200_20d_ago']= df_d['ema200'].shift(20)
df_d['ema200_slope_up'] = df_d['ema200'] > df_d['ema200_20d_ago']

# Align daily to 4H (no lookahead — shift by 1 day for availability)
df_d_avail        = df_d[['ema200', 'ema200_slope_up']].copy()
df_d_avail.index  = df_d_avail.index + pd.Timedelta(days=1)
df_d_aligned      = df_d_avail.reindex(df.index, method='ffill')
df['d_ema200']      = df_d_aligned['ema200']
df['d_ema200_up']   = df_d_aligned['ema200_slope_up']
df['regime_up']     = df['close'] > df['d_ema200']

# ── BACKTEST ENGINE (parameterized) ───────────────────────────────────────────

INITIAL_BALANCE = 1839.17
RISK_PCT        = 0.02
HARD_STOP_PCT   = 0.05
PYRAMID_STEP    = 0.5
MAX_UNITS       = 4
MAX_LEVERAGE    = 20
WARMUP          = 250

# arrays for speed
open_  = df['open'].values
high_  = df['high'].values
low_   = df['low'].values
close_ = df['close'].values
dhigh_ = df['donch_high_20'].values
dlow_  = df['donch_low_10'].values
atr_   = df['atr14'].values
atrsma_= df['atr_sma50'].values
adx_   = df['adx14'].values
reg_   = df['regime_up'].values
slope_ = df['d_ema200_up'].values
dates_ = df.index
n      = len(df)

def run_backtest(use_slope=False, use_adx=False, use_atrcomp=False):
    account = INITIAL_BALANCE
    trades  = []
    in_trade = False
    units = []
    original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None
    pending_exit = False
    pending_exit_reason = None

    def total_size(): return sum(u['size'] for u in units)
    def total_notional(p): return sum(u['size']*p for u in units)
    def total_pnl_at(p): return sum((p - u['entry_price'])*u['size'] for u in units)

    def close_all(exit_px, reason, i):
        nonlocal account, in_trade, units, original_entry, original_atr, common_stop, hard_stop, acct_at_entry
        total_pnl = total_pnl_at(exit_px)
        avg_entry = sum(u['entry_price']*u['size'] for u in units) / total_size()
        account += total_pnl
        trades.append({
            'entry_date': dates_[units[0]['entry_bar']], 'exit_date': dates_[i],
            'first_entry_price': units[0]['entry_price'], 'avg_entry_price': avg_entry,
            'exit_price': exit_px, 'num_units': len(units),
            'first_unit_risk': acct_at_entry * RISK_PCT,
            'pnl_usd': total_pnl, 'pnl_pct': total_pnl/acct_at_entry*100,
            'R_total': total_pnl / (acct_at_entry * RISK_PCT),
            'duration_h': (i - units[0]['entry_bar'])*4,
            'exit_reason': reason, 'account': account,
        })
        in_trade = False
        units = []
        original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None

    for i in range(WARMUP, n - 1):
        if pending_exit:
            close_all(open_[i], pending_exit_reason, i)
            pending_exit = False
            pending_exit_reason = None

        if in_trade:
            # Hard 5% stop
            if total_pnl_at(low_[i]) <= -HARD_STOP_PCT * acct_at_entry:
                target_loss = -HARD_STOP_PCT * acct_at_entry
                wavg_entry  = sum(u['entry_price']*u['size'] for u in units) / total_size()
                exit_px     = wavg_entry + target_loss / total_size()
                close_all(exit_px, 'hard_stop_5pct', i)
                continue

            if low_[i] <= common_stop:
                close_all(common_stop, 'atr_stop_trailing', i)
                continue

            while len(units) < MAX_UNITS:
                next_trigger = original_entry + PYRAMID_STEP * len(units) * original_atr
                if high_[i] < next_trigger: break
                unit_entry = next_trigger
                r_amt = acct_at_entry * RISK_PCT
                size  = r_amt / (2 * original_atr)
                lev   = (total_notional(close_[i]) + size*unit_entry) / (account if account > 0 else 1)
                if lev > MAX_LEVERAGE: break
                units.append({'entry_price': unit_entry, 'size': size, 'entry_bar': i})
                new_stop = unit_entry - 2*original_atr
                if new_stop > common_stop: common_stop = new_stop
                target_loss = -HARD_STOP_PCT * acct_at_entry
                wavg_entry  = sum(u['entry_price']*u['size'] for u in units) / total_size()
                hard_stop   = wavg_entry + target_loss / total_size()

            if close_[i] < dlow_[i]:
                pending_exit = True
                pending_exit_reason = 'donchian_exit'
                continue

        else:
            if np.isnan(dhigh_[i]) or np.isnan(atr_[i]) or np.isnan(reg_[i]): continue

            # Apply filters
            cond_baseline = close_[i] > dhigh_[i] and reg_[i]
            if not cond_baseline: continue

            if use_slope:
                if pd.isna(slope_[i]) or not slope_[i]: continue
            if use_adx:
                if np.isnan(adx_[i]) or adx_[i] <= 25: continue
            if use_atrcomp:
                if np.isnan(atrsma_[i]) or atr_[i] > atrsma_[i]: continue

            entry_px = open_[i+1]
            N = atr_[i]
            stop_px = entry_px - 2*N
            if entry_px - stop_px <= 0: continue
            r_amt = account * RISK_PCT
            size  = r_amt / (2*N)
            lev   = (size * entry_px) / account
            if lev > MAX_LEVERAGE: continue
            in_trade = True
            original_entry = entry_px
            original_atr = N
            acct_at_entry = account
            common_stop = stop_px
            units = [{'entry_price': entry_px, 'size': size, 'entry_bar': i+1}]
            hard_stop = entry_px - (HARD_STOP_PCT * account / size)

    if in_trade:
        close_all(close_[n-1], 'still_open_at_end', n-1)

    return pd.DataFrame(trades), account

def metrics(r, final, label):
    if len(r) == 0:
        return {'label': label, 'trades': 0, 'win_rate': 0, 'avg_win_R': 0, 'avg_loss_R': 0,
                'expectancy': 0, 'max_dd': 0, 'max_l': 0, 'final': final,
                'return_pct': (final/INITIAL_BALANCE-1)*100, 'biggest': 0}
    wins = r[r['R_total'] > 0]; losses = r[r['R_total'] <= 0]
    curve = [INITIAL_BALANCE] + list(r['account'])
    peak = INITIAL_BALANCE; max_dd = 0.0
    for v in curve:
        if v > peak: peak = v
        dd = (v - peak)/peak*100
        if dd < max_dd: max_dd = dd
    max_l = cur_l = 0
    for w in (r['R_total'] > 0):
        if w: cur_l = 0
        else: cur_l += 1; max_l = max(max_l, cur_l)
    return {
        'label': label,
        'trades': len(r),
        'win_rate': len(wins)/len(r)*100 if len(r) else 0,
        'avg_win_R': wins['R_total'].mean() if len(wins) else 0,
        'avg_loss_R': losses['R_total'].mean() if len(losses) else 0,
        'expectancy': r['R_total'].mean(),
        'max_dd': max_dd,
        'max_l': max_l,
        'final': final,
        'return_pct': (final/INITIAL_BALANCE-1)*100,
        'biggest': r['R_total'].max() if len(r) else 0,
    }

# ── RUN ALL VARIATIONS ────────────────────────────────────────────────────────

variants = [
    ('Baseline (no filter)', False, False, False),
    ('+ EMA slope',          True,  False, False),
    ('+ ADX > 25',           False, True,  False),
    ('+ ATR compression',    False, False, True),
    ('+ ALL three',          True,  True,  True),
]

results = {}
trade_dfs = {}
for label, sl, ad, at in variants:
    print(f"Running: {label}...")
    r, final = run_backtest(use_slope=sl, use_adx=ad, use_atrcomp=at)
    trade_dfs[label] = r
    results[label] = metrics(r, final, label)

# ── PRINT COMPARISON ──────────────────────────────────────────────────────────

sep = "─" * 110
print(f"\n{'═'*110}")
print(f"  4-UNIT DONCHIAN PYRAMID — Filter Comparison   BTC 4H   Jan 2022 → {df.index[-1].date()}")
print(f"{'═'*110}")
header = "  Metric                       " + "".join(f"{r['label']:>16}" for r in results.values())
print(header)
print(sep)
metric_rows = [
    ('Total trades',     lambda r: f"{r['trades']:>16}"),
    ('Win rate %',       lambda r: f"{r['win_rate']:>16.1f}"),
    ('Avg win (R)',      lambda r: f"{r['avg_win_R']:>+16.2f}"),
    ('Avg loss (R)',     lambda r: f"{r['avg_loss_R']:>+16.2f}"),
    ('Expectancy (R)',   lambda r: f"{r['expectancy']:>+16.3f}"),
    ('Max drawdown %',   lambda r: f"{r['max_dd']:>+16.2f}"),
    ('Max losing streak',lambda r: f"{r['max_l']:>16}"),
    ('Final balance ($)',lambda r: f"{r['final']:>16,.2f}"),
    ('Total return %',   lambda r: f"{r['return_pct']:>+16.1f}"),
    ('Biggest winner (R)',lambda r: f"{r['biggest']:>+16.2f}"),
    ('Return / DD ratio',lambda r: f"{abs(r['return_pct']/r['max_dd']) if r['max_dd']!=0 else 0:>16.2f}"),
]
for label, fmt in metric_rows:
    print(f"  {label:<28}" + "".join(fmt(r) for r in results.values()))

# ── EQUITY CURVE COMPARISON CHART ─────────────────────────────────────────────

def make_curve(r):
    if len(r) == 0:
        return pd.DataFrame({'date': [pd.Timestamp('2022-01-01', tz='UTC')], 'balance': [INITIAL_BALANCE]})
    return pd.DataFrame({
        'date':    [r['entry_date'].iloc[0] - pd.Timedelta(days=1)] + r['exit_date'].tolist(),
        'balance': [INITIAL_BALANCE] + r['account'].tolist(),
    })

colors = ['#1f77b4','#2ca02c','#ff7f0e','#9467bd','#d62728']

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10),
                                gridspec_kw={'height_ratios':[3, 2]},
                                sharex=True)

for (label, _, _, _), color in zip(variants, colors):
    r = trade_dfs[label]
    c = make_curve(r)
    res = results[label]
    ax1.plot(c['date'], c['balance'], color=color, linewidth=1.5,
             label=f"{label}   +{res['return_pct']:.0f}%   DD {res['max_dd']:.1f}%   ({res['trades']} trades)")

ax1.axhline(INITIAL_BALANCE, color='gray', linestyle='--', alpha=0.5)
ax1.set_yscale('log')
ax1.set_ylabel('Account ($)  (log scale)', fontsize=11)
ax1.set_title(f"4-Unit Donchian Pyramid + Filter Variants  —  BTC 4H  Jan 2022 → {df.index[-1].date()}",
              fontsize=13, fontweight='bold')
ax1.legend(loc='upper left', fontsize=9)
ax1.grid(True, alpha=0.3)

for (label, _, _, _), color in zip(variants, colors):
    r = trade_dfs[label]
    c = make_curve(r)
    c['peak'] = c['balance'].cummax()
    c['dd']   = (c['balance'] - c['peak']) / c['peak'] * 100
    ax2.plot(c['date'], c['dd'], color=color, linewidth=1.0, label=label)

ax2.axhline(0, color='black', linewidth=0.5)
ax2.set_ylabel('Drawdown from peak (%)', fontsize=11)
ax2.set_xlabel('Date', fontsize=11)
ax2.set_title('Underwater Curves', fontsize=12)
ax2.legend(loc='lower left', fontsize=9)
ax2.grid(True, alpha=0.3)

for ax in [ax1, ax2]:
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

plt.tight_layout()
plt.savefig('filter_comparison.png', dpi=120, bbox_inches='tight')
print(f"\nChart saved -> filter_comparison.png")

# Year-by-year for each variant
print(f"\n{sep}")
print(f"  YEAR-BY-YEAR P&L (USD)")
print(sep)
yr_header = "  Year   " + "".join(f"{label:>20}" for label in results.keys())
print(yr_header)
years = sorted(set().union(*[r['exit_date'].dt.year.unique() for r in trade_dfs.values() if len(r) > 0]))
for yr in years:
    line = f"  {yr}   "
    for label in results.keys():
        r = trade_dfs[label]
        if len(r) > 0:
            p = r[r['exit_date'].dt.year == yr]['pnl_usd'].sum() if len(r) else 0
            line += f"{p:>+20,.2f}"
        else:
            line += f"{'-':>20}"
    print(line)
