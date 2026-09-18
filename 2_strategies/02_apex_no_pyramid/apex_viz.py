"""
Apex no-pyramid baseline — focused visualization + pattern stats.
Uses cached 4H data.
"""
import os, pickle
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

ASSETS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT',
          'ADA/USDT', 'ARB/USDT', 'SUI/USDT', 'SEI/USDT']

INITIAL_CAPITAL = 1839.17
RISK_PCT        = 0.02
MAX_POSITIONS   = 3
FEE_PER_LEG     = 0.0010
LOOKBACK        = 1080
ATR_MULT        = 2.0
VOL_MULT        = 1.5

P1_start = pd.Timestamp('2022-01-01', tz='UTC')
P1_end   = pd.Timestamp('2023-12-31', tz='UTC')
P2_start = pd.Timestamp('2024-01-01', tz='UTC')
P2_end   = pd.Timestamp('2026-05-31', tz='UTC')

with open('../../1_data/ohlcv_4h_cache.pkl', 'rb') as f:
    raw = pickle.load(f)

def compute_indicators(df):
    df = df.copy()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    prev = df['close'].shift(1)
    tr = pd.concat([df['high']-df['low'], (df['high']-prev).abs(), (df['low']-prev).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()
    df['vol_sma20'] = df['volume'].rolling(20).mean()
    return df

data = {s: compute_indicators(df) for s, df in raw.items()}

def signal(df, i):
    if i < max(200, LOOKBACK): return False
    c = df['close'].iloc[i]
    s50, s200 = df['sma50'].iloc[i], df['sma200'].iloc[i]
    atr, vs, v = df['atr14'].iloc[i], df['vol_sma20'].iloc[i], df['volume'].iloc[i]
    if any(pd.isna(x) for x in [s50, s200, atr, vs]): return False
    if not (c > s50 > s200): return False
    if not (c > df['high'].iloc[i-LOOKBACK:i].max()): return False
    if not (v > vs * VOL_MULT): return False
    return True

def run(start, end):
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
                tot = pnl + p['partial']
                acct += pnl
                trades.append({'symbol': sym, 'entry_date': p['edate'], 'exit_date': date,
                               'entry': p['entry'], 'exit': px, 'pnl': tot,
                               'R': tot/(p['acct_at']*RISK_PCT),
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
                if not signal(df, idx): continue
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
                       'exit_date': df.loc[:end].index[-1], 'entry': p['entry'], 'exit': lc,
                       'pnl': tot, 'R': tot/(p['acct_at']*RISK_PCT), 'reason': 'open_end'})
    return pd.DataFrame(trades), acct, pd.DataFrame(eq_hist).set_index('date')

t1, f1, e1 = run(P1_start, P1_end)
t2, f2, e2 = run(P2_start, P2_end)
all_trades = pd.concat([t1.assign(period='P1'), t2.assign(period='P2')], ignore_index=True)
all_trades.to_csv('apex_trades.csv', index=False)

def dd_curve(eq):
    peak = eq.cummax()
    return (eq - peak) / peak * 100

# ── FIGURE: 3 panels — equity + DD + per-asset ──
fig = plt.figure(figsize=(15, 10))
gs = fig.add_gridspec(3, 2, height_ratios=[2.2, 1, 1.4], hspace=0.4, wspace=0.25)

# Panel A: full timeline equity (P1 + P2 on real calendar)
ax1 = fig.add_subplot(gs[0, :])
btc = raw['BTC/USDT']['close']
btc_slice = btc[(btc.index >= P1_start) & (btc.index <= P2_end)]
btc_norm_slice = btc_slice / btc_slice.iloc[0] * INITIAL_CAPITAL
ax1.plot(btc_norm_slice.index, btc_norm_slice, color='gray', alpha=0.35, linewidth=1.0,
         label='BTC normalized (context)')
ax1.plot(e1.index, e1['equity'], color='#1f77b4', linewidth=1.8,
         label=f"P1 training (2022-23): ${INITIAL_CAPITAL:,.0f} → ${f1:,.0f}  (+{(f1/INITIAL_CAPITAL-1)*100:.1f}%)")
ax1.plot(e2.index, e2['equity'], color='#d62728', linewidth=1.8,
         label=f"P2 fresh exam (2024-26): ${INITIAL_CAPITAL:,.0f} → ${f2:,.0f}  (+{(f2/INITIAL_CAPITAL-1)*100:.1f}%)")
# Mark trade entries
for _, tr in t1.iterrows():
    ax1.axvline(tr['entry_date'], color='#1f77b4', alpha=0.10, linewidth=0.5)
for _, tr in t2.iterrows():
    ax1.axvline(tr['entry_date'], color='#d62728', alpha=0.10, linewidth=0.5)
ax1.axhline(INITIAL_CAPITAL, color='black', linestyle='--', alpha=0.4, linewidth=0.8)
ax1.axvline(P2_start, color='black', linestyle=':', alpha=0.6)
ax1.text(P2_start, ax1.get_ylim()[1]*0.95, '  P1/P2 split', fontsize=9, alpha=0.7)
ax1.set_ylabel('Account ($) — each period starts at $1,839')
ax1.set_title(f'Apex no-pyramid — Walk-Forward Equity (4H, 8-asset universe, baseline params)',
              fontweight='bold')
ax1.legend(loc='upper left', fontsize=9)
ax1.grid(True, alpha=0.3)

# Panel B: drawdown
ax2 = fig.add_subplot(gs[1, :])
dd1 = dd_curve(e1['equity']); dd2 = dd_curve(e2['equity'])
ax2.fill_between(dd1.index, dd1, 0, color='#1f77b4', alpha=0.35, label=f'P1 DD (max {dd1.min():.1f}%)')
ax2.fill_between(dd2.index, dd2, 0, color='#d62728', alpha=0.35, label=f'P2 DD (max {dd2.min():.1f}%)')
ax2.axhline(0, color='black', linewidth=0.6)
ax2.set_ylabel('Drawdown %')
ax2.legend(loc='lower left', fontsize=9)
ax2.grid(True, alpha=0.3)

# Format dates for top two
for ax in (ax1, ax2):
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

# Panel C-left: per-asset PnL R
ax3 = fig.add_subplot(gs[2, 0])
per_sym = all_trades.groupby(['symbol','period'])['R'].agg(['sum','count']).reset_index()
syms_ordered = all_trades.groupby('symbol')['R'].sum().sort_values().index.tolist()
yp = np.arange(len(syms_ordered))
p1_sums = [per_sym[(per_sym['symbol']==s) & (per_sym['period']=='P1')]['sum'].sum() for s in syms_ordered]
p2_sums = [per_sym[(per_sym['symbol']==s) & (per_sym['period']=='P2')]['sum'].sum() for s in syms_ordered]
ax3.barh(yp-0.18, p1_sums, height=0.36, color='#1f77b4', label='P1')
ax3.barh(yp+0.18, p2_sums, height=0.36, color='#d62728', label='P2')
ax3.set_yticks(yp); ax3.set_yticklabels([s.replace('/USDT','') for s in syms_ordered])
ax3.axvline(0, color='black', linewidth=0.6)
ax3.set_xlabel('Total R per asset')
ax3.set_title('Per-asset contribution', fontweight='bold')
ax3.legend(loc='lower right', fontsize=9)
ax3.grid(True, alpha=0.3, axis='x')

# Panel C-right: R distribution
ax4 = fig.add_subplot(gs[2, 1])
ax4.hist(t1['R'], bins=np.arange(-2, 8, 0.5), alpha=0.6, color='#1f77b4', label=f'P1 ({len(t1)} trades)')
ax4.hist(t2['R'], bins=np.arange(-2, 8, 0.5), alpha=0.6, color='#d62728', label=f'P2 ({len(t2)} trades)')
ax4.axvline(0, color='black', linewidth=0.8)
ax4.axvline(t1['R'].mean(), color='#1f77b4', linestyle='--', linewidth=1.5, label=f'P1 avg {t1["R"].mean():+.2f}R')
ax4.axvline(t2['R'].mean(), color='#d62728', linestyle='--', linewidth=1.5, label=f'P2 avg {t2["R"].mean():+.2f}R')
ax4.set_xlabel('Trade R'); ax4.set_ylabel('Count')
ax4.set_title('Trade R distribution', fontweight='bold')
ax4.legend(fontsize=8)
ax4.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('apex_baseline.png', dpi=130, bbox_inches='tight')
print("Chart -> apex_baseline.png")

# ── PATTERN STATS ──
print("\n" + "="*70)
print("  APEX BASELINE — PATTERN STATS")
print("="*70)

for label, t, f, e in [('P1 (2022-23)', t1, f1, e1), ('P2 (2024-26)', t2, f2, e2)]:
    t = t.copy()
    t['exit_date'] = pd.to_datetime(t['exit_date'])
    t['year'] = t['exit_date'].dt.year
    t['duration_h'] = (t['exit_date'] - pd.to_datetime(t['entry_date'])).dt.total_seconds()/3600
    print(f"\n  ▶ {label}: {len(t)} trades, final ${f:,.0f}")
    print(f"    Win rate: {(t['R']>0).mean()*100:.1f}%  |  Avg R: {t['R'].mean():+.3f}")
    print(f"    Avg hold: {t['duration_h'].mean():.0f}h ({t['duration_h'].mean()/24:.1f} days)")
    print(f"    Year breakdown:")
    for yr, g in t.groupby('year'):
        wr = (g['R']>0).mean()*100
        print(f"       {yr}: {len(g):>2} trades, win {wr:>4.1f}%, exp {g['R'].mean():+.2f}R, P&L ${g['pnl'].sum():>+7.0f}")
    print(f"    Exit reasons:")
    for r, c in t['reason'].value_counts().items():
        g = t[t['reason']==r]
        print(f"       {r:<10}: {c:>2} trades, exp {g['R'].mean():+.2f}R")

# concentration
print(f"\n  Concentration: top 3 winners contributed:")
sorted_R = all_trades.sort_values('R', ascending=False)
top3_R = sorted_R['R'].iloc[:3].sum()
all_R = all_trades['R'].sum()
print(f"    Top 3 trades: {top3_R:.1f}R out of {all_R:.1f}R total ({top3_R/all_R*100:.0f}%)")
print(f"    Worst 3 trades: {sorted_R['R'].iloc[-3:].sum():.1f}R")

# losing streaks
print(f"\n  Longest losing streak:")
for label, t in [('P1', t1), ('P2', t2)]:
    losses = (t.sort_values('exit_date')['R'] < 0).astype(int).values
    streak = max_streak = 0
    for x in losses:
        if x == 1: streak += 1
        else: streak = 0
        max_streak = max(max_streak, streak)
    print(f"    {label}: {max_streak} losses in a row")
