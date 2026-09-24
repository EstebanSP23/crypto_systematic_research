"""
Round 2 - Experiment 3: three-speed Donchian ensemble on the v2 engine
Engine: quattro_v2_engine.py (v2 with taker fees + Binance funding), compared against v2.

Three independent subsystems with v2's logic (pyramid, stops, exit, daily EMA-200 filter),
entry/exit Donchian 10/5, 20/10 and 55/20, on ONE shared balance:
  - ensemble: each subsystem risks RISK_PCT/3 per unit; its hard stop is HARD_STOP_PCT/3 so the
    catastrophe cap stays at 2.5R of that subsystem's unit risk, as in v2
  - positions add up; fees and funding are charged per subsystem order; the 20x leverage cap
    applies to the combined notional; subsystems step each bar in the order 10/5, 20/10, 55/20
  - solo_*: each speed alone with full risk (solo_20_10 is v2 itself)
  - loo_*: ensemble without one speed (remaining two keep RISK_PCT/3 each)

Walk-forward: with overlapping positions an entry-date split leaves P2's starting equity
undefined, so here P1/P2 split the closed-trade equity curve by EXIT date, for every
configuration including the v2 reference. The v2 reference under v2's own entry-date split
is also checked, to make sure no verdict depends on the split method.
"""
import os
import numpy as np
import pandas as pd
import quattro_v2_engine as eng

data = eng.load_data()
eng.verify_v2(data)

R3, H3 = eng.RISK_PCT / 3, eng.HARD_STOP_PCT / 3
SPEEDS = {'10_5': (10, 5), '20_10': (20, 10), '55_20': (55, 20)}

def sub(speed, risk, hard):
    e, x = SPEEDS[speed]
    return dict(name=f'd{speed}', entry_len=e, exit_len=x, risk_pct=risk, hard_stop_pct=hard)

CONFIGS = {
    'v2':            [sub('20_10', eng.RISK_PCT, eng.HARD_STOP_PCT)],
    'ensemble':      [sub(s, R3, H3) for s in SPEEDS],
    'solo_10_5':     [sub('10_5',  eng.RISK_PCT, eng.HARD_STOP_PCT)],
    'solo_55_20':    [sub('55_20', eng.RISK_PCT, eng.HARD_STOP_PCT)],
    'loo_no_10_5':   [sub(s, R3, H3) for s in ['20_10', '55_20']],
    'loo_no_20_10':  [sub(s, R3, H3) for s in ['10_5', '55_20']],
    'loo_no_55_20':  [sub(s, R3, H3) for s in ['10_5', '20_10']],
}
EXPLANATIONS = {
    'ensemble':     "BTC trends unfold on several horizons; splitting risk across three channel lengths "
                    "diversifies entry timing and exit patience instead of betting on one lookback.",
    'solo_10_5':    "A faster channel enters shorter swings earlier and exits sooner, trading more of the "
                    "intermediate trends a 20-bar channel misses.",
    'solo_55_20':   "The slow Turtle 'System 2' channel only trades major breakouts, filtering noise at the "
                    "cost of later entries and fewer trades.",
    'loo_no_10_5':  "Two-horizon diversification (20/10 + 55/20) without the noisiest, fastest channel.",
    'loo_no_20_10': "Two-horizon diversification with the most distinct pair of lookbacks (10/5 + 55/20).",
    'loo_no_55_20': "Two-horizon diversification (10/5 + 20/10) that stays reactive, without the slowest channel.",
}


def split_by_exit(r, label):
    t_start = data.dates[eng.WARMUP]
    t_end   = data.dates[-1] + pd.Timedelta(hours=4)
    p1 = r[r['exit_date'] <  eng.SPLIT_DATE]
    p2 = r[r['exit_date'] >= eng.SPLIT_DATE]
    p2_start = p1['account'].iloc[-1] if len(p1) else eng.INITIAL_BALANCE
    return [
        {'version': label, 'period': eng.PERIODS[0], **eng.period_metrics(r,  eng.INITIAL_BALANCE, t_start,        t_end)},
        {'version': label, 'period': eng.PERIODS[1], **eng.period_metrics(p1, eng.INITIAL_BALANCE, t_start,        eng.SPLIT_DATE)},
        {'version': label, 'period': eng.PERIODS[2], **eng.period_metrics(p2, p2_start,            eng.SPLIT_DATE, t_end)},
    ]


rows, logs, contrib = [], {}, {}
for name, subs in CONFIGS.items():
    print(f"Running {name} ({' + '.join(s['name'] for s in subs)})...")
    trades, book, objs = eng.run(data, subs)
    logs[name] = trades
    rows += split_by_exit(trades, name)
    contrib[name] = trades.groupby('system').agg(trades=('pnl_usd', 'size'), net_pnl_usd=('pnl_usd', 'sum'),
                                                 sum_R=('R', 'sum'), costs_usd=('fees_usd', 'sum'))
    contrib[name]['costs_usd'] += trades.groupby('system')['funding_usd'].sum()
res = pd.DataFrame(rows)

# solo 20/10 must be v2 itself
same = logs['v2']['account'].iloc[-1]
print(f"\n  v2 final equity ${same:,.2f} (engine run) | exit-date split for all configs below")

# v2 reference under its own entry-date split (for the verdict robustness check)
v2_entry = pd.DataFrame(eng.split_metrics(logs['v2'], data, 'v2')).set_index('period')
v2_exit  = res[res['version'] == 'v2'].set_index('period')
print(f"  v2 Calmar  P1: exit-split {v2_exit.loc[eng.PERIODS[1], 'calmar']:.2f} / entry-split "
      f"{v2_entry.loc[eng.PERIODS[1], 'calmar']:.2f}   P2: exit-split {v2_exit.loc[eng.PERIODS[2], 'calmar']:.2f} / "
      f"entry-split {v2_entry.loc[eng.PERIODS[2], 'calmar']:.2f}")

eng.print_comparison(res, list(CONFIGS), 'EXP 3 - ENSEMBLE (exit-date split)', W=13)

print("\n  CONTRIBUTION BY SUBSYSTEM (net P&L after costs, within each run)")
for name in ['ensemble', 'loo_no_10_5', 'loo_no_20_10', 'loo_no_55_20']:
    c = contrib[name]
    tot = c['net_pnl_usd'].sum()
    parts = ', '.join(f"{s}: {r.trades} tr, ${r.net_pnl_usd:,.0f} ({r.net_pnl_usd/tot*100:.0f}%), {r.sum_R:+.1f}R"
                      for s, r in c.iterrows())
    print(f"  {name:<14} {parts}")

names = [v for v in CONFIGS if v != 'v2']
acc = [eng.acceptance(res, v, EXPLANATIONS[v]) for v in names]
eng.print_acceptance(acc)

# Robustness of (a) to the v2 reference split method
flips = []
for a in acc:
    alt = (a['calmar_P1'] > v2_entry.loc[eng.PERIODS[1], 'calmar']) and (a['calmar_P2'] > v2_entry.loc[eng.PERIODS[2], 'calmar'])
    if alt != a['a_calmar_P1_and_P2']:
        flips.append(a['variant'])
print(f"\n  Criterion (a) vs v2 entry-date reference: {'no verdict changes' if not flips else 'CHANGES for ' + ', '.join(flips)}")

# Robustness: the LOO configs run at 2/3 of v2's total risk, and lower leverage alone lifts Calmar.
# Re-run with total risk equalized (1/2 each) and v2 itself at 2/3 risk (not acceptance candidates).
ROBUST = {
    'v2_at_2of3_risk':   [sub('20_10', eng.RISK_PCT * 2/3, eng.HARD_STOP_PCT * 2/3)],
    'loo_no_10_5_half':  [sub(s, eng.RISK_PCT / 2, eng.HARD_STOP_PCT / 2) for s in ['20_10', '55_20']],
    'loo_no_20_10_half': [sub(s, eng.RISK_PCT / 2, eng.HARD_STOP_PCT / 2) for s in ['10_5', '55_20']],
    'loo_no_55_20_half': [sub(s, eng.RISK_PCT / 2, eng.HARD_STOP_PCT / 2) for s in ['10_5', '20_10']],
}
rob_rows = []
for name, subs in ROBUST.items():
    trades, _, _ = eng.run(data, subs)
    rob_rows += split_by_exit(trades, name)
rob = pd.DataFrame(rob_rows)
print("\n  ROBUSTNESS - total risk equalized (not acceptance candidates)")
print(f"  {'config':<20}{'return %':>10}{'max DD %':>10}{'Calmar full':>13}{'Calmar P1':>11}{'Calmar P2':>11}")
for name in ['v2', 'loo_no_10_5'] + list(ROBUST):
    g = (res if name in CONFIGS else rob)
    g = g[g['version'] == name].set_index('period')
    print(f"  {name:<20}{g.loc[eng.PERIODS[0], 'total_return_pct']:>+10.1f}{g.loc[eng.PERIODS[0], 'max_dd_pct']:>10.1f}"
          f"{g.loc[eng.PERIODS[0], 'calmar']:>13.2f}{g.loc[eng.PERIODS[1], 'calmar']:>11.2f}{g.loc[eng.PERIODS[2], 'calmar']:>11.2f}")

res['verdict'] = res['version'].map({a['variant']: a['verdict'] for a in acc}).fillna('reference')
rob['verdict'] = 'robustness_check'
res = pd.concat([res, rob], ignore_index=True)
res['split'] = 'exit_date'
res.round(4).to_csv(os.path.join(eng.HERE, 'results', 'round2_ensemble.csv'), index=False)
print(f"\nResults -> results/round2_ensemble.csv")
