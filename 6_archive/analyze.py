import pandas as pd
import numpy as np

r = pd.read_csv('backtest_results.csv')
r['win']  = r['pnl_usd'] > 0
r['year'] = pd.to_datetime(r['entry_date']).dt.year

print("=== R-MULTIPLE DISTRIBUTION ===")
print(r['R'].describe().round(3))

print("\n=== BY EXIT REASON ===")
for reason, grp in r.groupby('exit_reason'):
    wins = grp[grp['win']]
    wr   = len(wins) / len(grp) * 100
    avgR = grp['R'].mean()
    dur  = grp['duration_h'].mean()
    print(f"  {reason:<28}  {len(grp):>3} trades  {wr:>5.0f}% win  avg R: {avgR:+.3f}  avg duration: {dur:.1f}h")

print("\n=== STOP DISTANCE (% of entry price) ===")
r['stop_pct'] = r['stop_distance'] / r['entry_price'] * 100
print(r['stop_pct'].describe().round(3))

print("\n=== WINNERS: reward distance vs stop distance (R achieved) ===")
wins = r[r['win']].copy()
wins['reward_dist']     = wins['exit_price'] - wins['entry_price']
wins['reward_vs_stop']  = wins['reward_dist'] / wins['stop_distance']
print(wins['reward_vs_stop'].describe().round(3))

print("\n=== R DISTRIBUTION — winners ===")
buckets = [-99, 0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 99]
labels  = ['<0','0-0.25R','0.25-0.5R','0.5-0.75R','0.75-1R','1-1.5R','1.5-2R','>2R']
wins['R_bucket'] = pd.cut(wins['R'], bins=buckets, labels=labels)
print(wins['R_bucket'].value_counts().sort_index())

print("\n=== 2023 — losing trades by exit reason ===")
y23 = r[(r['year'] == 2023) & (~r['win'])]
print(y23['exit_reason'].value_counts())
print("Avg stop distance (2023 losses):", round(y23['stop_pct'].mean(), 2), "%")
print("Avg R (2023 losses):", round(y23['R'].mean(), 3))

print("\n=== YEAR-BY-YEAR R-MULTIPLE ===")
for yr, grp in r.groupby('year'):
    wins_yr = grp[grp['win']]
    loss_yr = grp[~grp['win']]
    print(f"  {yr}  trades:{len(grp):>3}  wr:{len(wins_yr)/len(grp)*100:>5.1f}%  "
          f"avg_win_R:{wins_yr['R'].mean():>+.2f}  avg_loss_R:{loss_yr['R'].mean():>+.2f}  "
          f"expectancy:{grp['R'].mean():>+.3f}R")
