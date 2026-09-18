"""
5 EMA TREND FILTER on BTC — 1D / 5D / 1W timeframes, 2018-present.

Rule:
  - Long when close > 5 EMA, enter at next bar's open
  - Exit when close < 5 EMA, exit at next bar's open
  - 100% of account each entry (1x, all-in)
  - Long-only, flat when below
  - Fees: 0.10% per leg
  - Benchmark: buy-and-hold BTC

Test period: 2018-01-01 → today. Captures the 2018 bear AND 2022 bear markets.
"""
import os, pickle
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

INITIAL_CAPITAL = 1839.17
FEE_PER_LEG     = 0.0010
START_DATE      = '2018-01-01T00:00:00Z'
CACHE_FILE      = '../../1_data/btc_1d_cache.pkl'

# ── DATA ─────────────────────────────────────────────────────────────────────
def fetch_full(symbol, timeframe, since_ms, exchange):
    out = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        out.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return out

if os.path.exists(CACHE_FILE):
    print(f"Loading cached BTC 1D from {CACHE_FILE}...")
    with open(CACHE_FILE, 'rb') as f:
        btc_1d = pickle.load(f)
else:
    print("Fetching BTC 1D from Binance...")
    ex = ccxt.binance()
    since = ex.parse8601(START_DATE)
    raw = fetch_full('BTC/USDT', '1d', since, ex)
    btc_1d = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
    btc_1d['dt'] = pd.to_datetime(btc_1d['ts'], unit='ms', utc=True)
    btc_1d = btc_1d.set_index('dt').drop(columns='ts').sort_index()
    btc_1d = btc_1d[~btc_1d.index.duplicated(keep='last')]
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(btc_1d, f)

print(f"BTC 1D: {len(btc_1d)} bars, from {btc_1d.index[0].date()} to {btc_1d.index[-1].date()}")

# Resample to 5D and 1W
def resample_ohlcv(df, rule):
    return df.resample(rule, label='right', closed='right').agg({
        'open':'first','high':'max','low':'min','close':'last','volume':'sum'
    }).dropna()

btc_5d = resample_ohlcv(btc_1d, '5D')
btc_1w = resample_ohlcv(btc_1d, 'W-MON')
print(f"BTC 5D: {len(btc_5d)} bars")
print(f"BTC 1W: {len(btc_1w)} bars")

# ── BACKTEST ENGINE ─────────────────────────────────────────────────────────
def run_5ema(df):
    """Long when close > EMA5; flat otherwise. Entries/exits at NEXT bar's open."""
    df = df.copy()
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    df['signal'] = df['close'] > df['ema5']    # at bar i, close vs ema5

    account = INITIAL_CAPITAL
    in_position = False
    units = 0.0
    trades = []
    eq_history = []
    entry_price = None
    entry_date = None

    for i in range(len(df)):
        bar = df.iloc[i]
        date = df.index[i]
        # Update equity at end of bar
        if in_position:
            mark_value = units * bar['close']
            eq_history.append({'date': date, 'equity': mark_value, 'in_pos': 1})
        else:
            eq_history.append({'date': date, 'equity': account, 'in_pos': 0})

        # Decide action based on bar i's signal; execute at bar i+1 open
        if i+1 >= len(df): continue
        next_open = df.iloc[i+1]['open']
        next_date = df.index[i+1]

        if not in_position and bar['signal']:
            # ENTER long at next open
            entry_fee = account * FEE_PER_LEG
            account_after_fee = account - entry_fee
            units = account_after_fee / next_open
            entry_price = next_open
            entry_date = next_date
            in_position = True

        elif in_position and not bar['signal']:
            # EXIT at next open
            gross = units * next_open
            exit_fee = gross * FEE_PER_LEG
            account = gross - exit_fee
            ret_pct = (account / (INITIAL_CAPITAL if not trades else trades[-1]['account_after']) - 1)
            trades.append({
                'entry_date': entry_date, 'exit_date': next_date,
                'entry': entry_price, 'exit': next_open,
                'pnl': account - (trades[-1]['account_after'] if trades else INITIAL_CAPITAL),
                'ret_pct': (next_open/entry_price - 1) * 100,
                'account_after': account,
                'duration_d': (next_date - entry_date).days,
            })
            in_position = False
            units = 0.0
            entry_price = None
            entry_date = None

    # Close any open position at last close
    if in_position:
        last = df.iloc[-1]
        gross = units * last['close']
        exit_fee = gross * FEE_PER_LEG
        account = gross - exit_fee
        trades.append({
            'entry_date': entry_date, 'exit_date': df.index[-1],
            'entry': entry_price, 'exit': last['close'],
            'pnl': account - (trades[-1]['account_after'] if trades else INITIAL_CAPITAL),
            'ret_pct': (last['close']/entry_price - 1) * 100,
            'account_after': account,
            'duration_d': (df.index[-1] - entry_date).days,
        })

    return pd.DataFrame(trades), pd.DataFrame(eq_history).set_index('date'), df

def metrics(trades, eq, df, label):
    if len(trades) == 0:
        return None
    wins = trades[trades['ret_pct'] > 0]
    losses = trades[trades['ret_pct'] <= 0]
    sorted_trades = trades.sort_values('entry_date').reset_index(drop=True)
    # Walk through bars and reconstruct equity (account when flat, mark-to-market when in pos)
    real_eq = [INITIAL_CAPITAL]
    real_dates = [df.index[0]]
    cur_acct = INITIAL_CAPITAL
    in_pos = False
    units_h = 0.0
    cur_t = 0
    for i in range(len(df)):
        bar = df.iloc[i]
        d = df.index[i]
        # Apply trades chronologically
        while cur_t < len(sorted_trades) and sorted_trades.iloc[cur_t]['entry_date'] <= d and not in_pos:
            t = sorted_trades.iloc[cur_t]
            entry_fee = cur_acct * FEE_PER_LEG
            units_h = (cur_acct - entry_fee) / t['entry']
            in_pos = True
            break
        if in_pos:
            cur_eq = units_h * bar['close']
            t = sorted_trades.iloc[cur_t]
            if d >= t['exit_date']:
                cur_acct = t['account_after']
                in_pos = False
                units_h = 0.0
                cur_t += 1
                cur_eq = cur_acct
        else:
            cur_eq = cur_acct
        real_eq.append(cur_eq)
        real_dates.append(d)

    eq_series = pd.Series(real_eq[1:], index=real_dates[1:])
    final = eq_series.iloc[-1]
    peak = INITIAL_CAPITAL; mdd = 0
    for v in eq_series:
        if v > peak: peak = v
        d = (v - peak)/peak*100
        if d < mdd: mdd = d
    days = (df.index[-1] - df.index[0]).days
    apy = ((final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    time_in_market = ((eq_series.values[1:] - eq_series.values[:-1] != 0).mean() if len(eq_series)>1 else 0)
    # better: count bars where signal was true
    bars_in = df['signal'].sum(); total_bars = len(df)

    return {
        'label': label,
        'trades': len(trades), 'wins': len(wins), 'wr': len(wins)/len(trades)*100,
        'avg_win': wins['ret_pct'].mean() if len(wins) else 0,
        'avg_loss': losses['ret_pct'].mean() if len(losses) else 0,
        'best': trades['ret_pct'].max(),
        'worst': trades['ret_pct'].min(),
        'avg_dur': trades['duration_d'].mean(),
        'final': final, 'mdd': mdd, 'apy': apy,
        'days': days, 'time_in_pct': bars_in/total_bars*100,
        'eq_series': eq_series,
    }

# Buy-and-hold benchmark
def bh_metrics(df):
    fee = INITIAL_CAPITAL * FEE_PER_LEG
    units = (INITIAL_CAPITAL - fee) / df['open'].iloc[1]
    eq = pd.Series(units * df['close'].values, index=df.index)
    final = eq.iloc[-1] - (eq.iloc[-1] * FEE_PER_LEG)   # exit fee
    peak = INITIAL_CAPITAL; mdd = 0
    for v in eq:
        if v > peak: peak = v
        d = (v - peak)/peak*100
        if d < mdd: mdd = d
    days = (df.index[-1] - df.index[0]).days
    apy = ((final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    return {'final': final, 'mdd': mdd, 'apy': apy, 'eq_series': eq}

# ── RUN ALL TIMEFRAMES ──────────────────────────────────────────────────────
results = {}
for label, df in [('1D', btc_1d), ('5D', btc_5d), ('1W', btc_1w)]:
    trades, _, df_with_sig = run_5ema(df)
    m = metrics(trades, None, df_with_sig, label)
    bh = bh_metrics(df_with_sig)
    results[label] = {'m': m, 'bh': bh, 'trades': trades, 'df': df_with_sig}

# ── PRINT ───────────────────────────────────────────────────────────────────
sep = "─" * 120
print(f"\n{'═'*120}")
print(f"  5 EMA TREND FILTER on BTC — 2018 to {btc_1d.index[-1].date()}")
print(f"  Start ${INITIAL_CAPITAL:,.0f}, 1x all-in, long/flat, 0.10% fees per leg")
print(f"{'═'*120}")
print(f"  {'TF':<5}{'Trades':>8}{'Wins':>6}{'WR%':>7}{'AvgWin%':>10}{'AvgLoss%':>10}{'Best%':>9}{'Worst%':>9}{'AvgDur':>8}{'TimeIn%':>9}{'Final$':>11}{'APY%':>9}{'MaxDD%':>9}")
print(sep)
for label, df in [('1D', btc_1d), ('5D', btc_5d), ('1W', btc_1w)]:
    m = results[label]['m']
    print(f"  {label:<5}{m['trades']:>8}{m['wins']:>6}{m['wr']:>7.1f}{m['avg_win']:>+10.2f}{m['avg_loss']:>+10.2f}{m['best']:>+9.1f}{m['worst']:>+9.1f}{m['avg_dur']:>8.1f}{m['time_in_pct']:>9.1f}{m['final']:>11,.0f}{m['apy']:>+9.1f}{m['mdd']:>+9.1f}")
# Benchmark
print(sep)
bh = results['1D']['bh']
print(f"  {'B&H':<5}{'-':>8}{'-':>6}{'-':>7}{'-':>10}{'-':>10}{'-':>9}{'-':>9}{'-':>8}{100.0:>9.1f}{bh['final']:>11,.0f}{bh['apy']:>+9.1f}{bh['mdd']:>+9.1f}")

# ── BEAR MARKET PERFORMANCE ─────────────────────────────────────────────────
print(f"\n{'═'*120}")
print(f"  BEAR-MARKET BEHAVIOR — how did the strategy handle 2018 and 2022 crashes?")
print(f"{'═'*120}")

bear_periods = [
    ('2018 bear', pd.Timestamp('2018-01-15', tz='UTC'), pd.Timestamp('2018-12-31', tz='UTC')),
    ('2022 bear', pd.Timestamp('2022-01-01', tz='UTC'), pd.Timestamp('2022-12-31', tz='UTC')),
]

for bname, bstart, bend in bear_periods:
    print(f"\n  ▶ {bname} ({bstart.date()} → {bend.date()})")
    for tf in ['1D','5D','1W']:
        eq_s = results[tf]['m']['eq_series']
        eq_b = results[tf]['bh']['eq_series']
        eq_s_b = eq_s[(eq_s.index >= bstart) & (eq_s.index <= bend)]
        eq_b_b = eq_b[(eq_b.index >= bstart) & (eq_b.index <= bend)]
        if len(eq_s_b) < 2 or len(eq_b_b) < 2: continue
        s_ret = (eq_s_b.iloc[-1]/eq_s_b.iloc[0] - 1) * 100
        b_ret = (eq_b_b.iloc[-1]/eq_b_b.iloc[0] - 1) * 100
        # DD inside period
        s_peak = eq_s_b.cummax(); s_dd = ((eq_s_b - s_peak)/s_peak*100).min()
        b_peak = eq_b_b.cummax(); b_dd = ((eq_b_b - b_peak)/b_peak*100).min()
        trades_in_bear = results[tf]['trades'][
            (results[tf]['trades']['entry_date'] >= bstart) &
            (results[tf]['trades']['entry_date'] <= bend)
        ]
        wr_b = (trades_in_bear['ret_pct']>0).mean()*100 if len(trades_in_bear) else 0
        print(f"     {tf}: strat {s_ret:>+7.1f}% (DD {s_dd:>+6.1f}%), B&H {b_ret:>+7.1f}% (DD {b_dd:>+6.1f}%)  |  {len(trades_in_bear)} trades, WR {wr_b:.0f}%")

# ── YEAR-BY-YEAR ────────────────────────────────────────────────────────────
print(f"\n{'═'*120}")
print(f"  YEAR-BY-YEAR (1D timeframe, the most active)")
print(f"{'═'*120}")
trades_1d = results['1D']['trades'].copy()
trades_1d['year'] = pd.to_datetime(trades_1d['exit_date']).dt.year
eq_1d = results['1D']['m']['eq_series']
eq_bh = results['1D']['bh']['eq_series']
print(f"  {'Year':<6}{'Trades':>8}{'WR%':>7}{'AvgWin%':>10}{'AvgLoss%':>10}{'Strat$':>11}{'StratRet%':>11}{'BH$':>11}{'BHRet%':>11}")
print(sep)
for yr in sorted(trades_1d['year'].unique()):
    g = trades_1d[trades_1d['year']==yr]
    wins = g[g['ret_pct']>0]; losses = g[g['ret_pct']<=0]
    yr_start = pd.Timestamp(f'{yr}-01-01', tz='UTC')
    yr_end   = pd.Timestamp(f'{yr}-12-31', tz='UTC')
    eq_yr = eq_1d[(eq_1d.index >= yr_start) & (eq_1d.index <= yr_end)]
    eq_bh_yr = eq_bh[(eq_bh.index >= yr_start) & (eq_bh.index <= yr_end)]
    if len(eq_yr) < 2 or len(eq_bh_yr) < 2: continue
    s_ret = (eq_yr.iloc[-1]/eq_yr.iloc[0] - 1) * 100
    bh_ret = (eq_bh_yr.iloc[-1]/eq_bh_yr.iloc[0] - 1) * 100
    print(f"  {yr:<6}{len(g):>8}{(g['ret_pct']>0).mean()*100:>7.1f}{wins['ret_pct'].mean() if len(wins) else 0:>+10.2f}{losses['ret_pct'].mean() if len(losses) else 0:>+10.2f}"
          f"{eq_yr.iloc[-1]:>11,.0f}{s_ret:>+11.1f}{eq_bh_yr.iloc[-1]:>11,.0f}{bh_ret:>+11.1f}")

# ── CHART ────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(15, 13), sharex=True)
for i, (tf, color) in enumerate([('1D','#1f77b4'),('5D','#ff7f0e'),('1W','#2ca02c')]):
    ax = axes[i]
    eq_s = results[tf]['m']['eq_series']
    eq_b = results[tf]['bh']['eq_series']
    m = results[tf]['m']; bh = results[tf]['bh']
    ax.plot(eq_s.index, eq_s.values, color=color, linewidth=1.7,
            label=f"5 EMA {tf} strategy:  {m['final']:,.0f}  ({m['apy']:+.1f}% APY, DD {m['mdd']:+.1f}%, {m['trades']} trades)")
    ax.plot(eq_b.index, eq_b.values, color='gray', linewidth=1.3, alpha=0.7, linestyle='--',
            label=f"BTC buy-and-hold:    {bh['final']:,.0f}  ({bh['apy']:+.1f}% APY, DD {bh['mdd']:+.1f}%)")
    # Shade bear markets
    for bn, bs, be in bear_periods:
        ax.axvspan(bs, be, alpha=0.08, color='red')
    ax.axhline(INITIAL_CAPITAL, color='black', linestyle=':', alpha=0.4)
    ax.set_ylabel('Account (USD)')
    ax.set_yscale('log')
    ax.set_title(f'5 EMA on BTC {tf} — strategy vs buy-and-hold (red bands = bear markets)', fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3, which='both')

axes[2].xaxis.set_major_locator(mdates.YearLocator())
axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
plt.tight_layout()
plt.savefig('btc_5ema.png', dpi=130, bbox_inches='tight')
print(f"\nChart -> btc_5ema.png")
