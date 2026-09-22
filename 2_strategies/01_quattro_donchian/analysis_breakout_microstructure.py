"""
Breakout microstructure - Donchian-20 breakouts on BTC/USDT 4H by hour / day / weekend / period
Descriptive price study only: no position management, no EMA-200 filter.

Events : every bar whose close > max(high of the previous 20 bars)  (rolling(20).max().shift(1))
Data   : 1_data/btc_4h_2019_cache.pkl (Binance spot, 2019-01 to 2026-09; built by 1_data/fetch_btc_2019_data.py)
ATR    : ATR14 Wilder (ewm alpha=1/14), same as the Quattro backtests, taken at the breakout bar
Labels (all by the bar's CLOSE time, UTC):
  hour    : 00/04/08/12/16/20  ("00:00" = bar opening 20:00 the previous day)
  dow     : day of week of the close
  weekend : bar fully inside Fri 20:00 -> Sun 20:00, i.e. close in (Fri 20:00, Sun 20:00]
  period  : 2019-2021 / 2022-2023 / 2024-2026
Measures (in ATR of the breakout bar, t = breakout bar):
  false   : min(low t+1..t+5) <= close_t - 2*ATR
  adv     : max(high t+1..t+20) - close_t
  retr    : close_t - min(low t+1..t+20)          (positive number)
  ret_k   : close_{t+k} - close_t,  k = 5, 10, 20
Samples: 'all' = every breakout bar; 'fresh' = breakout bar whose previous bar was not a
breakout (consecutive breakouts share forward windows, so they are not independent).
Tests  : two-sided two-proportion z-test on the false rate (+ Fisher exact p), per period,
         and a difference-in-differences z for (2024-2026) minus (2019-2021).
"""
import os
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE      = os.path.dirname(os.path.abspath(__file__))
CACHE     = os.path.join(HERE, '..', '..', '1_data', 'btc_4h_2019_cache.pkl')
OUT_DIR   = os.path.join(HERE, 'results')
SKIP_BARS = 100          # ATR warm-up
FWD       = 20
MIN_N     = 30
HOURS     = [0, 4, 8, 12, 16, 20]
DOWS      = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
PERIODS   = ['2019-2021', '2022-2023', '2024-2026']

# -- DATA + INDICATORS ---------------------------------------------------------

df = pd.read_pickle(CACHE)
print(f"4H cache: {len(df)} bars  {df.index[0]} -> {df.index[-1]}")

df['donch_high_20'] = df['high'].rolling(20).max().shift(1)
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low']  - df['close'].shift(1)).abs(),
], axis=1).max(axis=1)
df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()

high_, low_, close_ = df['high'].values, df['low'].values, df['close'].values
atr_   = df['atr14'].values
brk    = (df['close'] > df['donch_high_20']).values
n      = len(df)

# -- EVENTS --------------------------------------------------------------------

rows = []
for i in range(SKIP_BARS, n - FWD):
    if not brk[i]:
        continue
    c, a = close_[i], atr_[i]
    rows.append({
        'open_time': df.index[i],
        'close_px':  c,
        'atr':       a,
        'fresh':     not brk[i-1],
        'false':     low_[i+1:i+6].min() <= c - 2 * a,
        'adv':       (high_[i+1:i+FWD+1].max() - c) / a,
        'retr':      (c - low_[i+1:i+FWD+1].min()) / a,
        'ret5':      (close_[i+5]  - c) / a,
        'ret10':     (close_[i+10] - c) / a,
        'ret20':     (close_[i+20] - c) / a,
    })
ev = pd.DataFrame(rows)

close_t      = ev['open_time'] + pd.Timedelta(hours=4)
ev['hour']   = close_t.dt.hour
ev['dow']    = close_t.dt.dayofweek.map(dict(enumerate(DOWS)))
week_h       = close_t.dt.dayofweek * 24 + close_t.dt.hour        # Mon 00:00 = 0
ev['weekend'] = np.where((week_h > 4*24 + 20) & (week_h <= 6*24 + 20), 'weekend', 'weekday')
ev['period'] = pd.cut(close_t.dt.year, bins=[2018, 2021, 2023, 2026], labels=PERIODS).astype(str)

print(f"Breakout events: {len(ev)} ({ev['fresh'].sum()} fresh)  "
      f"{ev['open_time'].iloc[0].date()} -> {ev['open_time'].iloc[-1].date()}  (events without {FWD} forward bars dropped)")

# -- GROUP STATS ---------------------------------------------------------------

def group_stats(sub):
    return pd.Series({
        'n':           len(sub),
        'false_rate':  sub['false'].mean() * 100,
        'mean_adv':    sub['adv'].mean(),
        'mean_retr':   sub['retr'].mean(),
        'mean_ret5':   sub['ret5'].mean(),
        'mean_ret10':  sub['ret10'].mean(),
        'mean_ret20':  sub['ret20'].mean(),
        'median_ret20': sub['ret20'].median(),
    })

ORDER = {'hour': HOURS, 'dow': DOWS, 'weekend': ['weekday', 'weekend'], 'period': PERIODS}

stat_rows = []
for sample, s_ev in [('all', ev), ('fresh', ev[ev['fresh']])]:
    for dim, levels in ORDER.items():
        scopes = [('All', s_ev)] + ([] if dim == 'period' else [(p, s_ev[s_ev['period'] == p]) for p in PERIODS])
        for scope, sub in scopes:
            for lvl in levels:
                g = sub[sub[dim] == lvl]
                st = group_stats(g)
                stat_rows.append({'sample': sample, 'grouping': dim, 'group': f"{lvl:02d}:00" if dim == 'hour' else lvl,
                                  'period': scope, **st.to_dict(), 'inconclusive_n_lt_30': st['n'] < MIN_N})
gs = pd.DataFrame(stat_rows)
gs['n'] = gs['n'].astype(int)

# -- TESTS ---------------------------------------------------------------------

def grp_A(e): return e[(e['weekend'] == 'weekday') & e['hour'].isin([12, 16])]
def grp_B(e): return e[e['hour'].isin([0, 4])]
def grp_C(e): return e[e['weekend'] == 'weekend']

COMPARISONS = [
    ('weekday close 12/16 vs close 00/04', grp_A, grp_B),
    ('weekday close 12/16 vs weekend',     grp_A, grp_C),
]

def prop_test(a, b):
    x1, n1, x2, n2 = int(a['false'].sum()), len(a), int(b['false'].sum()), len(b)
    p1, p2 = x1 / n1, x2 / n2
    pool   = (x1 + x2) / (n1 + n2)
    se     = np.sqrt(pool * (1 - pool) * (1/n1 + 1/n2))
    z      = (p1 - p2) / se if se > 0 else np.nan
    fisher = stats.fisher_exact([[x1, n1 - x1], [x2, n2 - x2]])[1]
    se_un  = np.sqrt(p1*(1-p1)/n1 + p2*(1-p2)/n2)                  # unpooled, for diff-in-diff
    return dict(n_A=n1, false_A=x1, rate_A=p1*100, n_B=n2, false_B=x2, rate_B=p2*100,
                diff_pp=(p1 - p2)*100, z=z, p_value=2*stats.norm.sf(abs(z)), fisher_p=fisher,
                se_unpooled_pp=se_un*100,
                inconclusive_n_lt_30=min(n1, n2) < MIN_N)

test_rows = []
for sample, s_ev in [('all', ev), ('fresh', ev[ev['fresh']])]:
    for name, fa, fb in COMPARISONS:
        per = {}
        for scope in ['All'] + PERIODS:
            sub = s_ev if scope == 'All' else s_ev[s_ev['period'] == scope]
            res = prop_test(fa(sub), fb(sub))
            per[scope] = res
            test_rows.append({'sample': sample, 'comparison': name, 'period': scope, **res})
        # 3e: is the A-B gap different in 2024-2026 than in 2019-2021?
        d_new, d_old = per['2024-2026'], per['2019-2021']
        did = d_new['diff_pp'] - d_old['diff_pp']
        se  = np.sqrt(d_new['se_unpooled_pp']**2 + d_old['se_unpooled_pp']**2)
        z   = did / se
        test_rows.append({'sample': sample, 'comparison': name, 'period': 'DiD 2024-2026 minus 2019-2021',
                          'diff_pp': did, 'z': z, 'p_value': 2*stats.norm.sf(abs(z)), 'se_unpooled_pp': se,
                          'inconclusive_n_lt_30': d_new['inconclusive_n_lt_30'] or d_old['inconclusive_n_lt_30']})
tests = pd.DataFrame(test_rows)

# -- PRINT ---------------------------------------------------------------------

def show(dim, scope='All', sample='all'):
    t = gs[(gs['sample'] == sample) & (gs['grouping'] == dim) & (gs['period'] == scope)]
    print(f"\n  by {dim}  (sample={sample}, period={scope})")
    print(f"  {'group':<10}{'n':>6}{'false %':>9}{'adv ATR':>9}{'retr ATR':>10}{'ret5':>8}{'ret10':>8}{'ret20':>8}  flag")
    for r in t.itertuples():
        flag = 'n<30 inconclusive' if r.inconclusive_n_lt_30 else ''
        print(f"  {r.group:<10}{r.n:>6}{r.false_rate:>9.1f}{r.mean_adv:>9.2f}{r.mean_retr:>10.2f}"
              f"{r.mean_ret5:>+8.2f}{r.mean_ret10:>+8.2f}{r.mean_ret20:>+8.2f}  {flag}")

print("\n" + "=" * 90 + "\n  GROUP TABLES (all breakouts, all periods)\n" + "=" * 90)
for dim in ['hour', 'dow', 'weekend', 'period']:
    show(dim)
print("\n" + "=" * 90 + "\n  HOUR x PERIOD (all breakouts)\n" + "=" * 90)
for p in PERIODS:
    show('hour', p)

print("\n" + "=" * 90 + "\n  FALSE-RATE TESTS (A - B, two-sided)\n" + "=" * 90)
for sample in ['all', 'fresh']:
    for name, _, _ in COMPARISONS:
        print(f"\n  {name}   (sample={sample})")
        print(f"  {'period':<32}{'n_A':>6}{'rate_A':>8}{'n_B':>6}{'rate_B':>8}{'diff pp':>9}{'z':>7}{'p':>8}{'fisher p':>10}")
        t = tests[(tests['sample'] == sample) & (tests['comparison'] == name)]
        for r in t.itertuples():
            if r.period.startswith('DiD'):
                print(f"  {r.period:<32}{'':>6}{'':>8}{'':>6}{'':>8}{r.diff_pp:>+9.1f}{r.z:>7.2f}{r.p_value:>8.3f}")
            else:
                flag = '  n<30' if r.inconclusive_n_lt_30 else ''
                print(f"  {r.period:<32}{r.n_A:>6.0f}{r.rate_A:>7.1f}%{r.n_B:>6.0f}{r.rate_B:>7.1f}%"
                      f"{r.diff_pp:>+9.1f}{r.z:>7.2f}{r.p_value:>8.3f}{r.fisher_p:>10.3f}{flag}")

# -- SAVE ----------------------------------------------------------------------

os.makedirs(OUT_DIR, exist_ok=True)
gs.round(4).to_csv(os.path.join(OUT_DIR, 'breakout_microstructure.csv'), index=False)
tests.round(4).to_csv(os.path.join(OUT_DIR, 'breakout_microstructure_tests.csv'), index=False)

# -- CHARTS --------------------------------------------------------------------
# Palette: dataviz reference categorical slots 1-3 (validated all-pairs, light surface).
SURFACE, INK, INK_2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
PERIOD_COLORS = dict(zip(PERIODS, ['#2a78d6', '#eb6834', '#1baf7a']))

def hour_chart(metric, ylabel, title, fname):
    t = gs[(gs['sample'] == 'all') & (gs['grouping'] == 'hour') & (gs['period'].isin(PERIODS))]
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    fig.patch.set_facecolor(SURFACE); ax.set_facecolor(SURFACE)
    x, w = np.arange(len(HOURS)), 0.26
    for k, p in enumerate(PERIODS):
        tp = t[t['period'] == p].set_index('group').loc[[f"{h:02d}:00" for h in HOURS]]
        for j, (val, inc) in enumerate(zip(tp[metric], tp['inconclusive_n_lt_30'])):
            ax.bar(x[j] + (k - 1) * w, val, width=w, color=PERIOD_COLORS[p],
                   alpha=0.35 if inc else 1.0, hatch='///' if inc else None,
                   edgecolor=SURFACE, linewidth=1.5, zorder=3)
    ax.axhline(0, color=INK_2, linewidth=0.8, zorder=4)
    ax.set_xticks(x, [f"{h:02d}:00" for h in HOURS], color=INK_2)
    ax.tick_params(axis='y', colors=INK_2, length=0); ax.tick_params(axis='x', length=0)
    ax.set_xlabel('Bar close hour (UTC)', color=INK_2)
    ax.set_ylabel(ylabel, color=INK_2)
    ax.grid(axis='y', color=GRID, linewidth=0.8, zorder=0)
    for s in ['top', 'right', 'left']:
        ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color(GRID)
    handles = [plt.Rectangle((0, 0), 1, 1, color=PERIOD_COLORS[p]) for p in PERIODS]
    handles.append(plt.Rectangle((0, 0), 1, 1, facecolor='#9a9994', alpha=0.35, hatch='///', edgecolor=SURFACE))
    ax.legend(handles, PERIODS + ['n < 30 (inconclusive)'], frameon=False, ncol=4,
              loc='lower left', bbox_to_anchor=(0, 1.0), labelcolor=INK)
    fig.suptitle(title, x=0.01, y=0.99, ha='left', fontsize=13, color=INK, fontweight='bold')
    fig.text(0.01, 0.925, f"BTC/USDT 4H, every Donchian-20 breakout (no EMA filter), n = {len(ev)}. "
             "Table view: results/breakout_microstructure.csv", ha='left', fontsize=9, color=INK_2)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(os.path.join(OUT_DIR, fname), facecolor=SURFACE)
    plt.close(fig)

hour_chart('false_rate', 'False breakouts (%)',
           'False-breakout rate by bar close hour (touch of close - 2 ATR within 5 bars)',
           'breakout_false_rate_by_hour.png')
hour_chart('mean_ret20', 'Mean return after 20 bars (ATR)',
           'Mean 20-bar return after a breakout, by bar close hour',
           'breakout_ret20_by_hour.png')

print("\nSaved -> results/breakout_microstructure.csv, results/breakout_microstructure_tests.csv,")
print("         results/breakout_false_rate_by_hour.png, results/breakout_ret20_by_hour.png")
