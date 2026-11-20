"""
Bear-market spot ladder vs the first Quattro entry signal after the cycle floor
Data: 1_data/btc_4h_2017_cache.pkl (Binance BTC/USDT 4H) + 1_data/btc_1d_2017_cache.pkl (daily, for the EMA-200).
Signal rules come from quattro_v2_engine.py: close > previous 20-bar high (Data.dhigh(20)) AND
close > daily EMA-200 (available the day after), same arithmetic as the engine.

Per cycle (peak = highest 4H high in Dec-2017 / Nov-2021):
  floor  = lowest 4H low between the peak and the first bar that trades above the peak again
  signal = first bar after the floor meeting the entry rule; the ladder is sold at the next bar's open
Ladder: equal-dollar spot limit buys at a % below the peak, active from the bar after the peak until
the signal bar. A rung fills when the bar's low touches it, at min(limit, bar open). 0.1% fee per side.
  A  -52.5% .. -60.4% : 5 rungs = 60k / 57.5k / 55k / 52.5k / 50k measured from 126,198
  B  -50% .. -70%     : -50, -55, -60, -65, -70
  C  -60% .. -75%     : -60, -65, -70, -75
Worst floating drawdown: marked at each bar's low against the capital deployed so far (buy fees included).
USDT alternative: the same dollars, from each fill to the sale, at 4% per year compounded.
"""
import os
import numpy as np
import pandas as pd
import quattro_v2_engine as eng

DATA_DIR  = os.path.join(eng.HERE, '..', '..', '1_data')
FEE       = 0.001
USDT_APY  = 0.04
PER_RUNG  = 1000.0
REF_PEAK  = 126198.0
GRID      = [-45, -50, -55, -60, -65, -70, -75]
A_PRICES  = [60000, 57500, 55000, 52500, 50000]
LADDERS = {
    'A': [-(1 - p / REF_PEAK) * 100 for p in A_PRICES],
    'B': [-50, -55, -60, -65, -70],
    'C': [-60, -65, -70, -75],
}
LADDER_NAMES = {'A': 'A -52.5..-60.4%', 'B': 'B -50..-70%', 'C': 'C -60..-75%'}
CYCLES = {
    'Dec-2017': ('2017-12-01', '2018-01-01'),
    'Nov-2021': ('2021-11-01', '2021-12-01'),
}

# -- DATA + ENGINE SIGNAL ------------------------------------------------------
df = pd.read_pickle(os.path.join(DATA_DIR, 'btc_4h_2017_cache.pkl'))
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low']  - df['close'].shift(1)).abs(),
], axis=1).max(axis=1)
df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()
d1 = pd.read_pickle(os.path.join(DATA_DIR, 'btc_1d_2017_cache.pkl'))
d1['ema200'] = d1['close'].ewm(span=200, adjust=False).mean()
avail = d1[['ema200']].copy()
avail.index = avail.index + pd.Timedelta(days=1)
df['d_ema200']     = avail.reindex(df.index, method='ffill')['ema200']
df['regime_up']    = df['close'] > df['d_ema200']
df['funding_rate'] = np.nan

data = eng.Data(df, pd.DataFrame())
dh   = data.dhigh(20)
signal = (~np.isnan(dh)) & (~np.isnan(data.atr)) & (data.close > dh) & data.reg.astype(bool)

def months(t0, t1):
    return (t1 - t0).total_seconds() / (30.4375 * 86400)

# -- CYCLES --------------------------------------------------------------------
cycles = {}
for name, (m0, m1) in CYCLES.items():
    month = np.where((data.dates >= pd.Timestamp(m0, tz='UTC')) & (data.dates < pd.Timestamp(m1, tz='UTC')))[0]
    p_i  = month[np.argmax(data.high[month])]
    peak = data.high[p_i]
    above = np.where(data.high[p_i + 1:] > peak)[0]
    rec_i = p_i + 1 + above[0] if len(above) else data.n
    win  = np.arange(p_i + 1, rec_i)
    f_i  = win[np.argmin(data.low[win])]
    s_i  = f_i + 1 + np.argmax(signal[f_i + 1:])
    cycles[name] = dict(p_i=p_i, peak=peak, f_i=f_i, floor=data.low[f_i], s_i=s_i, sell_i=s_i + 1,
                        rec=data.dates[rec_i] if rec_i < data.n else None)

print("\n  CYCLES (4H bars; dates are bar open times, UTC)")
print(f"  {'cycle':<10}{'peak':>12}  {'peak date':<17}{'floor':>11}  {'floor date':<17}{'floor vs peak':>14}"
      f"  {'1st signal bar':<17}{'signal close':>13}  {'sale (next open)':<17}{'sale price':>11}")
for name, c in cycles.items():
    print(f"  {name:<10}{c['peak']:>12,.2f}  {data.dates[c['p_i']]:%Y-%m-%d %H:%M}  {c['floor']:>11,.2f}  "
          f"{data.dates[c['f_i']]:%Y-%m-%d %H:%M}  {(c['floor']/c['peak']-1)*100:>13.1f}%  "
          f"{data.dates[c['s_i']]:%Y-%m-%d %H:%M}  {data.close[c['s_i']]:>13,.2f}  "
          f"{data.dates[c['sell_i']]:%Y-%m-%d %H:%M}  {data.open[c['sell_i']]:>11,.2f}")

# -- LADDER SIMULATION ---------------------------------------------------------
def simulate(rungs_pct, c):
    prices = [c['peak'] * (1 + p / 100) for p in rungs_pct]
    fills  = {}                                   # rung index -> (bar, fill price, btc)
    worst  = 0.0
    invested = btc = 0.0
    for j in range(c['p_i'] + 1, c['sell_i']):
        for k, px in enumerate(prices):
            if k not in fills and data.low[j] <= px:
                fpx = min(px, data.open[j])
                b = PER_RUNG * (1 - FEE) / fpx
                fills[k] = (j, fpx, b)
                invested += PER_RUNG
                btc += b
        if invested:
            worst = min(worst, btc * data.low[j] / invested - 1)
    sell_px = data.open[c['sell_i']]
    t_sell  = data.dates[c['sell_i']]
    out = {'rungs': len(prices), 'filled': len(fills), 'prices': prices, 'fills': fills, 'sell_px': sell_px}
    if not fills:
        return out
    proceeds = btc * sell_px * (1 - FEE)
    usdt = sum(PER_RUNG * (1 + USDT_APY) ** ((t_sell - data.dates[j]).total_seconds() / (365.25 * 86400))
               for j, _, _ in fills.values())
    first_fill = min(data.dates[j] for j, _, _ in fills.values())
    out.update({
        'invested': invested,
        'avg_buy': invested / sum(PER_RUNG / fpx for _, fpx, _ in fills.values()),
        'return_pct': (proceeds / invested - 1) * 100,
        'worst_float_pct': worst * 100,
        'first_fill': first_fill,
        'months_from_first': months(first_fill, t_sell),
        'months_weighted': np.mean([months(data.dates[j], t_sell) for j, _, _ in fills.values()]),
        'usdt_pct': (usdt / invested - 1) * 100,
        'proceeds': proceeds, 'usdt_value': usdt,
    })
    return out

# Rung-level fills (full grid + ladder A rungs)
print("\n  RUNG FILLS - first touch between the peak and the sale (fill price = min(limit, bar open))")
rung_set = [(f"grid {p}%", p) for p in GRID] + [(f"A {pr/1000:g}k eq. ({p:.2f}%)", p) for pr, p in zip(A_PRICES, LADDERS['A'])]
for name, c in cycles.items():
    print(f"\n  {name}")
    print(f"  {'rung':<26}{'limit price':>13}  {'filled':<8}{'fill date':<18}{'fill price':>12}")
    for label, p in rung_set:
        r = simulate([p], c)
        if r['filled']:
            j, fpx, _ = r['fills'][0]
            print(f"  {label:<26}{r['prices'][0]:>13,.2f}  {'yes':<8}{data.dates[j]:%Y-%m-%d %H:%M}  {fpx:>12,.2f}")
        else:
            print(f"  {label:<26}{r['prices'][0]:>13,.2f}  {'no':<8}")

print(f"\n  LADDERS - ${PER_RUNG:,.0f} per rung, spot, 0.1% fee per side, sold at the open after the first signal")
print(f"  {'cycle':<10}{'ladder':<17}{'filled':>8}{'avg buy':>11}{'sale':>11}{'return':>9}{'worst float':>13}"
      f"{'months (1st fill)':>19}{'months (avg $)':>16}{'USDT 4%':>9}{'diff pp':>9}")
rows = []
for name, c in cycles.items():
    for key, rungs in LADDERS.items():
        r = simulate(rungs, c)
        if not r['filled']:
            print(f"  {name:<10}{LADDER_NAMES[key]:<17}{'0/' + str(r['rungs']):>8}   no fills")
            continue
        print(f"  {name:<10}{LADDER_NAMES[key]:<17}{str(r['filled']) + '/' + str(r['rungs']):>8}{r['avg_buy']:>11,.0f}"
              f"{r['sell_px']:>11,.0f}{r['return_pct']:>+8.1f}%{r['worst_float_pct']:>12.1f}%"
              f"{r['months_from_first']:>19.1f}{r['months_weighted']:>16.1f}{r['usdt_pct']:>+8.1f}%"
              f"{r['return_pct'] - r['usdt_pct']:>+9.1f}")
