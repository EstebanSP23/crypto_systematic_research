"""
Generate a polished English-language Quattro equity-curve chart suitable for
LinkedIn Featured. Reconstructs equity from the trade log to avoid relying on
the Spanish PDF assets.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

INITIAL_CAPITAL = 1839.17

df = pd.read_csv('../2_strategies/01_quattro_donchian/backtest_donchian_pyramid_results.csv')
df['entry_date'] = pd.to_datetime(df['entry_date'])
df['exit_date']  = pd.to_datetime(df['exit_date'])

# Reconstruct stepwise equity at each trade close
eq_dates = [df['entry_date'].min()]
eq_values = [INITIAL_CAPITAL]
for _, row in df.iterrows():
    eq_dates.append(row['exit_date'])
    eq_values.append(row['account'])

eq = pd.Series(eq_values, index=pd.DatetimeIndex(eq_dates))

# Drawdown
peak = eq.cummax()
dd_pct = (eq - peak) / peak * 100

# Stats
final = eq.iloc[-1]
total_ret = (final/INITIAL_CAPITAL - 1) * 100
mdd = dd_pct.min()
days = (eq.index[-1] - eq.index[0]).days
apy = ((final/INITIAL_CAPITAL) ** (365.25/days) - 1) * 100
trades = len(df)
wr = (df['win']).mean() * 100
avg_win_r = df[df['R'] > 0]['R'].mean()
avg_loss_r = df[df['R'] <= 0]['R'].mean()

# Chart
fig = plt.figure(figsize=(14, 8))
gs = fig.add_gridspec(2, 1, height_ratios=[2.4, 1], hspace=0.12)

ax1 = fig.add_subplot(gs[0])
ax1.plot(eq.index, eq.values, color='#1a936f', linewidth=2.2, zorder=3)
ax1.fill_between(eq.index, INITIAL_CAPITAL, eq.values,
                 where=(eq.values >= INITIAL_CAPITAL), color='#1a936f', alpha=0.10)
ax1.axhline(INITIAL_CAPITAL, color='gray', linestyle='--', linewidth=0.9, alpha=0.6)
ax1.set_yscale('log')
ax1.set_ylabel('Account (USD, log scale)', fontsize=11)
ax1.set_title('Quattro Donchian Breakout — BTC 4H Backtest\nJanuary 2022 to May 2026',
              fontsize=14, fontweight='bold', loc='left')
ax1.text(0.02, 0.95,
         f"Starting capital:    ${INITIAL_CAPITAL:,.0f}\n"
         f"Final balance:       ${final:,.0f}\n"
         f"Total return:        +{total_ret:,.0f}%\n"
         f"Annualized (APY):    +{apy:.0f}%\n"
         f"Max drawdown:        {mdd:.1f}%\n"
         f"Trades:              {trades}\n"
         f"Win rate:            {wr:.1f}%\n"
         f"Win/loss R ratio:    {avg_win_r/abs(avg_loss_r):.1f}x",
         transform=ax1.transAxes, fontsize=10, family='monospace', va='top',
         bbox=dict(boxstyle='round,pad=0.6', facecolor='white', edgecolor='gray', alpha=0.92))
ax1.grid(True, alpha=0.3, which='both')
ax1.set_xticklabels([])

ax2 = fig.add_subplot(gs[1])
ax2.fill_between(dd_pct.index, dd_pct.values, 0, color='#c0392b', alpha=0.35)
ax2.plot(dd_pct.index, dd_pct.values, color='#c0392b', linewidth=1.2)
ax2.axhline(mdd, color='#c0392b', linestyle=':', linewidth=1, alpha=0.7)
ax2.text(dd_pct.index[5], mdd*1.05, f'Max DD: {mdd:.1f}%', fontsize=9, color='#c0392b')
ax2.set_ylabel('Drawdown %', fontsize=11)
ax2.grid(True, alpha=0.3)
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax2.xaxis.get_majorticklabels(), rotation=35, ha='right')

# Footer
fig.text(0.02, 0.01,
         'Single-asset Donchian-20 breakout with 4-unit pyramid (+0.5N intervals) and rising 200 EMA filter. '
         '2% risk per unit, 5% hard catastrophe stop, 2N per-unit trailing stop, Donchian-10 channel exit. '
         'Walk-forward validated. Live-deployed on BloFin perpetual futures via CCXT.',
         fontsize=8, style='italic', color='gray', wrap=True)

plt.tight_layout(rect=[0, 0.04, 1, 1])
plt.savefig('quattro_featured_en.png', dpi=150, bbox_inches='tight', facecolor='white')
print("Generated: quattro_featured_en.png")
print(f"Verified stats: {trades} trades, {wr:.1f}% WR, +{total_ret:,.0f}% return, +{apy:.0f}% APY, {mdd:.1f}% DD")
