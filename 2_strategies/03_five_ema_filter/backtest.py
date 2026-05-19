"""
5 EMA + 200 EMA SLOPE FILTER on BTC, 2018-now, 1D/5D/1W.

Filter (Quattro-style, forward-computable):
  daily_EMA_200[today] > daily_EMA_200[20 days ago]   →  trending UP
  daily_EMA_200[today] < daily_EMA_200[20 days ago]   →  trending DOWN
  Filter is always computed on DAILY data, then read at higher-TF bar timestamp.

Variants:
  V0: long-only 5 EMA, no filter             (baseline)
  V1: long-only 5 EMA, gated by filter (uptrend only)
  V2: long when uptrend, short when downtrend  (USER REQUEST, filter-driven)
  V3: hindsight cycle (long bull years / short bear years 2018,22,26) — reference only

100% all-in, 0.10% per leg, no funding cost. Compared against BTC B&H.
"""
import os, pickle
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

INITIAL_CAPITAL = 1839.17
FEE_PER_LEG     = 0.0010
HINDSIGHT_BEAR_YEARS = {2018, 2022, 2026}
CACHE = 'btc_1d_2017_cache.pkl'

# ── DATA (fetch from 2017 for EMA200 warmup) ─────────────────────────────────
if os.path.exists(CACHE):
    with open(CACHE,'rb') as f: btc_1d = pickle.load(f)
    print(f"Loaded cache: {len(btc_1d)} bars, {btc_1d.index[0].date()} → {btc_1d.index[-1].date()}")
else:
    print("Fetching BTC 1D from 2017-01-01...")
    ex = ccxt.binance()
    since = ex.parse8601('2017-01-01T00:00:00Z')
    out = []
    while True:
        batch = ex.fetch_ohlcv('BTC/USDT','1d', since=since, limit=1000)
        if not batch: break
        out.extend(batch); since = batch[-1][0]+1
        if len(batch) < 1000: break
    btc_1d = pd.DataFrame(out, columns=['ts','open','high','low','close','volume'])
    btc_1d['dt'] = pd.to_datetime(btc_1d['ts'], unit='ms', utc=True)
    btc_1d = btc_1d.set_index('dt').drop(columns='ts').sort_index()
    btc_1d = btc_1d[~btc_1d.index.duplicated(keep='last')]
    with open(CACHE,'wb') as f: pickle.dump(btc_1d, f)
    print(f"Saved: {len(btc_1d)} bars")

# Compute daily 200 EMA slope filter
btc_1d['ema200_d'] = btc_1d['close'].ewm(span=200, adjust=False).mean()
btc_1d['ema200_d_lag20'] = btc_1d['ema200_d'].shift(20)
btc_1d['uptrend'] = btc_1d['ema200_d'] > btc_1d['ema200_d_lag20']
# Build filter lookup series at midnight UTC
filter_series = btc_1d['uptrend']

def resample_ohlcv(df, rule):
    return df.resample(rule, label='right', closed='right').agg({
        'open':'first','high':'max','low':'min','close':'last','volume':'sum'
    }).dropna()

btc_5d = resample_ohlcv(btc_1d[['open','high','low','close','volume']], '5D')
btc_1w = resample_ohlcv(btc_1d[['open','high','low','close','volume']], 'W-MON')

# Truncate everything to start from 2018-01-01 (post-warmup)
START_TEST = pd.Timestamp('2018-01-01', tz='UTC')
btc_1d_test = btc_1d[btc_1d.index >= START_TEST].copy()
btc_5d_test = btc_5d[btc_5d.index >= START_TEST].copy()
btc_1w_test = btc_1w[btc_1w.index >= START_TEST].copy()

def get_filter_at(date):
    """Look up the most recent daily uptrend value at or before 'date'."""
    valid = filter_series[filter_series.index <= date]
    if len(valid) == 0: return None
    return bool(valid.iloc[-1])

def add_ema5(df):
    df = df.copy()
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    return df

def run(df, variant):
    df = add_ema5(df)
    account = INITIAL_CAPITAL
    pos = None
    units = 0.0; entry_px = None; entry_date = None
    trades = []; eq_history = []

    for i in range(len(df)):
        bar = df.iloc[i]
        date = df.index[i]
        close = bar['close']; ema5 = bar['ema5']

        if pos == 'long':   cur_eq = units * close
        elif pos == 'short': cur_eq = units * (2*entry_px - close)
        else: cur_eq = account
        eq_history.append({'date': date, 'equity': cur_eq})

        if i+1 >= len(df): continue
        next_open = df.iloc[i+1]['open']
        next_date = df.index[i+1]

        # Filter lookup at THIS bar's date (no look-ahead)
        uptrend = get_filter_at(date)
        year = date.year

        if variant == 'V0':
            target = 'long' if close > ema5 else None
        elif variant == 'V1':
            if uptrend is None: target = None
            else: target = 'long' if (uptrend and close > ema5) else None
        elif variant == 'V2':
            if uptrend is None: target = None
            elif uptrend:       target = 'long' if close > ema5 else None
            else:               target = 'short' if close < ema5 else None
        elif variant == 'V3':
            if year in HINDSIGHT_BEAR_YEARS:
                target = 'short' if close < ema5 else None
            else:
                target = 'long' if close > ema5 else None
        else: target = None

        if pos is not None and pos != target:
            if pos == 'long':
                gross = units * next_open
                fee = gross * FEE_PER_LEG
                account = gross - fee
                ret = (next_open/entry_px - 1)*100
            else:
                gross = units * entry_px + units * (entry_px - next_open)
                fee = units * next_open * FEE_PER_LEG
                account = gross - fee
                ret = (entry_px/next_open - 1)*100
            trades.append({
                'side': pos, 'entry_date': entry_date, 'exit_date': next_date,
                'entry': entry_px, 'exit': next_open, 'ret_pct': ret,
                'account_after': account,
                'duration_d': (next_date-entry_date).days,
                'year': entry_date.year,
            })
            pos = None; units=0; entry_px=None; entry_date=None

        if pos is None and target is not None:
            fee = account * FEE_PER_LEG
            units = (account - fee) / next_open
            entry_px = next_open; entry_date = next_date
            pos = target

    if pos is not None:
        lc = df.iloc[-1]['close']
        if pos == 'long':
            gross = units * lc; fee = gross*FEE_PER_LEG
            account = gross - fee
            ret = (lc/entry_px - 1)*100
        else:
            gross = units*entry_px + units*(entry_px-lc); fee = units*lc*FEE_PER_LEG
            account = gross - fee
            ret = (entry_px/lc - 1)*100
        trades.append({'side':pos,'entry_date':entry_date,'exit_date':df.index[-1],
                       'entry':entry_px,'exit':lc,'ret_pct':ret,'account_after':account,
                       'duration_d':(df.index[-1]-entry_date).days,'year':entry_date.year})
    eq_df = pd.DataFrame(eq_history).set_index('date')
    return pd.DataFrame(trades), eq_df['equity']

def bh_eq(df):
    df = df.dropna()
    fee = INITIAL_CAPITAL * FEE_PER_LEG
    units = (INITIAL_CAPITAL - fee) / df['open'].iloc[1]
    return pd.Series(units * df['close'].values, index=df.index)

def stats(trades, eq, df):
    if len(eq) == 0:
        return {'trades':0,'wr':0,'final':INITIAL_CAPITAL,'apy':0,'mdd':0,'eq':eq,'avg_win':0,'avg_loss':0,'best':0,'worst':0}
    final = eq.iloc[-1]
    peak = INITIAL_CAPITAL; mdd = 0
    for v in eq.values:
        if v > peak: peak = v
        d = (v-peak)/peak*100
        if d < mdd: mdd = d
    days = (df.index[-1] - df.index[0]).days
    apy = ((final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    if len(trades) == 0:
        return {'trades':0,'wr':0,'final':final,'apy':apy,'mdd':mdd,'eq':eq,'avg_win':0,'avg_loss':0,'best':0,'worst':0}
    wins = trades[trades['ret_pct']>0]; losses = trades[trades['ret_pct']<=0]
    return {
        'trades': len(trades),
        'wr': (trades['ret_pct']>0).mean()*100,
        'avg_win': wins['ret_pct'].mean() if len(wins) else 0,
        'avg_loss': losses['ret_pct'].mean() if len(losses) else 0,
        'best': trades['ret_pct'].max(),
        'worst': trades['ret_pct'].min(),
        'final': final, 'apy': apy, 'mdd': mdd, 'eq': eq,
    }

data_tf = [('1D', btc_1d_test), ('5D', btc_5d_test), ('1W', btc_1w_test)]
variants = ['V0','V1','V2','V3']
labels = {
    'V0':'V0 long-only, no filter (baseline)',
    'V1':'V1 long-only, filter-gated',
    'V2':'V2 long/short, filter-gated (USER)',
    'V3':'V3 hindsight cycle (reference)',
}

results = {}
for tf, df in data_tf:
    results[tf] = {}
    for v in variants:
        t, e = run(df, v)
        s = stats(t, e, df)
        s['trades_df'] = t
        results[tf][v] = s
    e_bh = bh_eq(df)
    s_bh = stats(pd.DataFrame(), e_bh, df)
    s_bh['eq'] = e_bh
    results[tf]['bh'] = s_bh

# ── PRINT ──
sep = "─" * 120
for tf, _ in data_tf:
    print(f"\n{'═'*120}")
    print(f"  TIMEFRAME = {tf}")
    print(f"{'═'*120}")
    print(f"  {'Variant':<40}{'Trades':>8}{'WR%':>7}{'AvgWin%':>10}{'AvgLoss%':>10}{'Best%':>9}{'Worst%':>9}{'Final$':>11}{'APY%':>9}{'MaxDD%':>9}")
    print(sep)
    for v in variants:
        s = results[tf][v]
        print(f"  {labels[v]:<40}{s['trades']:>8}{s['wr']:>7.1f}{s['avg_win']:>+10.2f}{s['avg_loss']:>+10.2f}{s['best']:>+9.1f}{s['worst']:>+9.1f}{s['final']:>11,.0f}{s['apy']:>+9.1f}{s['mdd']:>+9.1f}")
    bs = results[tf]['bh']
    print(sep)
    print(f"  {'BTC buy-and-hold':<40}{'-':>8}{'-':>7}{'-':>10}{'-':>10}{'-':>9}{'-':>9}{bs['final']:>11,.0f}{bs['apy']:>+9.1f}{bs['mdd']:>+9.1f}")

# ── V2 vs V3: how much does honest filter cost vs hindsight? ──
print(f"\n{'═'*120}")
print(f"  HONEST FILTER vs HINDSIGHT — V2 (filter-driven) vs V3 (hindsight cycle)")
print(f"{'═'*120}")
print(f"  {'TF':<5}{'V2 final$':>13}{'V2 APY%':>10}{'V2 DD%':>10}{'V3 final$':>13}{'V3 APY%':>10}{'V3 DD%':>10}{'Cost of honesty':>20}")
print(sep)
for tf, _ in data_tf:
    v2 = results[tf]['V2']; v3 = results[tf]['V3']
    cost = v3['final'] - v2['final']
    print(f"  {tf:<5}{v2['final']:>13,.0f}{v2['apy']:>+10.1f}{v2['mdd']:>+10.1f}{v3['final']:>13,.0f}{v3['apy']:>+10.1f}{v3['mdd']:>+10.1f}{cost:>+20,.0f}")

# ── PER-SIDE STATS for V2 on each TF ──
print(f"\n{'═'*120}")
print(f"  V2 PER-SIDE PERFORMANCE — did the shorts pay?")
print(f"{'═'*120}")
print(f"  {'TF':<5}{'Long #':>8}{'Long WR%':>10}{'Long AvgRet%':>14}{'Long TotRet%':>14}{'Short #':>9}{'Short WR%':>11}{'Short AvgRet%':>15}{'Short TotRet%':>15}")
print(sep)
for tf, _ in data_tf:
    t = results[tf]['V2']['trades_df']
    longs = t[t['side']=='long']; shorts = t[t['side']=='short']
    l_wr = (longs['ret_pct']>0).mean()*100 if len(longs) else 0
    s_wr = (shorts['ret_pct']>0).mean()*100 if len(shorts) else 0
    print(f"  {tf:<5}{len(longs):>8}{l_wr:>10.1f}{longs['ret_pct'].mean() if len(longs) else 0:>+14.2f}{longs['ret_pct'].sum() if len(longs) else 0:>+14.1f}"
          f"{len(shorts):>9}{s_wr:>11.1f}{shorts['ret_pct'].mean() if len(shorts) else 0:>+15.2f}{shorts['ret_pct'].sum() if len(shorts) else 0:>+15.1f}")

# ── YEAR-BY-YEAR V2 on 1W ──
print(f"\n{'═'*120}")
print(f"  V2 year-by-year on 1W timeframe")
print(f"{'═'*120}")
eq_v2_1w = results['1W']['V2']['eq']
print(f"  {'Year':<6}{'Filter most of year':<22}{'Trades':>8}{'Year P&L%':>12}{'BH P&L%':>11}")
print(sep)
for yr in range(2018, 2027):
    ys = pd.Timestamp(f'{yr}-01-01',tz='UTC'); ye = pd.Timestamp(f'{yr}-12-31',tz='UTC')
    eq_yr = eq_v2_1w[(eq_v2_1w.index>=ys) & (eq_v2_1w.index<=ye)]
    eq_bh_yr = results['1W']['bh']['eq']
    eq_bh_yr = eq_bh_yr[(eq_bh_yr.index>=ys) & (eq_bh_yr.index<=ye)]
    if len(eq_yr) < 2 or len(eq_bh_yr) < 2: continue
    filt_yr = filter_series[(filter_series.index>=ys) & (filter_series.index<=ye)]
    pct_up = filt_yr.mean()*100 if len(filt_yr) else 0
    label = f"{pct_up:.0f}% uptrend"
    t_in_year = results['1W']['V2']['trades_df']
    t_yr = t_in_year[pd.to_datetime(t_in_year['exit_date']).dt.year == yr]
    yr_ret = (eq_yr.iloc[-1]/eq_yr.iloc[0]-1)*100
    bh_ret = (eq_bh_yr.iloc[-1]/eq_bh_yr.iloc[0]-1)*100
    print(f"  {yr:<6}{label:<22}{len(t_yr):>8}{yr_ret:>+12.1f}{bh_ret:>+11.1f}")

# ── CHART ──
fig, axes = plt.subplots(3, 1, figsize=(15, 13), sharex=True)
colors = {'V0':'#1f77b4','V1':'#9467bd','V2':'#d62728','V3':'#ff7f0e'}
for idx, (tf, df) in enumerate(data_tf):
    ax = axes[idx]
    for v in variants:
        s = results[tf][v]
        lw = 2.0 if v=='V2' else 1.2
        alpha = 1.0 if v=='V2' else 0.7
        ax.plot(s['eq'].index, s['eq'].values, color=colors[v], linewidth=lw, alpha=alpha,
                label=f"{labels[v]}: {s['final']:,.0f} ({s['apy']:+.1f}% APY, DD {s['mdd']:+.0f}%)")
    bh = results[tf]['bh']
    ax.plot(bh['eq'].index, bh['eq'].values, color='gray', linewidth=1.0, alpha=0.6, linestyle='--',
            label=f"BTC B&H: {bh['final']:,.0f} ({bh['apy']:+.1f}% APY, DD {bh['mdd']:+.0f}%)")
    # Shade downtrend periods (filter false) at bottom
    for j in range(len(btc_1d_test)):
        d = btc_1d_test.index[j]
        if not get_filter_at(d):
            ax.axvspan(d, d + pd.Timedelta(days=1), alpha=0.04, color='red', linewidth=0)
    ax.axhline(INITIAL_CAPITAL, color='black', linestyle=':', alpha=0.4)
    ax.set_ylabel('Account (USD)')
    ax.set_yscale('log')
    ax.set_title(f'5 EMA + 200 EMA-slope filter on BTC {tf} (red shading = downtrend per filter)', fontweight='bold')
    ax.legend(loc='upper left', fontsize=8)
    ax.grid(True, alpha=0.3, which='both')
axes[2].xaxis.set_major_locator(mdates.YearLocator())
axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
plt.tight_layout()
plt.savefig('btc_5ema_filter.png', dpi=130, bbox_inches='tight')
print(f"\nChart -> btc_5ema_filter.png")
