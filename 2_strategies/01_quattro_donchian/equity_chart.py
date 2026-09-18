import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import numpy as np

r = pd.read_csv('backtest_donchian_pyramid_results.csv')
r['entry_date'] = pd.to_datetime(r['entry_date'])
r['exit_date']  = pd.to_datetime(r['exit_date'])
r['win']        = r['pnl_usd'] > 0
r['R']          = r['R_total']

INITIAL_BALANCE = 1839.17

# Build equity curve with timestamps
equity = pd.DataFrame({
    'date':    [r['entry_date'].iloc[0] - pd.Timedelta(days=1)] + r['exit_date'].tolist(),
    'balance': [INITIAL_BALANCE] + r['account'].tolist(),
})
equity['peak']     = equity['balance'].cummax()
equity['drawdown'] = (equity['balance'] - equity['peak']) / equity['peak'] * 100

# Identify the maximum drawdown period
max_dd_idx = equity['drawdown'].idxmin()
max_dd_pct = equity['drawdown'].iloc[max_dd_idx]
max_dd_balance = equity['balance'].iloc[max_dd_idx]
max_dd_date = equity['date'].iloc[max_dd_idx]

# Find peak before max drawdown
peak_idx = equity.loc[:max_dd_idx, 'balance'].idxmax()
peak_balance = equity['balance'].iloc[peak_idx]
peak_date = equity['date'].iloc[peak_idx]

# Find recovery date (first time balance exceeds the peak after the trough)
recovery_idx = None
for j in range(max_dd_idx, len(equity)):
    if equity['balance'].iloc[j] >= peak_balance:
        recovery_idx = j
        break

# ── PLOT ──────────────────────────────────────────────────────────────────────

fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 12),
                                     gridspec_kw={'height_ratios':[3, 2, 2]},
                                     sharex=True)

# === Chart 1: Equity curve ===
ax1.plot(equity['date'], equity['balance'], linewidth=1.5, color='#1f77b4', label='Account balance')
ax1.fill_between(equity['date'], INITIAL_BALANCE, equity['balance'],
                 where=(equity['balance'] >= INITIAL_BALANCE), alpha=0.15, color='green')
ax1.fill_between(equity['date'], INITIAL_BALANCE, equity['balance'],
                 where=(equity['balance'] < INITIAL_BALANCE), alpha=0.15, color='red')

# Mark the worst drawdown period
ax1.axvspan(peak_date, max_dd_date, alpha=0.25, color='red', label='Max drawdown period')
ax1.annotate(f'Peak\n${peak_balance:,.0f}',
             xy=(peak_date, peak_balance), xytext=(10, 20), textcoords='offset points',
             fontsize=9, ha='left',
             arrowprops=dict(arrowstyle='->', color='black', lw=0.5))
ax1.annotate(f'Trough\n${max_dd_balance:,.0f}\n({max_dd_pct:.1f}%)',
             xy=(max_dd_date, max_dd_balance), xytext=(10, -40), textcoords='offset points',
             fontsize=9, ha='left', color='darkred',
             arrowprops=dict(arrowstyle='->', color='darkred', lw=0.5))

ax1.axhline(INITIAL_BALANCE, color='gray', linestyle='--', alpha=0.5, label=f'Start (${INITIAL_BALANCE:,.0f})')
ax1.set_ylabel('Account ($)', fontsize=11)
ax1.set_title('Donchian Pyramid  -  Equity Curve  ($1,839 -> $22,196 over 4.5 years)', fontsize=13, fontweight='bold')
ax1.legend(loc='upper left', fontsize=9)
ax1.grid(True, alpha=0.3)
ax1.set_yscale('log')

# === Chart 2: Underwater curve (drawdown %) ===
ax2.fill_between(equity['date'], 0, equity['drawdown'], color='#d62728', alpha=0.5)
ax2.plot(equity['date'], equity['drawdown'], color='#d62728', linewidth=1)
ax2.axhline(0, color='black', linewidth=0.5)
ax2.axhline(max_dd_pct, color='red', linestyle='--', alpha=0.6,
            label=f'Max DD: {max_dd_pct:.1f}%')
ax2.set_ylabel('Drawdown from peak (%)', fontsize=11)
ax2.set_title('Underwater Curve  -  How far below peak the account is at each point', fontsize=12)
ax2.legend(loc='lower left', fontsize=9)
ax2.grid(True, alpha=0.3)

# === Chart 3: Per-trade P&L ===
colors = ['green' if w else 'red' for w in r['win']]
ax3.bar(r['exit_date'], r['R'], color=colors, width=4, alpha=0.7)
ax3.axhline(0, color='black', linewidth=0.5)
ax3.set_ylabel('P&L per trade (R)', fontsize=11)
ax3.set_xlabel('Date', fontsize=11)
ax3.set_title('Per-Trade P&L in R-multiples  (1R = 2% of account at trade entry)', fontsize=12)
ax3.grid(True, alpha=0.3)

# Highlight outliers
biggest_win = r['R'].idxmax()
biggest_loss = r['R'].idxmin()
ax3.annotate(f"Best: +{r['R'].iloc[biggest_win]:.1f}R",
             xy=(r['exit_date'].iloc[biggest_win], r['R'].iloc[biggest_win]),
             xytext=(0, -25), textcoords='offset points',
             fontsize=9, color='darkgreen', ha='center')

# Format dates
for ax in [ax1, ax2, ax3]:
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

plt.tight_layout()
plt.savefig('equity_curve.png', dpi=120, bbox_inches='tight')
print("Saved -> equity_curve.png")

# === Print drawdown analysis ===
print("\n" + "="*70)
print("MAX DRAWDOWN ANALYSIS")
print("="*70)
print(f"  Peak balance:        ${peak_balance:,.2f}  ({peak_date.date()})")
print(f"  Trough balance:      ${max_dd_balance:,.2f}  ({max_dd_date.date()})")
print(f"  Drawdown:            {max_dd_pct:.1f}%  (${peak_balance - max_dd_balance:,.2f})")
print(f"  Duration peak->trough: {(max_dd_date - peak_date).days} days")
if recovery_idx is not None:
    rec_date = equity['date'].iloc[recovery_idx]
    print(f"  Recovery date:       {rec_date.date()}  ({(rec_date - max_dd_date).days} days from trough)")
    print(f"  Total drawdown duration: {(rec_date - peak_date).days} days")
else:
    print("  Not recovered to peak (still in drawdown at backtest end)")

# Trades during the drawdown
during_dd = r[(r['exit_date'] >= peak_date) & (r['exit_date'] <= max_dd_date)]
print(f"\n  Trades during drawdown:  {len(during_dd)}")
print(f"    Wins:    {len(during_dd[during_dd['win']])}")
print(f"    Losses:  {len(during_dd[~during_dd['win']])}")
print(f"    Total P&L: ${during_dd['pnl_usd'].sum():+,.2f}")
print(f"    Worst single trade: {during_dd['R'].min():+.2f}R  (${during_dd['pnl_usd'].min():+,.2f})")

print("\n" + "="*70)
print("TOP 5 BIGGEST WINNERS")
print("="*70)
for idx, row in r.nlargest(5, 'R').iterrows():
    print(f"  {row['exit_date'].date()}  +{row['R']:>6.2f}R  (${row['pnl_usd']:>+8,.2f})  units={int(row['num_units'])}")

print("\n" + "="*70)
print("TOP 5 BIGGEST LOSERS")
print("="*70)
for idx, row in r.nsmallest(5, 'R').iterrows():
    print(f"  {row['exit_date'].date()}  {row['R']:>+6.2f}R  (${row['pnl_usd']:>+8,.2f})  units={int(row['num_units'])}  reason={row['exit_reason']}")

print("\n" + "="*70)
print("CONCENTRATION OF GAINS")
print("="*70)
total_pnl = r['pnl_usd'].sum()
top5_pnl  = r.nlargest(5, 'pnl_usd')['pnl_usd'].sum()
top10_pnl = r.nlargest(10, 'pnl_usd')['pnl_usd'].sum()
print(f"  Total P&L:                  ${total_pnl:>+10,.2f}")
print(f"  Top 5 trades contribute:    ${top5_pnl:>+10,.2f}  ({top5_pnl/total_pnl*100:.1f}% of total)")
print(f"  Top 10 trades contribute:   ${top10_pnl:>+10,.2f}  ({top10_pnl/total_pnl*100:.1f}% of total)")
