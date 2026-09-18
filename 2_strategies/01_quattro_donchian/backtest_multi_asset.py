"""
LOCKED STRATEGY — 4-Unit Donchian Pyramid + EMA Slope Filter
─────────────────────────────────────────────────────────────
Entry filters (4H):
  - 4H close > previous 20-bar high (Donchian breakout)
  - 4H close > daily 200 EMA (price above long-term trend)
  - Daily 200 EMA > daily 200 EMA from 20 days ago (trend is rising)

Position management:
  - Initial position: risk 2% of account on 2*ATR(14) stop
  - Pyramid: add up to 3 more units at +0.5N, +1.0N, +1.5N (max 4 units)
  - Common trailing stop: trails up to (newest unit entry - 2N) — wick-based
  - 5% account hard stop — wick-based catastrophe backstop

Exit:
  - 4H close < previous 10-bar low → exit all units at next open

Run identical strategy on BTC, ETH, SOL — independent capital $1,839 each
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ── DATA FETCH ────────────────────────────────────────────────────────────────

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

ASSETS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']

# ── INDICATORS PER ASSET ──────────────────────────────────────────────────────

def prep_data(symbol):
    print(f"  {symbol}: fetching 4H...")
    raw_4h = fetch_full(symbol, '4h', since, exchange)
    df = pd.DataFrame(raw_4h, columns=['ts','open','high','low','close','volume'])
    df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.set_index('dt').drop(columns='ts')

    print(f"  {symbol}: fetching daily...")
    raw_d = fetch_full(symbol, '1d', since_d, exchange)
    df_d = pd.DataFrame(raw_d, columns=['ts','open','high','low','close','volume'])
    df_d['dt'] = pd.to_datetime(df_d['ts'], unit='ms', utc=True)
    df_d = df_d.set_index('dt').drop(columns='ts')

    df['donch_high_20'] = df['high'].rolling(20).max().shift(1)
    df['donch_low_10']  = df['low'].rolling(10).min().shift(1)

    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low']  - prev_close).abs(),
    ], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()

    df_d['ema200']        = df_d['close'].ewm(span=200, adjust=False).mean()
    df_d['ema200_20d']    = df_d['ema200'].shift(20)
    df_d['ema200_up']     = df_d['ema200'] > df_d['ema200_20d']

    df_d_avail = df_d[['ema200', 'ema200_up']].copy()
    df_d_avail.index = df_d_avail.index + pd.Timedelta(days=1)
    df_d_aligned = df_d_avail.reindex(df.index, method='ffill')
    df['d_ema200']    = df_d_aligned['ema200']
    df['d_ema200_up'] = df_d_aligned['ema200_up']
    df['regime_up']   = df['close'] > df['d_ema200']

    return df

# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────

INITIAL_BALANCE = 1839.17
RISK_PCT        = 0.02
HARD_STOP_PCT   = 0.05
PYRAMID_STEP    = 0.5
MAX_UNITS       = 4
MAX_LEVERAGE    = 20
WARMUP          = 250

def run_backtest(df):
    open_, high_, low_, close_ = df['open'].values, df['high'].values, df['low'].values, df['close'].values
    dhigh_ = df['donch_high_20'].values
    dlow_  = df['donch_low_10'].values
    atr_   = df['atr14'].values
    reg_   = df['regime_up'].values
    slope_ = df['d_ema200_up'].values
    dates_ = df.index
    n      = len(df)

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
            if not (close_[i] > dhigh_[i] and reg_[i]): continue
            if pd.isna(slope_[i]) or not slope_[i]: continue        # EMA slope filter

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

def compute_stats(r, final, name):
    if len(r) == 0:
        return {'asset': name, 'trades': 0, 'win_rate': 0, 'avg_win_R': 0, 'avg_loss_R': 0,
                'expectancy': 0, 'max_dd': 0, 'max_l': 0, 'max_w': 0, 'final': final,
                'return_pct': (final/INITIAL_BALANCE-1)*100, 'biggest': 0, 'worst': 0}
    wins = r[r['R_total'] > 0]; losses = r[r['R_total'] <= 0]
    curve = [INITIAL_BALANCE] + list(r['account'])
    peak = INITIAL_BALANCE; max_dd = 0.0
    for v in curve:
        if v > peak: peak = v
        dd = (v - peak)/peak*100
        if dd < max_dd: max_dd = dd
    max_w = max_l = cur_w = cur_l = 0
    for w in (r['R_total'] > 0):
        if w: cur_w += 1; cur_l = 0; max_w = max(max_w, cur_w)
        else: cur_l += 1; cur_w = 0; max_l = max(max_l, cur_l)
    return {
        'asset': name,
        'trades': len(r),
        'win_rate': len(wins)/len(r)*100 if len(r) else 0,
        'avg_win_R': wins['R_total'].mean() if len(wins) else 0,
        'avg_loss_R': losses['R_total'].mean() if len(losses) else 0,
        'expectancy': r['R_total'].mean(),
        'max_dd': max_dd, 'max_w': max_w, 'max_l': max_l, 'final': final,
        'return_pct': (final/INITIAL_BALANCE-1)*100,
        'biggest': r['R_total'].max() if len(r) else 0,
        'worst': r['R_total'].min() if len(r) else 0,
    }

# ── RUN ALL ASSETS ────────────────────────────────────────────────────────────

print("=== Fetching data and running backtests for all assets ===\n")
asset_results = {}
asset_trades  = {}
asset_data    = {}

for sym in ASSETS:
    short_name = sym.split('/')[0]
    print(f"--- {sym} ---")
    df = prep_data(sym)
    asset_data[short_name] = df
    print(f"  {sym}: running backtest...")
    r, final = run_backtest(df)
    asset_trades[short_name] = r
    asset_results[short_name] = compute_stats(r, final, short_name)
    print(f"  {sym}: {len(r)} trades, ${final:,.2f} final ({(final/INITIAL_BALANCE-1)*100:+.1f}%)\n")

# ── COMPARISON TABLE ──────────────────────────────────────────────────────────

sep = "─" * 80
print(f"\n{'═'*80}")
print(f"  STRATEGY: 4-Unit Donchian Pyramid + EMA Slope Filter   |   4H Timeframe")
print(f"  PERIOD:   Jan 2022 → 2026-05-16   |   Start: $1,839 per asset")
print(f"{'═'*80}")
print(f"  {'Metric':<28}{'BTC':>16}{'ETH':>16}{'SOL':>16}")
print(sep)

metric_rows = [
    ('Total trades',      'trades',     '{:>16}'),
    ('Win rate %',        'win_rate',   '{:>16.1f}'),
    ('Avg win (R)',       'avg_win_R',  '{:>+16.2f}'),
    ('Avg loss (R)',      'avg_loss_R', '{:>+16.2f}'),
    ('Expectancy (R)',    'expectancy', '{:>+16.3f}'),
    ('Max drawdown %',    'max_dd',     '{:>+16.2f}'),
    ('Max losing streak', 'max_l',      '{:>16}'),
    ('Max winning streak','max_w',      '{:>16}'),
    ('Final balance ($)', 'final',      '{:>16,.2f}'),
    ('Total return %',    'return_pct', '{:>+16.1f}'),
    ('Biggest winner (R)','biggest',    '{:>+16.2f}'),
    ('Worst loser (R)',   'worst',      '{:>+16.2f}'),
]

for label, key, fmt in metric_rows:
    line = f"  {label:<28}"
    for a in ['BTC', 'ETH', 'SOL']:
        v = asset_results[a][key]
        line += fmt.format(v)
    print(line)

# Return / DD ratio
line = f"  {'Return / DD ratio':<28}"
for a in ['BTC', 'ETH', 'SOL']:
    r = asset_results[a]
    ratio = abs(r['return_pct']/r['max_dd']) if r['max_dd'] != 0 else 0
    line += f"{ratio:>16.2f}"
print(line)

# ── YEAR-BY-YEAR ──────────────────────────────────────────────────────────────

print(f"\n{sep}")
print(f"  YEAR-BY-YEAR P&L (USD)")
print(sep)
print(f"  {'Year':<8}{'BTC':>16}{'ETH':>16}{'SOL':>16}")
years = set()
for a in asset_trades.values():
    if len(a) > 0:
        years.update(a['exit_date'].dt.year.unique())

for yr in sorted(years):
    line = f"  {yr:<8}"
    for a in ['BTC', 'ETH', 'SOL']:
        r = asset_trades[a]
        if len(r) > 0:
            p = r[r['exit_date'].dt.year == yr]['pnl_usd'].sum()
            line += f"{p:>+16,.2f}"
        else:
            line += f"{'-':>16}"
    print(line)

# Total
line = f"  {'TOTAL':<8}"
for a in ['BTC', 'ETH', 'SOL']:
    final = asset_results[a]['final']
    line += f"{final - INITIAL_BALANCE:>+16,.2f}"
print(line)

# ── CORRELATION OF EQUITY CURVES ──────────────────────────────────────────────

print(f"\n{sep}")
print(f"  EQUITY CURVE CORRELATIONS")
print(sep)

def make_curve(r, name):
    if len(r) == 0:
        return pd.DataFrame({'date':[pd.Timestamp('2022-01-01', tz='UTC')], name:[INITIAL_BALANCE]}).set_index('date')
    c = pd.DataFrame({
        'date':    r['exit_date'].tolist(),
        name:      r['account'].tolist(),
    }).set_index('date')
    c = c[~c.index.duplicated(keep='last')]
    return c

curves = {a: make_curve(asset_trades[a], a) for a in ['BTC', 'ETH', 'SOL']}
# Align all curves to a common daily index
all_dates = pd.date_range(start='2022-01-01', end='2026-05-16', freq='D', tz='UTC')
aligned = pd.DataFrame(index=all_dates)
for a in ['BTC', 'ETH', 'SOL']:
    c = curves[a].copy()
    c = c.resample('D').last().ffill()
    aligned[a] = c[a]
aligned = aligned.fillna(method='ffill').fillna(INITIAL_BALANCE)

returns = aligned.pct_change().dropna()
corr = returns.corr()
print(f"  {'':<8}{'BTC':>10}{'ETH':>10}{'SOL':>10}")
for a in ['BTC', 'ETH', 'SOL']:
    print(f"  {a:<8}" + "".join(f"{corr.loc[a,b]:>10.3f}" for b in ['BTC', 'ETH', 'SOL']))

# ── COMBINED PORTFOLIO (equal-weight across assets) ───────────────────────────

print(f"\n{sep}")
print(f"  COMBINED PORTFOLIO  (assuming $1,839 split into 3 = $613 per asset)")
print(sep)
combined_final = sum(asset_results[a]['final'] for a in ['BTC','ETH','SOL']) / 3
total_per_asset = INITIAL_BALANCE
combined_initial = total_per_asset
# If each asset runs with $613 base, scale results proportionally
combined_final_scaled = combined_final / 3  # average of three assets with full $1,839
# Actually the cleanest equivalent is: sum of trades from each asset on 1/3 of capital each
# Or: average return across the three assets (since each is independently scaled)
avg_return = sum(asset_results[a]['return_pct'] for a in ['BTC','ETH','SOL']) / 3
combined_balance_if_split = INITIAL_BALANCE * (1 + avg_return/100)
print(f"  Avg return across 3 assets:    {avg_return:+.1f}%")
print(f"  Equivalent balance ($1,839 → ): ${combined_balance_if_split:,.2f}")

# ── EQUITY CHART ──────────────────────────────────────────────────────────────

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10),
                                gridspec_kw={'height_ratios':[3, 2]},
                                sharex=True)

colors = {'BTC':'#f7931a', 'ETH':'#627eea', 'SOL':'#9945ff'}

for a in ['BTC', 'ETH', 'SOL']:
    r = asset_trades[a]
    res = asset_results[a]
    if len(r) > 0:
        c = pd.DataFrame({
            'date':    [r['entry_date'].iloc[0] - pd.Timedelta(days=1)] + r['exit_date'].tolist(),
            'balance': [INITIAL_BALANCE] + r['account'].tolist(),
        })
        c['peak'] = c['balance'].cummax()
        c['dd']   = (c['balance'] - c['peak']) / c['peak'] * 100
        ax1.plot(c['date'], c['balance'], color=colors[a], linewidth=1.5,
                 label=f"{a}  +{res['return_pct']:.0f}%  DD {res['max_dd']:.1f}%  ({res['trades']} trades)")
        ax2.plot(c['date'], c['dd'], color=colors[a], linewidth=1.0, label=a)

ax1.axhline(INITIAL_BALANCE, color='gray', linestyle='--', alpha=0.5)
ax1.set_yscale('log')
ax1.set_ylabel('Account ($) — log scale', fontsize=11)
ax1.set_title(f"4-Unit Donchian Pyramid + EMA Slope Filter — BTC / ETH / SOL — Jan 2022 → May 2026",
              fontsize=13, fontweight='bold')
ax1.legend(loc='upper left', fontsize=10)
ax1.grid(True, alpha=0.3)

ax2.axhline(0, color='black', linewidth=0.5)
ax2.set_ylabel('Drawdown from peak (%)', fontsize=11)
ax2.set_xlabel('Date', fontsize=11)
ax2.set_title('Underwater Curves', fontsize=12)
ax2.legend(loc='lower left', fontsize=10)
ax2.grid(True, alpha=0.3)

for ax in [ax1, ax2]:
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

plt.tight_layout()
plt.savefig('multi_asset_comparison.png', dpi=120, bbox_inches='tight')
print(f"\nChart saved -> multi_asset_comparison.png")

for a in ['BTC', 'ETH', 'SOL']:
    if len(asset_trades[a]) > 0:
        asset_trades[a].to_csv(f'backtest_locked_{a}_results.csv', index=False)
print(f"Trade logs saved -> backtest_locked_BTC_results.csv, backtest_locked_ETH_results.csv, backtest_locked_SOL_results.csv")
