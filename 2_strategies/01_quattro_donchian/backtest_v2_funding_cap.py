"""
Round 2 - Experiment 2: pyramid cap on extreme funding
Engine: quattro_v2_engine.py (v2 with taker fees + Binance funding), compared against v2.

Before adding a capped unit, look at the funding rate in force: the last SETTLED 8h rate at or
before the open of the bar where the unit's trigger is hit (only settled rates exist in the
history; using the next one would look ahead). If it is above the rolling percentile of all
settlements in the previous 365 days (strictly earlier, the current one excluded), the unit is
not added - and no further unit is added for the rest of that trade.

  2a_p90_u4   : p90, unit 4 only
  2b_p95_u4   : p95, unit 4 only
  2c_p90_u34  : p90, units 3 and 4
  2d_p95_u34  : p95, units 3 and 4

Funding saved = funding the blocked units (whose trigger was actually hit) would have paid:
their size x rate x bar open at every settlement until the trade's exit.
"""
import os
import numpy as np
import pandas as pd
import quattro_v2_engine as eng

data = eng.load_data()
eng.verify_v2(data)

# -- Rolling funding percentiles (no look-ahead) --------------------------------
f = data.fund.copy()
f['ts'] = pd.to_datetime(f['timestamp_ms'], unit='ms', utc=True)
s = f.set_index('ts')['funding_rate'].sort_index()
pct = pd.DataFrame({
    'rate': s,
    'p90':  s.rolling('365D', closed='left').quantile(0.90),
    'p95':  s.rolling('365D', closed='left').quantile(0.95),
    'n365': s.rolling('365D', closed='left').count(),
})
pct.index = pct.index.floor('h')                     # settlement -> the 4H bar it opens
in_force = pct.reindex(data.dates, method='ffill')   # last settlement at or before the bar open
rate_now = in_force['rate'].values
thr = {'p90': in_force['p90'].values, 'p95': in_force['p95'].values}
print(f"  Funding in force: window size at backtest start = {int(in_force['n365'].iloc[eng.WARMUP])} settlements "
      f"(first percentile uses data from {s.index[0].date()})")

def make_cap(q, units):
    def allow_unit(sub, i, k):
        return 'block' if (k in units and rate_now[i] > thr[q][i]) else 'ok'
    return allow_unit

VARIANTS = {
    'v2':         dict(),
    '2a_p90_u4':  dict(allow_unit=make_cap('p90', {4})),
    '2b_p95_u4':  dict(allow_unit=make_cap('p95', {4})),
    '2c_p90_u34': dict(allow_unit=make_cap('p90', {3, 4})),
    '2d_p95_u34': dict(allow_unit=make_cap('p95', {3, 4})),
}
EXPLANATION = ("Extreme positive funding marks crowded leveraged longs, raising long-squeeze risk and the "
               "carry cost exactly when the pyramid would add its largest exposure.")

rows, trade_logs = [], {}
for name, kw in VARIANTS.items():
    print(f"Running {name}...")
    trades, book, sub = eng.run_single(data, **kw)
    trade_logs[name] = trades
    ev = pd.DataFrame(sub.events)
    for m in eng.split_metrics(trades, data, name):
        if m['period'] == eng.PERIODS[0]:
            t, e = trades, ev
        elif m['period'] == eng.PERIODS[1]:
            t = trades[trades['entry_date'] < eng.SPLIT_DATE]
            e = ev[ev['date'] < eng.SPLIT_DATE] if len(ev) else ev
        else:
            t = trades[trades['entry_date'] >= eng.SPLIT_DATE]
            e = ev[ev['date'] >= eng.SPLIT_DATE] if len(ev) else ev
        m['cap_activations']   = len(e)
        m['trades_capped']     = int((t['blocked_units'] > 0).sum())
        m['units_not_added']   = int(t['blocked_units'].sum())
        m['funding_saved_usd'] = t['hyp_funding_saved'].sum()
        rows.append(m)
res = pd.DataFrame(rows)
v2f = res[res['version'] == 'v2'].set_index('period')['funding_usd']
res['funding_vs_v2_usd'] = res['funding_usd'] - res['period'].map(v2f)

eng.print_comparison(res, list(VARIANTS), 'EXP 2 - FUNDING CAP')

print(f"\n  CAP ACTIVATIONS AND FUNDING SAVED")
print(f"  {'variant':<13}{'period':<24}{'activations':>12}{'trades':>8}{'units':>7}{'saved $':>10}{'funding vs v2 $':>17}")
for r in res[res['version'] != 'v2'].itertuples():
    print(f"  {r.version:<13}{r.period:<24}{r.cap_activations:>12}{r.trades_capped:>8}{r.units_not_added:>7}"
          f"{r.funding_saved_usd:>10,.0f}{r.funding_vs_v2_usd:>+17,.0f}")

names = [v for v in VARIANTS if v != 'v2']
acc = [eng.acceptance(res, v, EXPLANATION) for v in names]
eng.print_acceptance(acc)

res['verdict'] = res['version'].map({a['variant']: a['verdict'] for a in acc}).fillna('reference')
res.round(4).to_csv(os.path.join(eng.HERE, 'results', 'round2_funding_cap.csv'), index=False)
print(f"\nResults -> results/round2_funding_cap.csv")
