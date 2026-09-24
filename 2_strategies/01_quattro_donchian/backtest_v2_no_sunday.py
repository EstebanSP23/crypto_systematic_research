"""
Round 2 - Experiment 1: no new entries when the signal bar closes on Sunday (UTC)
Engine: quattro_v2_engine.py (v2 with taker fees + Binance funding), compared against v2.

  v2          : v2 as is
  1a_no_sun   : a breakout whose signal bar closes on Sunday UTC does not open a trade
                (if the breakout still holds on a later non-Sunday bar, that bar can enter)
  1b_no_sun_pyr : 1a + no pyramid unit is added on a bar that closes on Sunday; the unit is
                deferred to the next allowed bar and filled at max(trigger, open)

Caveat: the Sunday idea comes from analysis_breakout_microstructure.py, which looked at
2019-2026 data, so P1/P2 are not out-of-sample for this hypothesis.
"""
import os
import pandas as pd
import quattro_v2_engine as eng

data = eng.load_data()
eng.verify_v2(data)

SUNDAY = 6
closes_sunday = (data.close_time.dayofweek == SUNDAY)

def no_sunday_entry(i):
    return not closes_sunday[i]

def no_sunday_unit(sub, i, k):
    return 'defer' if closes_sunday[i] else 'ok'

VARIANTS = {
    'v2':            dict(),
    '1a_no_sun':     dict(allow_entry=no_sunday_entry),
    '1b_no_sun_pyr': dict(allow_entry=no_sunday_entry, allow_unit=no_sunday_unit),
}
EXPLANATION = ("Sunday-close breakouts happen in the thinnest liquidity of the week (CME, ETFs and most "
               "desks closed), so they are more often noise that reverses when volume returns.")

rows, extra = [], {}
for name, kw in VARIANTS.items():
    print(f"Running {name}...")
    trades, book, sub = eng.run_single(data, **kw)
    rows += eng.split_metrics(trades, data, name)
    deferred = [e for e in sub.events if e['action'] == 'defer']
    extra[name] = {
        'sunday_entries': int((trades['entry_date'].dt.dayofweek == SUNDAY).sum()),
        'deferred_unit_bars': len(deferred),
    }
res = pd.DataFrame(rows)

print(f"\n  Blocked Sunday signals in v2 would be: {extra['v2']['sunday_entries']} of "
      f"{int(res[(res['version']=='v2') & (res['period']==eng.PERIODS[0])]['trades'].iloc[0])} entries")
for name in ['1a_no_sun', '1b_no_sun_pyr']:
    print(f"  {name}: entries on Sunday-close signal bars = {extra[name]['sunday_entries']}, "
          f"bars with a deferred pyramid unit = {extra[name]['deferred_unit_bars']}")

eng.print_comparison(res, list(VARIANTS), 'EXP 1 - NO SUNDAY ENTRIES')
acc = [eng.acceptance(res, v, EXPLANATION) for v in ['1a_no_sun', '1b_no_sun_pyr']]
eng.print_acceptance(acc)

verdict = {a['variant']: a['verdict'] for a in acc}
res['verdict'] = res['version'].map(verdict).fillna('reference')
out = os.path.join(eng.HERE, 'results', 'round2_no_sunday.csv')
res.round(4).to_csv(out, index=False)
print(f"\nResults -> results/round2_no_sunday.csv")
