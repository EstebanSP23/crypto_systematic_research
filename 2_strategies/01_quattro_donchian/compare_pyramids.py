import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

INITIAL_BALANCE = 1839.17

# Load all three result sets
r0 = pd.read_csv('backtest_trend_results.csv')                    # no pyramid
r2 = pd.read_csv('backtest_pyramid_2units_results.csv')           # 2-unit cap
r4 = pd.read_csv('backtest_donchian_pyramid_results.csv')         # 4-unit cap

for r in (r0, r2, r4):
    r['entry_date'] = pd.to_datetime(r['entry_date'])
    r['exit_date']  = pd.to_datetime(r['exit_date'])
    r['win']        = r['pnl_usd'] > 0
    # ensure R column exists
    if 'R' not in r.columns:
        if 'R_total' in r.columns:
            r['R'] = r['R_total']
        else:
            r['R'] = r['pnl_usd'] / r['risk_amt']

def stats(r, name):
    wins   = r[r['win']]
    losses = r[~r['win']]
    final  = r['account'].iloc[-1]
    curve  = [INITIAL_BALANCE] + list(r['account'])
    peak = INITIAL_BALANCE; max_dd = 0.0
    for v in curve:
        if v > peak: peak = v
        dd = (v - peak)/peak*100
        if dd < max_dd: max_dd = dd
    max_w = max_l = cur_w = cur_l = 0
    for w in r['win']:
        if w: cur_w += 1; cur_l = 0; max_w = max(max_w, cur_w)
        else: cur_l += 1; cur_w = 0; max_l = max(max_l, cur_l)
    return {
        'name': name,
        'trades': len(r),
        'win_rate': len(wins)/len(r)*100,
        'avg_win_R': wins['R'].mean(),
        'avg_loss_R': losses['R'].mean(),
        'expectancy': r['R'].mean(),
        'max_dd': max_dd,
        'max_w': max_w,
        'max_l': max_l,
        'final': final,
        'return_pct': (final/INITIAL_BALANCE-1)*100,
        'biggest': r['R'].max(),
        'worst': r['R'].min(),
    }

s0 = stats(r0, 'No pyramid')
s2 = stats(r2, '2-unit pyramid')
s4 = stats(r4, '4-unit pyramid')

# ── PRINT COMPARISON ──────────────────────────────────────────────────────────

sep = "-" * 86
print(f"\n{'='*86}")
print(f"  3-WAY COMPARISON   Donchian Trend Strategies   BTC 4H   Jan 2022 -> May 2026")
print(f"{'='*86}")
print(f"{'':28}{'No pyramid':>18}{'2-unit pyramid':>20}{'4-unit pyramid':>20}")
print(sep)
def row(label, v0, v2, v4, fmt='{:>18.2f}'):
    print(f"  {label:<26}{fmt.format(v0):>18}{fmt.format(v2):>20}{fmt.format(v4):>20}")

print(f"  {'Total trades':<26}{s0['trades']:>18}{s2['trades']:>20}{s4['trades']:>20}")
print(f"  {'Win rate %':<26}{s0['win_rate']:>18.1f}{s2['win_rate']:>20.1f}{s4['win_rate']:>20.1f}")
print(f"  {'Avg win (R)':<26}{s0['avg_win_R']:>+18.2f}{s2['avg_win_R']:>+20.2f}{s4['avg_win_R']:>+20.2f}")
print(f"  {'Avg loss (R)':<26}{s0['avg_loss_R']:>+18.2f}{s2['avg_loss_R']:>+20.2f}{s4['avg_loss_R']:>+20.2f}")
print(f"  {'Expectancy (R)':<26}{s0['expectancy']:>+18.3f}{s2['expectancy']:>+20.3f}{s4['expectancy']:>+20.3f}")
print(f"  {'Max drawdown %':<26}{s0['max_dd']:>+18.2f}{s2['max_dd']:>+20.2f}{s4['max_dd']:>+20.2f}")
print(f"  {'Max losing streak':<26}{s0['max_l']:>18}{s2['max_l']:>20}{s4['max_l']:>20}")
print(f"  {'Final balance ($)':<26}{s0['final']:>18,.2f}{s2['final']:>20,.2f}{s4['final']:>20,.2f}")
print(f"  {'Total return %':<26}{s0['return_pct']:>+18.1f}{s2['return_pct']:>+20.1f}{s4['return_pct']:>+20.1f}")
print(f"  {'Biggest winner (R)':<26}{s0['biggest']:>+18.2f}{s2['biggest']:>+20.2f}{s4['biggest']:>+20.2f}")
print(f"  {'Worst loser (R)':<26}{s0['worst']:>+18.2f}{s2['worst']:>+20.2f}{s4['worst']:>+20.2f}")

# Risk-adjusted: return per unit of drawdown
print(f"  {'Return / Drawdown ratio':<26}{abs(s0['return_pct']/s0['max_dd']):>18.2f}{abs(s2['return_pct']/s2['max_dd']):>20.2f}{abs(s4['return_pct']/s4['max_dd']):>20.2f}")

print(f"\n{sep}")
print(f"  YEAR-BY-YEAR P&L (USD)")
print(sep)
print(f"  Year      No pyramid      2-unit      4-unit")
for yr in sorted(r4['exit_date'].dt.year.unique()):
    p0 = r0[r0['exit_date'].dt.year == yr]['pnl_usd'].sum()
    p2 = r2[r2['exit_date'].dt.year == yr]['pnl_usd'].sum()
    p4 = r4[r4['exit_date'].dt.year == yr]['pnl_usd'].sum()
    print(f"  {yr}     ${p0:>+9,.2f}    ${p2:>+9,.2f}    ${p4:>+9,.2f}")

# ── EQUITY CURVE COMPARISON CHART ─────────────────────────────────────────────

def make_curve(r):
    return pd.DataFrame({
        'date':    [r['entry_date'].iloc[0] - pd.Timedelta(days=1)] + r['exit_date'].tolist(),
        'balance': [INITIAL_BALANCE] + r['account'].tolist(),
    })

c0 = make_curve(r0)
c2 = make_curve(r2)
c4 = make_curve(r4)

def add_drawdown(c):
    c['peak'] = c['balance'].cummax()
    c['dd']   = (c['balance'] - c['peak']) / c['peak'] * 100
    return c
c0 = add_drawdown(c0); c2 = add_drawdown(c2); c4 = add_drawdown(c4)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10),
                                gridspec_kw={'height_ratios':[3, 2]},
                                sharex=True)

ax1.plot(c0['date'], c0['balance'], color='#1f77b4', linewidth=1.5, label=f"No pyramid  (+{s0['return_pct']:.0f}%, DD {s0['max_dd']:.1f}%)")
ax1.plot(c2['date'], c2['balance'], color='#ff7f0e', linewidth=1.5, label=f"2-unit pyramid  (+{s2['return_pct']:.0f}%, DD {s2['max_dd']:.1f}%)")
ax1.plot(c4['date'], c4['balance'], color='#d62728', linewidth=1.5, label=f"4-unit pyramid  (+{s4['return_pct']:.0f}%, DD {s4['max_dd']:.1f}%)")
ax1.axhline(INITIAL_BALANCE, color='gray', linestyle='--', alpha=0.5)
ax1.set_yscale('log')
ax1.set_ylabel('Account ($)  (log scale)', fontsize=11)
ax1.set_title('Equity Curve Comparison  -  Donchian Strategies on BTC 4H  (Jan 2022 to May 2026)', fontsize=13, fontweight='bold')
ax1.legend(loc='upper left', fontsize=10)
ax1.grid(True, alpha=0.3)

ax2.plot(c0['date'], c0['dd'], color='#1f77b4', linewidth=1.0, label='No pyramid')
ax2.plot(c2['date'], c2['dd'], color='#ff7f0e', linewidth=1.0, label='2-unit pyramid')
ax2.plot(c4['date'], c4['dd'], color='#d62728', linewidth=1.0, label='4-unit pyramid')
ax2.axhline(0, color='black', linewidth=0.5)
ax2.set_ylabel('Drawdown from peak (%)', fontsize=11)
ax2.set_xlabel('Date', fontsize=11)
ax2.set_title('Underwater Curves  -  How deep below peak each strategy went', fontsize=12)
ax2.legend(loc='lower left', fontsize=10)
ax2.grid(True, alpha=0.3)
ax2.fill_between(c4['date'], 0, c4['dd'], color='#d62728', alpha=0.1)

for ax in [ax1, ax2]:
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

plt.tight_layout()
plt.savefig('comparison_3way.png', dpi=120, bbox_inches='tight')
print(f"\nChart saved -> comparison_3way.png")
