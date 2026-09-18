import pandas as pd
df = pd.read_csv('../2_strategies/01_quattro_donchian/backtest_donchian_pyramid_results.csv')
df['entry_date'] = pd.to_datetime(df['entry_date'])
df['exit_date'] = pd.to_datetime(df['exit_date'])

print(f"Trades: {len(df)}")
print(f"First entry: {df['entry_date'].min().date()}")
print(f"Last exit: {df['exit_date'].max().date()}")
days = (df['exit_date'].max() - df['entry_date'].min()).days
print(f"Days covered: {days}")
print(f"Years: {days/365.25:.2f}")
print()

wins = df[df['win']==True]
losses = df[df['win']==False]
print(f"Wins: {len(wins)} ({len(wins)/len(df)*100:.1f}%)")
print(f"Losses: {len(losses)} ({len(losses)/len(df)*100:.1f}%)")
print()

print(f"Avg win R: {wins['R'].mean():+.3f}")
print(f"Avg loss R: {losses['R'].mean():+.3f}")
print(f"Best trade R: {df['R'].max():+.2f}")
print(f"Worst trade R: {df['R'].min():+.2f}")
print(f"Avg duration (hours): {df['duration_h'].mean():.1f}")
print(f"Avg duration (days):  {df['duration_h'].mean()/24:.1f}")
print()

start_capital = df['account'].iloc[0] - df['pnl_usd'].iloc[0]
final = df['account'].iloc[-1]
total_ret = (final/start_capital - 1) * 100
apy = ((final/start_capital) ** (365.25/days) - 1) * 100

print(f"Starting capital: ${start_capital:,.2f}")
print(f"Final account:    ${final:,.2f}")
print(f"Total return:     {total_ret:+.1f}%")
print(f"APY:              {apy:+.1f}%")
print()

running_peak = start_capital
mdd = 0
for v in df['account']:
    if v > running_peak: running_peak = v
    d = (v - running_peak)/running_peak * 100
    if d < mdd: mdd = d
print(f"Max DD (trade-to-trade): {mdd:.2f}%")
print()

print("Exit reason breakdown:")
print(df['exit_reason'].value_counts().to_string())
print()
print("Trades by year:")
print(df.groupby('year').size().to_string())
print()
print("R bucket distribution:")
print(df['bucket'].value_counts().to_string())
