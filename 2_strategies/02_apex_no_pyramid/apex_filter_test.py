"""
Apex no-pyramid — TREND FILTER COMPARISON
  V0: close > sma50 > sma200            (baseline, the "lagging" one)
  V1: close > sma200                    (user request — drop the 50 SMA filter entirely)
  V2: close > sma200 AND sma200 rising  (less laggy than V0, more selective than V1)

Everything else identical: 180d lookback, 2×ATR stop, 1.5× volume, 50% off at 2R, 20-bar trail.
"""
import os, pickle
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

INITIAL_CAPITAL = 1839.17
RISK_PCT        = 0.02
MAX_POSITIONS   = 3
FEE_PER_LEG     = 0.0010
LOOKBACK        = 1080
ATR_MULT        = 2.0
VOL_MULT        = 1.5
SMA200_SLOPE_BARS = 50    # for V2: 200 SMA must be rising over last N bars

P1_start = pd.Timestamp('2022-01-01', tz='UTC')
P1_end   = pd.Timestamp('2023-12-31', tz='UTC')
P2_start = pd.Timestamp('2024-01-01', tz='UTC')
P2_end   = pd.Timestamp('2026-05-31', tz='UTC')

with open('../../1_data/ohlcv_4h_cache.pkl', 'rb') as f:
    raw = pickle.load(f)

def compute(df):
    df = df.copy()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    df['sma200_prev'] = df['sma200'].shift(SMA200_SLOPE_BARS)
    prev = df['close'].shift(1)
    tr = pd.concat([df['high']-df['low'], (df['high']-prev).abs(), (df['low']-prev).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()
    df['vol_sma20'] = df['volume'].rolling(20).mean()
    return df

data = {s: compute(df) for s, df in raw.items()}

def signal(df, i, variant):
    if i < max(200, LOOKBACK): return False
    c = df['close'].iloc[i]
    s50, s200 = df['sma50'].iloc[i], df['sma200'].iloc[i]
    s200_p = df['sma200_prev'].iloc[i]
    atr, vs, v = df['atr14'].iloc[i], df['vol_sma20'].iloc[i], df['volume'].iloc[i]
    if any(pd.isna(x) for x in [s50, s200, atr, vs]): return False

    if variant == 'V0':
        if not (c > s50 > s200): return False
    elif variant == 'V1':
        if not (c > s200): return False
    elif variant == 'V2':
        if pd.isna(s200_p): return False
        if not (c > s200 and s200 > s200_p): return False

    if not (c > df['high'].iloc[i-LOOKBACK:i].max()): return False
    if not (v > vs * VOL_MULT): return False
    return True

def run(start, end, variant):
    acct = INITIAL_CAPITAL
    pos = {}; trades = []; eq_hist = []
    dates = sorted(set().union(*[df.index for df in data.values()]))
    dates = [d for d in dates if start <= d <= end]
    for date in dates:
        for sym in list(pos.keys()):
            if date not in data[sym].index: continue
            df = data[sym]; idx = df.index.get_loc(date)
            h, l = df['high'].iloc[idx], df['low'].iloc[idx]
            p = pos[sym]
            if l <= p['stop']:
                px = p['stop']; sz = p['size'] * p['rem']
                pnl = (px - p['entry'])*sz - px*sz*FEE_PER_LEG
                tot = pnl + p['partial']; acct += pnl
                trades.append({'symbol': sym, 'entry_date': p['edate'], 'exit_date': date,
                               'pnl': tot, 'R': tot/(p['acct_at']*RISK_PCT),
                               'reason': 'trail' if p.get('scaled') else 'stop'})
                del pos[sym]; continue
            if not p.get('scaled') and h >= p['target']:
                psz = p['size']*0.5
                ppn = (p['target']-p['entry'])*psz - p['target']*psz*FEE_PER_LEG
                acct += ppn; p['partial'] += ppn
                p['rem'] = 0.5; p['stop'] = p['entry']; p['scaled'] = True
            if p.get('scaled'):
                lo20 = df['low'].iloc[max(0,idx-20):idx].min()
                if lo20 > p['stop']: p['stop'] = lo20
        if len(pos) < MAX_POSITIONS:
            for sym, df in data.items():
                if sym in pos: continue
                if date not in df.index: continue
                idx = df.index.get_loc(date)
                if not signal(df, idx, variant): continue
                if idx+1 >= len(df): continue
                ent = df['open'].iloc[idx+1]
                atr = df['atr14'].iloc[idx]
                stp = ent - ATR_MULT*atr
                if stp >= ent: continue
                if len(pos) >= MAX_POSITIONS: break
                sd = ent - stp
                sz = (acct*RISK_PCT)/sd
                fee = ent*sz*FEE_PER_LEG; acct -= fee
                pos[sym] = {'edate': df.index[idx+1], 'entry': ent, 'stop': stp,
                            'target': ent+2*sd, 'size': sz, 'rem': 1.0,
                            'acct_at': acct+fee, 'partial': -fee}
        eq_hist.append({'date': date, 'equity': acct})
    for sym, p in pos.items():
        df = data[sym]; lc = df['close'].loc[:end].iloc[-1]
        sz = p['size']*p['rem']
        pnl = (lc-p['entry'])*sz - lc*sz*FEE_PER_LEG
        tot = pnl + p['partial']; acct += pnl
        trades.append({'symbol': sym, 'entry_date': p['edate'],
                       'exit_date': df.loc[:end].index[-1],
                       'pnl': tot, 'R': tot/(p['acct_at']*RISK_PCT), 'reason': 'open_end'})
    eq = pd.DataFrame(eq_hist).set_index('date') if eq_hist else pd.DataFrame()
    return pd.DataFrame(trades), acct, eq

def metrics(t, f, eq, start, end):
    n = len(t)
    if n == 0:
        return {'trades':0,'wr':0,'aw':0,'al':0,'exp':0,'apy':0,'dd':0,'final':f}
    wins = t[t['R']>0]; losses = t[t['R']<=0]
    curve = [INITIAL_CAPITAL] + (list(eq['equity']) if len(eq) else [])
    peak, mdd = INITIAL_CAPITAL, 0
    for v in curve:
        if v > peak: peak = v
        d = (v-peak)/peak*100
        if d < mdd: mdd = d
    days = (end - start).days
    apy = ((f/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    return {
        'trades': n, 'wr': len(wins)/n*100,
        'aw': wins['R'].mean() if len(wins) else 0,
        'al': losses['R'].mean() if len(losses) else 0,
        'exp': t['R'].mean(), 'apy': apy, 'dd': mdd, 'final': f,
    }

results = {}
for variant, desc in [('V0','close > sma50 > sma200 (baseline)'),
                      ('V1','close > sma200 only'),
                      ('V2','close > sma200 AND sma200 rising')]:
    print(f"\n=== {variant}: {desc} ===")
    t1, f1, e1 = run(P1_start, P1_end, variant)
    t2, f2, e2 = run(P2_start, P2_end, variant)
    m1 = metrics(t1, f1, e1, P1_start, P1_end)
    m2 = metrics(t2, f2, e2, P2_start, P2_end)
    print(f"  P1: {m1['trades']} trades, WR {m1['wr']:.1f}%, exp {m1['exp']:+.2f}R, APY {m1['apy']:+.1f}%, DD {m1['dd']:+.1f}%")
    print(f"  P2: {m2['trades']} trades, WR {m2['wr']:.1f}%, exp {m2['exp']:+.2f}R, APY {m2['apy']:+.1f}%, DD {m2['dd']:+.1f}%")
    # year breakdown for P2
    if len(t2) > 0:
        t2c = t2.copy(); t2c['year'] = pd.to_datetime(t2c['exit_date']).dt.year
        for yr, g in t2c.groupby('year'):
            wr = (g['R']>0).mean()*100
            print(f"    P2 {yr}: {len(g):>2} trades, WR {wr:.1f}%, exp {g['R'].mean():+.2f}R, P&L ${g['pnl'].sum():+.0f}")
    results[variant] = {'desc': desc, 'm1': m1, 'm2': m2, 't1': t1, 't2': t2, 'e1': e1, 'e2': e2}

# Comparison table
sep = "─" * 110
print(f"\n{'═'*110}")
print(f"  TREND FILTER COMPARISON — Apex no-pyramid, walk-forward")
print(f"{'═'*110}")
print(f"  {'Variant':<10}{'Filter':<38}{'P1 trd':>8}{'P1 exp':>9}{'P1 APY':>9}{'P1 DD':>8}{'P2 trd':>8}{'P2 exp':>9}{'P2 APY':>9}{'P2 DD':>8}")
print(sep)
for v in ['V0','V1','V2']:
    r = results[v]; m1, m2 = r['m1'], r['m2']
    print(f"  {v:<10}{r['desc'][:36]:<38}{m1['trades']:>8}{m1['exp']:>+9.2f}{m1['apy']:>+9.1f}{m1['dd']:>+8.1f}"
          f"{m2['trades']:>8}{m2['exp']:>+9.2f}{m2['apy']:>+9.1f}{m2['dd']:>+8.1f}")

# Equity chart
fig, ax = plt.subplots(figsize=(14, 7))
colors = {'V0': '#1f77b4', 'V1': '#d62728', 'V2': '#2ca02c'}
labels = {'V0': '50>200 SMA (baseline)', 'V1': 'close > 200 SMA only', 'V2': '200 SMA rising'}
for v in ['V0','V1','V2']:
    r = results[v]
    full_eq = pd.concat([r['e1'], r['e2']])
    ax.plot(r['e1'].index, r['e1']['equity'], color=colors[v], linewidth=1.5, alpha=0.9,
            label=f"{labels[v]} — P1 {r['m1']['final']:,.0f} ({r['m1']['apy']:+.0f}% APY)  P2 {r['m2']['final']:,.0f} ({r['m2']['apy']:+.0f}% APY)")
    ax.plot(r['e2'].index, r['e2']['equity'], color=colors[v], linewidth=1.5, alpha=0.9, linestyle='--')

ax.axhline(INITIAL_CAPITAL, color='black', linestyle=':', alpha=0.4)
ax.axvline(P2_start, color='black', linestyle=':', alpha=0.5)
ax.set_ylabel('Account ($) — each period resets to $1,839')
ax.set_title('Apex — Trend Filter Comparison (solid=P1 train, dashed=P2 fresh exam)', fontweight='bold')
ax.legend(loc='upper left', fontsize=9)
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
plt.tight_layout()
plt.savefig('apex_filter_test.png', dpi=130, bbox_inches='tight')
print(f"\nChart -> apex_filter_test.png")
