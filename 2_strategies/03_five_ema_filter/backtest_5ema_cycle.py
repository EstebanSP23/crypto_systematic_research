"""
5 EMA + 4-YEAR CYCLE OVERLAY on BTC, 2018-now, 1D/5D/1W.

Cycle map (Bitcoin halving cycle):
  BEAR years: 2018, 2022, 2026   → SHORT mode (open short on close < EMA5, close on close > EMA5)
  BULL years: 2019, 2020, 2021, 2023, 2024, 2025 → LONG mode (open long on close > EMA5, close on close < EMA5)

Comparison set:
  V0: Long-only 5 EMA (baseline, what we already ran)
  V1: Long-only + skip bear years entirely (sit flat in 2018/2022/2026)
  V2: Combined long-in-bull / short-in-bear (USER REQUEST)
  V3: Short-only in bear years (just to see what shorts alone do)
  BH: BTC buy-and-hold

100% all-in, 0.10% per leg fees, no funding (cash-only, would be different on perps).
"""
import os, pickle
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

INITIAL_CAPITAL = 1839.17
FEE_PER_LEG     = 0.0010
BEAR_YEARS      = {2018, 2022, 2026}

with open('../../1_data/btc_1d_cache.pkl','rb') as f:
    btc_1d = pickle.load(f)

def resample_ohlcv(df, rule):
    return df.resample(rule, label='right', closed='right').agg({
        'open':'first','high':'max','low':'min','close':'last','volume':'sum'
    }).dropna()

btc_5d = resample_ohlcv(btc_1d, '5D')
btc_1w = resample_ohlcv(btc_1d, 'W-MON')

def add_ema(df):
    df = df.copy()
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    return df

def run(df, variant):
    """
    variant:
      'long_only'      = long when close>ema5, flat otherwise (V0)
      'long_skip_bear' = same but skip bear years entirely (V1)
      'cycle_combo'    = long in bull years, short in bear years (V2)
      'short_bear'     = short in bear years only, flat otherwise (V3)
    """
    df = add_ema(df)
    account = INITIAL_CAPITAL
    pos = None  # None, 'long', 'short'
    units = 0.0
    entry_px = None; entry_date = None
    trades = []
    eq_history = []

    for i in range(len(df)):
        bar = df.iloc[i]
        date = df.index[i]
        year = date.year
        close = bar['close']; ema5 = bar['ema5']

        # mark-to-market equity
        if pos == 'long':
            cur_eq = units * close
        elif pos == 'short':
            cur_eq = units * (2 * entry_px - close)   # (entry-(close-entry)) * units
        else:
            cur_eq = account
        eq_history.append({'date': date, 'equity': cur_eq, 'pos': pos or 'flat'})

        if i+1 >= len(df): continue
        next_open = df.iloc[i+1]['open']
        next_date = df.index[i+1]
        next_year = next_date.year

        # Determine intended position type for THIS BAR's signal
        if variant == 'long_only':
            target = 'long' if close > ema5 else None
        elif variant == 'long_skip_bear':
            if year in BEAR_YEARS:
                target = None
            else:
                target = 'long' if close > ema5 else None
        elif variant == 'cycle_combo':
            if year in BEAR_YEARS:
                target = 'short' if close < ema5 else None
            else:
                target = 'long' if close > ema5 else None
        elif variant == 'short_bear':
            if year in BEAR_YEARS:
                target = 'short' if close < ema5 else None
            else:
                target = None
        else:
            target = None

        # If position type doesn't match target → exit
        if pos is not None and pos != target:
            # Close at next open
            if pos == 'long':
                gross = units * next_open
                fee = gross * FEE_PER_LEG
                account = gross - fee
                ret = (next_open / entry_px - 1) * 100
            else:  # short
                # cash settlement: profit = (entry - exit) per unit
                gross = units * entry_px + units * (entry_px - next_open)
                fee = units * next_open * FEE_PER_LEG
                account = gross - fee
                ret = (entry_px / next_open - 1) * 100
            trades.append({
                'side': pos, 'entry_date': entry_date, 'exit_date': next_date,
                'entry': entry_px, 'exit': next_open, 'ret_pct': ret,
                'pnl': account - (trades[-1]['account_after'] if trades else INITIAL_CAPITAL),
                'account_after': account,
                'duration_d': (next_date - entry_date).days,
                'year': entry_date.year,
            })
            pos = None; units = 0; entry_px = None; entry_date = None

        # Open new if target set and currently flat
        if pos is None and target is not None:
            fee = account * FEE_PER_LEG
            account_after = account - fee
            units = account_after / next_open
            entry_px = next_open; entry_date = next_date
            pos = target

    # Close any open position
    if pos is not None:
        last_close = df.iloc[-1]['close']
        if pos == 'long':
            gross = units * last_close
            fee = gross * FEE_PER_LEG
            account = gross - fee
            ret = (last_close/entry_px - 1) * 100
        else:
            gross = units * entry_px + units * (entry_px - last_close)
            fee = units * last_close * FEE_PER_LEG
            account = gross - fee
            ret = (entry_px/last_close - 1) * 100
        trades.append({
            'side': pos, 'entry_date': entry_date, 'exit_date': df.index[-1],
            'entry': entry_px, 'exit': last_close, 'ret_pct': ret,
            'pnl': account - (trades[-1]['account_after'] if trades else INITIAL_CAPITAL),
            'account_after': account,
            'duration_d': (df.index[-1] - entry_date).days,
            'year': entry_date.year,
        })
    return pd.DataFrame(trades), pd.DataFrame(eq_history).set_index('date')

def bh(df):
    df = df.dropna()
    fee = INITIAL_CAPITAL * FEE_PER_LEG
    units = (INITIAL_CAPITAL - fee) / df['open'].iloc[1]
    eq = pd.Series(units * df['close'].values, index=df.index)
    return eq

def stats(trades, eq, df):
    if len(trades) == 0:
        return {'trades':0,'wr':0,'final':INITIAL_CAPITAL,'apy':0,'mdd':0,'eq':eq}
    final = eq.iloc[-1]
    peak = INITIAL_CAPITAL; mdd = 0
    for v in eq.values:
        if v > peak: peak = v
        d = (v-peak)/peak*100
        if d < mdd: mdd = d
    days = (df.index[-1] - df.index[0]).days
    apy = ((final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    return {
        'trades': len(trades),
        'wr': (trades['ret_pct']>0).mean()*100,
        'avg_win': trades[trades['ret_pct']>0]['ret_pct'].mean() if (trades['ret_pct']>0).any() else 0,
        'avg_loss': trades[trades['ret_pct']<=0]['ret_pct'].mean() if (trades['ret_pct']<=0).any() else 0,
        'best': trades['ret_pct'].max(),
        'worst': trades['ret_pct'].min(),
        'final': final, 'apy': apy, 'mdd': mdd,
        'eq': eq,
    }

# Run across timeframes and variants
data_tf = [('1D', btc_1d), ('5D', btc_5d), ('1W', btc_1w)]
variants = ['long_only','long_skip_bear','cycle_combo','short_bear']
labels = {
    'long_only': 'V0 long-only',
    'long_skip_bear': 'V1 long, skip bear years',
    'cycle_combo': 'V2 long-bull / short-bear',
    'short_bear': 'V3 short-only in bear years',
}

results = {}
for tf, df in data_tf:
    results[tf] = {}
    for v in variants:
        trades, eq = run(df, v)
        results[tf][v] = stats(trades, eq, df)
        results[tf][v]['trades_df'] = trades
    bh_eq = bh(df)
    bh_final = bh_eq.iloc[-1]
    peak = INITIAL_CAPITAL; mdd = 0
    for x in bh_eq.values:
        if x > peak: peak = x
        d = (x-peak)/peak*100
        if d < mdd: mdd = d
    days = (df.index[-1] - df.index[0]).days
    bh_apy = ((bh_final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1)*100
    results[tf]['bh'] = {'final':bh_final,'apy':bh_apy,'mdd':mdd,'eq':bh_eq}

# ── PRINT FULL COMPARISON ──
sep = "─" * 120
for tf, _ in data_tf:
    print(f"\n{'═'*120}")
    print(f"  TIMEFRAME = {tf}")
    print(f"{'═'*120}")
    print(f"  {'Variant':<30}{'Trades':>8}{'WR%':>7}{'AvgWin%':>10}{'AvgLoss%':>10}{'Best%':>9}{'Worst%':>9}{'Final$':>11}{'APY%':>9}{'MaxDD%':>9}")
    print(sep)
    for v in variants:
        s = results[tf][v]
        print(f"  {labels[v]:<30}{s['trades']:>8}{s['wr']:>7.1f}{s['avg_win']:>+10.2f}{s['avg_loss']:>+10.2f}{s['best']:>+9.1f}{s['worst']:>+9.1f}{s['final']:>11,.0f}{s['apy']:>+9.1f}{s['mdd']:>+9.1f}")
    bh_s = results[tf]['bh']
    print(sep)
    print(f"  {'BTC buy-and-hold':<30}{'-':>8}{'-':>7}{'-':>10}{'-':>10}{'-':>9}{'-':>9}{bh_s['final']:>11,.0f}{bh_s['apy']:>+9.1f}{bh_s['mdd']:>+9.1f}")

# ── YEAR-BY-YEAR FOR V2 (the headline) on 1W timeframe ──
print(f"\n{'═'*120}")
print(f"  YEAR-BY-YEAR V2 (cycle combo) on 1W — what happened each year?")
print(f"{'═'*120}")
print(f"  {'Year':<6}{'Mode':<8}{'Trades':>8}{'WR%':>7}{'AvgRet%':>10}{'Total ret%':>13}{'Year P&L$':>13}")
print(sep)
trades_1w = results['1W']['cycle_combo']['trades_df'].copy()
eq_1w = results['1W']['cycle_combo']['eq']
trades_1w['exit_year'] = pd.to_datetime(trades_1w['exit_date']).dt.year
for yr in sorted(set(trades_1w['year'].unique()) | set(trades_1w['exit_year'].unique())):
    if pd.isna(yr): continue
    yr = int(yr)
    g = trades_1w[trades_1w['exit_year'] == yr]
    mode = 'SHORT' if yr in BEAR_YEARS else 'LONG'
    yr_start = pd.Timestamp(f'{yr}-01-01', tz='UTC')
    yr_end   = pd.Timestamp(f'{yr}-12-31', tz='UTC')
    eq_yr = eq_1w[(eq_1w.index >= yr_start) & (eq_1w.index <= yr_end)]
    if len(eq_yr) < 2: continue
    yr_ret = (eq_yr.iloc[-1]/eq_yr.iloc[0] - 1) * 100
    yr_pnl = eq_yr.iloc[-1] - eq_yr.iloc[0]
    if len(g) > 0:
        wr = (g['ret_pct']>0).mean()*100
        avg = g['ret_pct'].mean()
        print(f"  {yr:<6}{mode:<8}{len(g):>8}{wr:>7.1f}{avg:>+10.2f}{yr_ret:>+13.1f}{yr_pnl:>+13,.0f}")
    else:
        print(f"  {yr:<6}{mode:<8}{0:>8}{'-':>7}{'-':>10}{yr_ret:>+13.1f}{yr_pnl:>+13,.0f}")

# ── DID THE SHORTS ACTUALLY WORK? ──
print(f"\n{'═'*120}")
print(f"  SHORT TRADE PERFORMANCE — V2 cycle_combo, all TFs")
print(f"{'═'*120}")
print(f"  {'TF':<5}{'Short trades':>14}{'Short WR%':>11}{'Avg short ret%':>16}{'Total short ret%':>18}")
print(sep)
for tf, _ in data_tf:
    t = results[tf]['cycle_combo']['trades_df']
    shorts = t[t['side']=='short']
    longs = t[t['side']=='long']
    if len(shorts) > 0:
        print(f"  {tf:<5}{len(shorts):>14}{(shorts['ret_pct']>0).mean()*100:>11.1f}{shorts['ret_pct'].mean():>+16.2f}{shorts['ret_pct'].sum():>+18.1f}")

# ── CHART ──
fig, axes = plt.subplots(3, 1, figsize=(15, 13), sharex=True)
colors = {'long_only':'#1f77b4','long_skip_bear':'#9467bd','cycle_combo':'#d62728','short_bear':'#ff7f0e'}
for idx, (tf, df) in enumerate(data_tf):
    ax = axes[idx]
    for v in variants:
        s = results[tf][v]
        ax.plot(s['eq'].index, s['eq'].values, color=colors[v], linewidth=1.7 if v=='cycle_combo' else 1.2,
                alpha=1.0 if v=='cycle_combo' else 0.75,
                label=f"{labels[v]}: {s['final']:,.0f} ({s['apy']:+.1f}% APY, DD {s['mdd']:+.0f}%)")
    bh_s = results[tf]['bh']
    ax.plot(bh_s['eq'].index, bh_s['eq'].values, color='gray', linewidth=1.0, alpha=0.7, linestyle='--',
            label=f"BTC B&H: {bh_s['final']:,.0f} ({bh_s['apy']:+.1f}% APY, DD {bh_s['mdd']:+.0f}%)")
    # Shade bear years
    for yr in BEAR_YEARS:
        ax.axvspan(pd.Timestamp(f'{yr}-01-01', tz='UTC'), pd.Timestamp(f'{yr}-12-31', tz='UTC'),
                   alpha=0.1, color='red')
    ax.axhline(INITIAL_CAPITAL, color='black', linestyle=':', alpha=0.4)
    ax.set_ylabel('Account (USD)')
    ax.set_yscale('log')
    ax.set_title(f'5 EMA on BTC {tf} — long-only vs cycle overlay (red bands = designated bear years)', fontweight='bold')
    ax.legend(loc='upper left', fontsize=8)
    ax.grid(True, alpha=0.3, which='both')

axes[2].xaxis.set_major_locator(mdates.YearLocator())
axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
plt.tight_layout()
plt.savefig('btc_5ema_cycle.png', dpi=130, bbox_inches='tight')
print(f"\nChart -> btc_5ema_cycle.png")
