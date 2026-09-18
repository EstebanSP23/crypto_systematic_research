"""
Apex baseline — full dissection per asset per year + outlier detection.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap

# Load trades from previous run
df = pd.read_csv('apex_trades.csv')
df['entry_date'] = pd.to_datetime(df['entry_date'])
df['exit_date']  = pd.to_datetime(df['exit_date'])
df['year']       = df['exit_date'].dt.year
df['month']      = df['exit_date'].dt.month
df['quarter']    = df['exit_date'].dt.quarter
df['duration_d'] = (df['exit_date'] - df['entry_date']).dt.total_seconds() / 86400
df['asset']      = df['symbol'].str.replace('/USDT','', regex=False)
df['win']        = df['R'] > 0

print(f"Total trades loaded: {len(df)}")
print(f"Periods: P1 {(df['period']=='P1').sum()} trades, P2 {(df['period']=='P2').sum()} trades")
print(f"Years present: {sorted(df['year'].unique())}")
print(f"Assets that traded: {sorted(df['asset'].unique())}")

# ── 1. PER ASSET × YEAR TABLE ─────────────────────────────────────────────
sep = "─" * 130
print(f"\n{'═'*130}")
print(f"  PER-ASSET × YEAR DISSECTION")
print(f"{'═'*130}")
print(f"  {'Asset':<7}{'Year':<6}{'Trades':>7}{'Wins':>6}{'WR%':>7}{'AvgR':>8}{'MedR':>8}{'BestR':>8}{'WorstR':>8}{'TotalR':>9}{'P&L$':>10}{'AvgDay':>8}{'%stop':>7}{'%trail':>7}")
print(sep)

for asset in sorted(df['asset'].unique(), key=lambda a: df[df['asset']==a]['R'].sum(), reverse=True):
    g_all = df[df['asset']==asset]
    print(sep)
    for yr in sorted(g_all['year'].unique()):
        g = g_all[g_all['year']==yr]
        wins = g[g['win']]
        n = len(g)
        wr = len(wins)/n*100
        tot_pnl = g['pnl'].sum()
        tot_r = g['R'].sum()
        avg_dur = g['duration_d'].mean()
        stop_pct = (g['reason']=='stop').mean()*100
        trail_pct = (g['reason']=='trail').mean()*100
        print(f"  {asset:<7}{yr:<6}{n:>7}{len(wins):>6}{wr:>7.1f}{g['R'].mean():>+8.2f}{g['R'].median():>+8.2f}"
              f"{g['R'].max():>+8.2f}{g['R'].min():>+8.2f}{tot_r:>+9.2f}{tot_pnl:>+10.0f}{avg_dur:>8.1f}{stop_pct:>7.0f}{trail_pct:>7.0f}")
    # asset total
    n = len(g_all); wins = g_all[g_all['win']]
    wr = len(wins)/n*100
    print(f"  {asset+' ALL':<13}{n:>7}{len(wins):>6}{wr:>7.1f}{g_all['R'].mean():>+8.2f}{g_all['R'].median():>+8.2f}"
          f"{g_all['R'].max():>+8.2f}{g_all['R'].min():>+8.2f}{g_all['R'].sum():>+9.2f}{g_all['pnl'].sum():>+10.0f}"
          f"{g_all['duration_d'].mean():>8.1f}{(g_all['reason']=='stop').mean()*100:>7.0f}{(g_all['reason']=='trail').mean()*100:>7.0f}")

# Universe total
print(sep)
print(f"  {'UNIVERSE':<13}{len(df):>7}{df['win'].sum():>6}{df['win'].mean()*100:>7.1f}"
      f"{df['R'].mean():>+8.2f}{df['R'].median():>+8.2f}{df['R'].max():>+8.2f}{df['R'].min():>+8.2f}"
      f"{df['R'].sum():>+9.2f}{df['pnl'].sum():>+10.0f}{df['duration_d'].mean():>8.1f}"
      f"{(df['reason']=='stop').mean()*100:>7.0f}{(df['reason']=='trail').mean()*100:>7.0f}")

# ── 2. YEAR SUMMARY ──────────────────────────────────────────────────────
print(f"\n{'═'*130}")
print(f"  YEAR SUMMARY (all assets)")
print(f"{'═'*130}")
print(f"  {'Year':<6}{'Trades':>8}{'WR%':>7}{'AvgR':>8}{'TotalR':>9}{'P&L$':>10}{'Assets traded':>16}{'Best trade':>14}{'Worst trade':>14}")
print(sep)
for yr in sorted(df['year'].unique()):
    g = df[df['year']==yr]
    assets = g['asset'].nunique()
    best = g.loc[g['R'].idxmax()]
    worst = g.loc[g['R'].idxmin()]
    print(f"  {yr:<6}{len(g):>8}{g['win'].mean()*100:>7.1f}{g['R'].mean():>+8.2f}{g['R'].sum():>+9.2f}{g['pnl'].sum():>+10.0f}"
          f"{assets:>16}{best['asset']+' '+f'{best['R']:+.2f}R':>14}{worst['asset']+' '+f'{worst['R']:+.2f}R':>14}")

# ── 3. OUTLIER TRADES ────────────────────────────────────────────────────
print(f"\n{'═'*130}")
print(f"  OUTLIER TRADES — winners (R >= +3) and losers (R <= -1.2)")
print(f"{'═'*130}")
print(f"  {'#':>3} {'Period':<7}{'Asset':<7}{'Entry':<12}{'Exit':<12}{'EntryPx':>10}{'ExitPx':>10}{'R':>8}{'P&L$':>10}{'Days':>7}{'Reason':>8}")
print(sep)
winners = df[df['R'] >= 3.0].sort_values('R', ascending=False)
losers  = df[df['R'] <= -1.2].sort_values('R')
print(f"  >>> BIG WINNERS ({len(winners)}):")
for i, (_, t) in enumerate(winners.iterrows(), 1):
    print(f"  {i:>3} {t['period']:<7}{t['asset']:<7}{t['entry_date'].strftime('%Y-%m-%d'):<12}{t['exit_date'].strftime('%Y-%m-%d'):<12}"
          f"{t['entry']:>10.4f}{t['exit']:>10.4f}{t['R']:>+8.2f}{t['pnl']:>+10.0f}{t['duration_d']:>7.1f}{t['reason']:>8}")
print(f"\n  >>> BIG LOSERS ({len(losers)}):")
for i, (_, t) in enumerate(losers.iterrows(), 1):
    print(f"  {i:>3} {t['period']:<7}{t['asset']:<7}{t['entry_date'].strftime('%Y-%m-%d'):<12}{t['exit_date'].strftime('%Y-%m-%d'):<12}"
          f"{t['entry']:>10.4f}{t['exit']:>10.4f}{t['R']:>+8.2f}{t['pnl']:>+10.0f}{t['duration_d']:>7.1f}{t['reason']:>8}")

# ── 4. CONCENTRATION ─────────────────────────────────────────────────────
print(f"\n{'═'*130}")
print(f"  CONCENTRATION ANALYSIS")
print(f"{'═'*130}")
total_R = df['R'].sum()
sorted_R = df.sort_values('R', ascending=False).reset_index(drop=True)
top1, top3, top5 = sorted_R['R'].iloc[:1].sum(), sorted_R['R'].iloc[:3].sum(), sorted_R['R'].iloc[:5].sum()
print(f"  Total cumulative R across all 66 trades: {total_R:+.2f}R  (${df['pnl'].sum():+.0f})")
print(f"  Top  1 trade contributes:  {top1:+.2f}R  ({top1/total_R*100:.0f}% of total)")
print(f"  Top  3 trades contribute:  {top3:+.2f}R  ({top3/total_R*100:.0f}% of total)")
print(f"  Top  5 trades contribute:  {top5:+.2f}R  ({top5/total_R*100:.0f}% of total)")
top10 = sorted_R['R'].iloc[:10].sum()
print(f"  Top 10 trades contribute:  {top10:+.2f}R  ({top10/total_R*100:.0f}% of total)")
n_pos = (df['R']>0).sum(); n_neg = (df['R']<=0).sum()
print(f"  {n_pos} winners contributed: {df[df['R']>0]['R'].sum():+.2f}R")
print(f"  {n_neg} losers  contributed: {df[df['R']<=0]['R'].sum():+.2f}R")
# Worst case removal scenarios
print(f"\n  WHAT-IF removal analysis:")
print(f"    If we missed the best 1 trade:  remaining {total_R-top1:+.2f}R total ({(total_R-top1)/65*100:.1f}R/trade)")
print(f"    If we missed the best 3 trades: remaining {total_R-top3:+.2f}R total ({(total_R-top3)/63*100:.1f}R/trade)")
print(f"    If we missed the best 5 trades: remaining {total_R-top5:+.2f}R total ({(total_R-top5)/61*100:.1f}R/trade)")

# ── 5. SEASONALITY ───────────────────────────────────────────────────────
print(f"\n{'═'*130}")
print(f"  MONTHLY SEASONALITY (entry month)")
print(f"{'═'*130}")
df['entry_month'] = df['entry_date'].dt.month
month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
print(f"  {'Month':<6}{'Trades':>8}{'WR%':>7}{'AvgR':>8}{'TotalR':>9}")
print(sep)
for m in range(1, 13):
    g = df[df['entry_month']==m]
    if len(g) == 0:
        print(f"  {month_names[m-1]:<6}{0:>8}{'-':>7}{'-':>8}{'-':>9}")
        continue
    print(f"  {month_names[m-1]:<6}{len(g):>8}{g['win'].mean()*100:>7.1f}{g['R'].mean():>+8.2f}{g['R'].sum():>+9.2f}")

# ── 6. CHART: Heatmap + per-asset cumulative ─────────────────────────────
fig = plt.figure(figsize=(15, 11))
gs = fig.add_gridspec(3, 2, height_ratios=[1.2, 1.2, 1.3], hspace=0.45, wspace=0.25)

# Heatmap: asset (rows) × year (cols), color = total R
ax1 = fig.add_subplot(gs[0, :])
years = sorted(df['year'].unique())
assets_sorted = sorted(df['asset'].unique(), key=lambda a: df[df['asset']==a]['R'].sum(), reverse=True)
matrix = np.full((len(assets_sorted), len(years)), np.nan)
labels = np.full((len(assets_sorted), len(years)), '', dtype=object)
for i, a in enumerate(assets_sorted):
    for j, y in enumerate(years):
        g = df[(df['asset']==a) & (df['year']==y)]
        if len(g) > 0:
            matrix[i,j] = g['R'].sum()
            labels[i,j] = f"{g['R'].sum():+.1f}R\n({len(g)} trades)"

cmap = LinearSegmentedColormap.from_list('rg', ['#c0392b','#ecf0f1','#27ae60'])
vmax = np.nanmax(np.abs(matrix)); vmin = -vmax
im = ax1.imshow(matrix, cmap=cmap, vmin=vmin, vmax=vmax, aspect='auto')
ax1.set_xticks(range(len(years))); ax1.set_xticklabels(years)
ax1.set_yticks(range(len(assets_sorted))); ax1.set_yticklabels(assets_sorted)
for i in range(len(assets_sorted)):
    for j in range(len(years)):
        if not np.isnan(matrix[i,j]):
            ax1.text(j, i, labels[i,j], ha='center', va='center', fontsize=9,
                     color='white' if abs(matrix[i,j]) > vmax*0.6 else 'black')
ax1.set_title('Per-asset × Year: Total R contributed (color) and trade count', fontweight='bold')
plt.colorbar(im, ax=ax1, label='Total R', fraction=0.025, pad=0.01)

# Per-asset cumulative R curves
ax2 = fig.add_subplot(gs[1, :])
df_sorted = df.sort_values('exit_date').reset_index(drop=True)
colors_map = plt.cm.tab10(np.linspace(0, 1, len(assets_sorted)))
for i, a in enumerate(assets_sorted):
    g = df_sorted[df_sorted['asset']==a].copy()
    if len(g) == 0: continue
    g['cum_R'] = g['R'].cumsum()
    final = g['cum_R'].iloc[-1]
    ax2.plot(g['exit_date'], g['cum_R'], marker='o', markersize=4, linewidth=1.5,
             color=colors_map[i], label=f"{a}: {final:+.1f}R ({len(g)} trades)")
ax2.axhline(0, color='black', linewidth=0.8)
ax2.axvline(pd.Timestamp('2024-01-01'), color='black', linestyle=':', alpha=0.5)
ax2.text(pd.Timestamp('2024-01-05'), ax2.get_ylim()[1]*0.95, 'P1 → P2 split', fontsize=9, alpha=0.7)
ax2.set_ylabel('Cumulative R per asset')
ax2.set_title('Per-asset cumulative R over time (trade-by-trade)', fontweight='bold')
ax2.legend(loc='upper left', fontsize=9, ncol=2)
ax2.grid(True, alpha=0.3)
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')

# Trade-by-trade R bars colored by asset
ax3 = fig.add_subplot(gs[2, :])
df_sorted2 = df.sort_values('exit_date').reset_index(drop=True)
x = np.arange(len(df_sorted2))
for i, a in enumerate(assets_sorted):
    mask = df_sorted2['asset']==a
    ax3.bar(x[mask], df_sorted2.loc[mask, 'R'], color=colors_map[i], label=a)
ax3.axhline(0, color='black', linewidth=0.8)
ax3.axhline(df['R'].mean(), color='blue', linestyle='--', alpha=0.5,
            label=f"Avg R {df['R'].mean():+.2f}")
ax3.axvline((df_sorted2['period']=='P1').sum()-0.5, color='black', linestyle=':', alpha=0.6)
ax3.text((df_sorted2['period']=='P1').sum(), ax3.get_ylim()[1]*0.9, 'P1 → P2', fontsize=9)
ax3.set_xlabel('Trade # (chronological)')
ax3.set_ylabel('R per trade')
ax3.set_title('Every trade in order — colored by asset', fontweight='bold')
ax3.legend(loc='upper right', fontsize=8, ncol=4)
ax3.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
plt.savefig('apex_dissect.png', dpi=130, bbox_inches='tight')
print(f"\nChart -> apex_dissect.png")

# ── 7. INTERESTING OBSERVATIONS ──────────────────────────────────────────
print(f"\n{'═'*130}")
print(f"  KEY OBSERVATIONS")
print(f"{'═'*130}")

# Untraded assets per year
for yr in sorted(df['year'].unique()):
    traded = set(df[df['year']==yr]['asset'].unique())
    universe = {'BTC','ETH','SOL','LINK','ADA','ARB','SUI','SEI'}
    missing = universe - traded
    if missing:
        print(f"  {yr}: assets that took ZERO trades: {sorted(missing)}")

# Asset profitability rank
print(f"\n  Asset profitability (across all 66 trades):")
ranked = df.groupby('asset')['R'].agg(['sum','mean','count']).sort_values('sum', ascending=False)
for a, row in ranked.iterrows():
    flag = ' 🚨' if row['sum'] < 0 else (' ⭐' if row['sum'] > 5 else '')
    print(f"    {a:<6}: {row['count']:>3} trades, total {row['sum']:+.2f}R, avg {row['mean']:+.2f}R{flag}")

# Hold duration analysis
print(f"\n  Hold duration (days):")
print(f"    Winners (R>0):  mean {df[df['R']>0]['duration_d'].mean():.1f}d, median {df[df['R']>0]['duration_d'].median():.1f}d, max {df[df['R']>0]['duration_d'].max():.1f}d")
print(f"    Losers  (R<=0): mean {df[df['R']<=0]['duration_d'].mean():.1f}d, median {df[df['R']<=0]['duration_d'].median():.1f}d, max {df[df['R']<=0]['duration_d'].max():.1f}d")

# Winner R distribution
print(f"\n  Winner R distribution:")
ww = df[df['R']>0]
for thr in [(0,1),(1,2),(2,3),(3,5),(5,10)]:
    bucket = ww[(ww['R']>=thr[0]) & (ww['R']<thr[1])]
    print(f"    {thr[0]:>2}R to {thr[1]}R: {len(bucket):>3} trades, total {bucket['R'].sum():+.2f}R")

# Consecutive trades streaks
print(f"\n  Streaks:")
seq = df.sort_values('exit_date')['R'].values
cur_w = cur_l = max_w = max_l = 0
for r in seq:
    if r > 0:
        cur_w += 1; cur_l = 0; max_w = max(max_w, cur_w)
    else:
        cur_l += 1; cur_w = 0; max_l = max(max_l, cur_l)
print(f"    Longest winning streak: {max_w}")
print(f"    Longest losing streak:  {max_l}")
