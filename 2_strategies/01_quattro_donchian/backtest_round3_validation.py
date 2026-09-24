"""
Round 3 - validation of 20/10 + 55/20 (accepted in Round 2 by leave-one-out)
Engine: quattro_v2_engine.py (v2 with taker fees + Binance funding). Criteria fixed before running:

  Test A (out of sample): P0 = 2019-10-01 .. 2021-12-31. The combination 20/10 + 55/20 at 1/2 risk
          each must beat v2 (20/10 alone, full risk) on Calmar in P0. If not -> REJECTED regardless of B.
          2020 and 2021 reported separately for information only.
  Test B (neighbourhood): 20/10 combined with slow legs 40/15, 55/20, 70/25, 100/30 at 1/2 risk each.
          At least 3 of 4 must beat v2 on P2 Calmar and none may have P2 Calmar < 0.5.
  Verdict: ACCEPTED only if A and B pass.

Data:
  P0     : 1_data/btc_4h_2019_cache.pkl (ATR warmed from 2019-01) + 1_data/btc_1d_2017_cache.pkl
           (daily EMA-200 warmed from 2017-08) + Binance funding (from 2019-09-10). Independent run
           starting at INITIAL_BALANCE on 2019-10-01. Both caches are first checked against the live
           Binance data on their overlap.
  P1/P2  : the same 2022-01 .. 2026-05 live pipeline as Round 2 (P1 2022-2023, P2 2024-2026, split
           by exit date because the combinations hold overlapping positions).
Combinations run at 1/2 risk per leg (total risk equal to v2), hard stop scaled the same way (2.5R).
"""
import os
import numpy as np
import pandas as pd
import quattro_v2_engine as eng

DATA_DIR  = os.path.join(eng.HERE, '..', '..', '1_data')
P0_START  = pd.Timestamp('2019-10-01', tz='UTC')
P0_END    = pd.Timestamp('2022-01-01', tz='UTC')      # exclusive
SLOW_LEGS = {'40_15': (40, 15), '55_20': (55, 20), '70_25': (70, 25), '100_30': (100, 30)}
TESTED    = '55_20'
R, H      = eng.RISK_PCT, eng.HARD_STOP_PCT


def leg(e, x, frac):
    return dict(name=f'd{e}_{x}', entry_len=e, exit_len=x, risk_pct=R * frac, hard_stop_pct=H * frac)

CONFIGS = {'v2': [leg(20, 10, 1)]}
for k, (e, x) in SLOW_LEGS.items():
    CONFIGS[f'20_10+{k}'] = [leg(20, 10, 0.5), leg(e, x, 0.5)]
for k, (e, x) in SLOW_LEGS.items():
    CONFIGS[f'solo_{k}'] = [leg(e, x, 1)]


# -- DATA ----------------------------------------------------------------------

live = eng.load_data()                       # 2022-01 .. 2026-05, Round 2 pipeline
eng.verify_v2(live)

c4 = pd.read_pickle(os.path.join(DATA_DIR, 'btc_4h_2019_cache.pkl'))
c1 = pd.read_pickle(os.path.join(DATA_DIR, 'btc_1d_2017_cache.pkl'))

# cache vs live on the overlap (same Binance candles expected)
cols = ['open', 'high', 'low', 'close']
ov4  = c4.loc[c4.index.isin(live.df.index), cols]
same4 = len(ov4) == len(live.df) and np.allclose(ov4.values, live.df.loc[ov4.index, cols].values, rtol=0, atol=1e-8)
print(f"  Cache check: 4H cache == live 4H on 2022-01..2026-05 ({len(ov4)} bars) [{'OK' if same4 else 'FAIL'}]")
if not same4:
    raise SystemExit("4H cache does not match live data - aborting.")

df = c4.copy()
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low']  - df['close'].shift(1)).abs(),
], axis=1).max(axis=1)
df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()
d1 = c1.copy()
d1['ema200'] = d1['close'].ewm(span=200, adjust=False).mean()
avail = d1[['ema200']].copy()
avail.index = avail.index + pd.Timedelta(days=1)
df['d_ema200']  = avail.reindex(df.index, method='ffill')['ema200']
df['regime_up'] = df['close'] > df['d_ema200']

fund = pd.read_csv(eng.FUNDING_CSV)
fund['bar'] = pd.to_datetime(fund['timestamp_ms'], unit='ms', utc=True).dt.floor('h')
df['funding_rate'] = fund.set_index('bar')['funding_rate'].reindex(df.index)

start = df.index.get_loc(P0_START) - eng.WARMUP      # bar WARMUP of the slice = 2019-10-01 00:00
p0df  = df.iloc[start:]
p0df  = p0df[p0df.index < P0_END]
data0 = eng.Data(p0df, fund)

settle   = p0df.index.hour.isin([0, 8, 16]) & (p0df.index >= P0_START)
no_rate  = int((settle & p0df['funding_rate'].isna()).sum())
missing  = int((P0_END - P0_START) / pd.Timedelta(hours=4)) - int((p0df.index >= P0_START).sum())
print(f"  P0 data: trading from {data0.dates[eng.WARMUP]} to {data0.dates[-1]} | missing 4H bars: {missing} | "
      f"settlement bars without funding: {no_rate} | EMA-200 NaN in P0: {int(p0df.loc[p0df.index >= P0_START, 'd_ema200'].isna().sum())}")
if no_rate or p0df.loc[p0df.index >= P0_START, 'd_ema200'].isna().any():
    raise SystemExit("P0 data insufficient - aborting.")


# -- RUNS ----------------------------------------------------------------------

def metrics_between(r, start_eq, t0, t1):
    return eng.period_metrics(r, start_eq, t0, t1)

def split_exit(r, pieces):
    """pieces: list of (label, t0, t1); equity carried over by exit date."""
    out, eq = [], eng.INITIAL_BALANCE
    for label, t0, t1 in pieces:
        before = r[r['exit_date'] < t0]
        eq0 = before['account'].iloc[-1] if len(before) else eng.INITIAL_BALANCE
        sub = r[(r['exit_date'] >= t0) & (r['exit_date'] < t1)]
        out.append({'period': label, **metrics_between(sub, eq0, t0, t1)})
    return out

T0_live = live.dates[eng.WARMUP]
T1_live = live.dates[-1] + pd.Timedelta(hours=4)
Y2020, Y2021 = pd.Timestamp('2020-01-01', tz='UTC'), pd.Timestamp('2021-01-01', tz='UTC')

rows = []
for name, legs in CONFIGS.items():
    print(f"Running {name}...")
    r0, _, _ = eng.run(data0, legs)
    for m in split_exit(r0, [('P0 2019-10..2021-12', P0_START, P0_END),
                             ('2020 (info)', Y2020, Y2021), ('2021 (info)', Y2021, P0_END)]):
        rows.append({'config': name, **m})
    r1, _, _ = eng.run(live, legs)
    for m in split_exit(r1, [('Full 2022-01..2026-05', T0_live, T1_live),
                             ('P1 2022-2023', T0_live, eng.SPLIT_DATE),
                             ('P2 2024-2026', eng.SPLIT_DATE, T1_live)]):
        rows.append({'config': name, **m})
res = pd.DataFrame(rows)
# the P0 row must start from INITIAL_BALANCE (split_exit carries equity only for later pieces)
g = lambda c, p, k: res[(res['config'] == c) & (res['period'] == p)][k].iloc[0]


# -- CRITERIA ------------------------------------------------------------------

combo = f'20_10+{TESTED}'
A_pass = g(combo, 'P0 2019-10..2021-12', 'calmar') > g('v2', 'P0 2019-10..2021-12', 'calmar')
combos = [f'20_10+{k}' for k in SLOW_LEGS]
beat_p2 = {c: g(c, 'P2 2024-2026', 'calmar') > g('v2', 'P2 2024-2026', 'calmar') for c in combos}
disaster = {c: g(c, 'P2 2024-2026', 'calmar') < 0.5 for c in combos}
B_pass = sum(beat_p2.values()) >= 3 and not any(disaster.values())
verdict = 'ACCEPTED' if (A_pass and B_pass) else 'REJECTED'
failed = [k for k, ok in [('A', A_pass), ('B', B_pass)] if not ok]


# -- REPORT --------------------------------------------------------------------

print("\n" + "=" * 100 + "\n  TEST A - OUT OF SAMPLE P0 (2019-10-01 .. 2021-12-31), with costs\n" + "=" * 100)
print(f"  {'config':<16}{'period':<22}{'return %':>10}{'APY %':>8}{'max DD %':>10}{'Calmar':>8}{'trades':>8}"
      f"{'win %':>7}{'avgW R':>8}{'avgL R':>8}{'costs $':>9}")
for c in ['v2', combo]:
    for p in ['P0 2019-10..2021-12', '2020 (info)', '2021 (info)']:
        m = res[(res['config'] == c) & (res['period'] == p)].iloc[0]
        print(f"  {c:<16}{p:<22}{m.total_return_pct:>+10.1f}{m.apy_pct:>+8.1f}{m.max_dd_pct:>10.1f}{m.calmar:>8.2f}"
              f"{m.trades:>8.0f}{m.win_rate_pct:>7.1f}{m.avg_win_R:>+8.2f}{m.avg_loss_R:>+8.2f}{m.total_costs_usd:>9,.0f}")

print("\n" + "=" * 100 + "\n  TEST B - NEIGHBOURHOOD (Calmar by period; return / DD / trades / costs for P0 and 2022-26)\n" + "=" * 100)
print(f"  {'config':<16}{'Cal P0':>8}{'Cal P1':>8}{'Cal P2':>8}   {'P0 ret %':>9}{'P0 DD %':>9}{'P0 tr':>6}{'P0 cost$':>9}"
      f"   {'22-26 ret%':>11}{'DD %':>7}{'tr':>5}{'cost $':>8}")
for c in CONFIGS:
    p0, full = [res[(res['config'] == c) & (res['period'] == p)].iloc[0]
                for p in ['P0 2019-10..2021-12', 'Full 2022-01..2026-05']]
    print(f"  {c:<16}{p0.calmar:>8.2f}{g(c, 'P1 2022-2023', 'calmar'):>8.2f}{g(c, 'P2 2024-2026', 'calmar'):>8.2f}   "
          f"{p0.total_return_pct:>+9.1f}{p0.max_dd_pct:>9.1f}{p0.trades:>6.0f}{p0.total_costs_usd:>9,.0f}   "
          f"{full.total_return_pct:>+11.1f}{full.max_dd_pct:>7.1f}{full.trades:>5.0f}{full.total_costs_usd:>8,.0f}")

print("\n  CRITERIA (fixed before running)")
print(f"  A  {combo} Calmar P0 {g(combo, 'P0 2019-10..2021-12', 'calmar'):.2f} vs v2 "
      f"{g('v2', 'P0 2019-10..2021-12', 'calmar'):.2f} -> {'PASS' if A_pass else 'FAIL'}")
print(f"  B  combos beating v2 on P2 Calmar ({g('v2', 'P2 2024-2026', 'calmar'):.2f}): "
      + ', '.join(f"{c.split('+')[1]} {g(c, 'P2 2024-2026', 'calmar'):.2f}{' OK' if beat_p2[c] else ' no'}" for c in combos)
      + f"  -> {sum(beat_p2.values())}/4; disasters (<0.5): {sum(disaster.values())} -> {'PASS' if B_pass else 'FAIL'}")
print(f"\n  VERDICT 20/10 + 55/20: {verdict}" + (f" (failed: {', '.join(failed)})" if failed else ''))

res['criterion_A_pass'] = A_pass
res['criterion_B_pass'] = B_pass
res['verdict_20_10+55_20'] = verdict
res.round(4).to_csv(os.path.join(eng.HERE, 'results', 'round3_validation.csv'), index=False)
print("\nResults -> results/round3_validation.csv")
