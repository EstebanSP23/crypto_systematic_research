"""
Continuous backtest 2018-01-01 -> today, $1,000 start, compounding, real costs
Engine: quattro_v2_engine.py (taker 0.06% per side + funding debited from the balance).

  A_quattro_20_10 : Quattro = Donchian 20/10 alone, full risk (2% per unit)
  B_55_20         : Donchian 55/20 alone, full risk
  C_20_10+55_20   : both legs at 1/2 risk each on a shared balance (as in Round 3)
  buy_hold        : BTC bought at the 2018-01-01 00:00 open, no fees (reference)

Data : 1_data/btc_4h_2017_cache.pkl (Binance spot 4H from 2017-08-17, built by 1_data/fetch_btc_4h_2017.py)
       + Binance daily candles fetched live from 2017-08-17 for the EMA-200 regime filter.
       Binance has no BTC/USDT history before 2017-08-17, so on 2018-01-01 the daily EMA-200 rests on
       only 137 daily closes (seed weight ~25%, below 5% by July 2018).
Funding: real Binance BTC/USDT:USDT settlements from 2019-09-10 08:00; before that the perpetual did
       not exist and 0.01% per 8h settlement (00/08/16 UTC) is assumed.
Max DD : on mark-to-market equity = balance + unrealized P&L of open units at each 4H bar close.
"""
import os
import ccxt
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import quattro_v2_engine as eng

DATA_DIR     = os.path.join(eng.HERE, '..', '..', '1_data')
OUT_DIR      = os.path.join(eng.HERE, 'results')
START        = pd.Timestamp('2018-01-01', tz='UTC')
START_BAL    = 1000.0
SYNTH_RATE   = 0.0001
R, H         = eng.RISK_PCT, eng.HARD_STOP_PCT

def leg(e, x, frac):
    return dict(name=f'd{e}_{x}', entry_len=e, exit_len=x, risk_pct=R * frac, hard_stop_pct=H * frac)

CONFIGS = {
    'A_quattro_20_10': [leg(20, 10, 1)],
    'B_55_20':         [leg(55, 20, 1)],
    'C_20_10+55_20':   [leg(20, 10, 0.5), leg(55, 20, 0.5)],
}
LABELS = {'A_quattro_20_10': 'A  Quattro 20/10', 'B_55_20': 'B  55/20 alone',
          'C_20_10+55_20': 'C  20/10 + 55/20', 'buy_hold': 'BTC buy & hold'}

# -- ENGINE CHECK --------------------------------------------------------------
live = eng.load_data()
eng.verify_v2(live)

# -- DATA ----------------------------------------------------------------------
df = pd.read_pickle(os.path.join(DATA_DIR, 'btc_4h_2017_cache.pkl'))
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low']  - df['close'].shift(1)).abs(),
], axis=1).max(axis=1)
df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()

ex = ccxt.binance()
raw_d = eng._fetch_full('BTC/USDT', '1d', ex.parse8601('2017-08-17T00:00:00Z'), ex)
d1 = pd.DataFrame(raw_d, columns=['ts','open','high','low','close','volume'])
d1 = d1[d1['ts'] + 86400000 <= ex.milliseconds()]            # drop today's forming candle
d1['dt'] = pd.to_datetime(d1['ts'], unit='ms', utc=True)
d1 = d1.set_index('dt').drop(columns='ts')
d1['ema200'] = d1['close'].ewm(span=200, adjust=False).mean()
avail = d1[['ema200']].copy()
avail.index = avail.index + pd.Timedelta(days=1)
df['d_ema200']  = avail.reindex(df.index, method='ffill')['ema200']
df['regime_up'] = df['close'] > df['d_ema200']

fund = pd.read_csv(eng.FUNDING_CSV)
fund['bar'] = pd.to_datetime(fund['timestamp_ms'], unit='ms', utc=True).dt.floor('h')
REAL_FUNDING_START = fund['bar'].iloc[0]
df['funding_rate'] = fund.set_index('bar')['funding_rate'].reindex(df.index)
settle = df.index.hour.isin([0, 8, 16])
synthetic = settle & (df.index < REAL_FUNDING_START)
df.loc[synthetic, 'funding_rate'] = SYNTH_RATE
missing_real = int((settle & (df.index >= REAL_FUNDING_START) & df['funding_rate'].isna()).sum())

first = df.index.searchsorted(START)
data  = eng.Data(df.iloc[first - eng.WARMUP:], fund)
T_END = data.dates[-1] + pd.Timedelta(hours=4)
YEARS = (T_END - START).total_seconds() / (365.25 * 86400)
print(f"  4H cache {df.index[0]} -> {df.index[-1]} | trading {data.dates[eng.WARMUP]} -> {data.dates[-1]} "
      f"({YEARS:.2f} years)")
print(f"  Funding: synthetic 0.01% on {int(synthetic.sum())} settlements before {REAL_FUNDING_START}; "
      f"real settlements without a rate after it: {missing_real}")
print(f"  Daily EMA-200 seed: {int((d1.index < START).sum())} daily closes before {START.date()}")


# -- RUN WITH MARK-TO-MARKET EQUITY --------------------------------------------
def run_mtm(legs, funding_override=None):
    d = data
    if funding_override is not None:
        d = eng.Data(data.df.assign(funding_rate=funding_override), fund)
    book = eng.Book(START_BAL)
    subs = [eng.Subsystem(book, d, **kw) for kw in legs]
    eq = np.full(d.n, np.nan)
    for i in range(eng.WARMUP, d.n - 1):
        for s in subs:
            s.step(i)
        unreal = sum((d.close[i] - u['entry_price']) * u['size']
                     for s in subs if s.in_trade for u in s.units if u['entry_bar'] <= i)
        eq[i] = book.balance + unreal
    for s in subs:
        s.finish(d.n - 1)
    eq[d.n - 1] = book.balance
    trades = pd.concat([pd.DataFrame(s.trades) for s in subs], ignore_index=True)
    trades = trades.sort_values(['exit_date', 'entry_date'], kind='stable').reset_index(drop=True)
    curve = pd.Series(eq[eng.WARMUP:], index=d.close_time[eng.WARMUP:])
    curve = pd.concat([pd.Series([START_BAL], index=[START]), curve])
    return trades, curve, book.balance


def max_dd(curve):
    return ((curve / curve.cummax()) - 1).min() * 100

bh_curve = pd.concat([pd.Series([START_BAL], index=[START]),
                      pd.Series(START_BAL * data.close[eng.WARMUP:] / data.open[eng.WARMUP],
                                index=data.close_time[eng.WARMUP:])])

runs, summary = {}, []
for name, legs in CONFIGS.items():
    print(f"Running {name}...")
    trades, curve, final = run_mtm(legs)
    runs[name] = (trades, curve)
    apy  = ((final / START_BAL) ** (1 / YEARS) - 1) * 100
    dd   = max_dd(curve)
    wins, loss = trades[trades['pnl_usd'] > 0], trades[trades['pnl_usd'] <= 0]
    closed = pd.concat([pd.Series([START_BAL]), trades['account']])
    no_synth = run_mtm(legs, funding_override=df['funding_rate'].where(~synthetic, 0.0).iloc[first - eng.WARMUP:])[2]
    summary.append({
        'config': name, 'total_return_pct': (final / START_BAL - 1) * 100, 'final_balance': final,
        'apy_pct': apy, 'max_dd_mtm_pct': dd, 'calmar': apy / abs(dd), 'trades': len(trades),
        'win_rate_pct': len(wins) / len(trades) * 100, 'avg_win_R': wins['R'].mean(), 'avg_loss_R': loss['R'].mean(),
        'fees_usd': trades['fees_usd'].sum(), 'funding_usd': trades['funding_usd'].sum(),
        'total_costs_usd': trades['fees_usd'].sum() + trades['funding_usd'].sum(),
        'max_dd_closed_trades_pct': ((closed / closed.cummax()) - 1).min() * 100,
        'final_if_no_synthetic_funding': no_synth,
    })
bh_final = bh_curve.iloc[-1]
bh_apy = ((bh_final / START_BAL) ** (1 / YEARS) - 1) * 100
summary.append({'config': 'buy_hold', 'total_return_pct': (bh_final / START_BAL - 1) * 100, 'final_balance': bh_final,
                'apy_pct': bh_apy, 'max_dd_mtm_pct': max_dd(bh_curve), 'calmar': bh_apy / abs(max_dd(bh_curve))})
summ = pd.DataFrame(summary)

# -- CALENDAR YEARS ------------------------------------------------------------
curves = {**{k: v[1] for k, v in runs.items()}, 'buy_hold': bh_curve}
yearly = []
for y in range(2018, T_END.year + 1):
    y0, y1 = pd.Timestamp(f'{y}-01-01', tz='UTC'), pd.Timestamp(f'{y+1}-01-01', tz='UTC')
    row = {'year': f'{y}' + (' YTD' if y1 > T_END else '')}
    for k, c in curves.items():
        seg = c[(c.index >= y0) & (c.index <= y1)]
        start_val = c[c.index <= y0].iloc[-1]
        seg = pd.concat([pd.Series([start_val], index=[y0]), seg[seg.index > y0]])
        row[f'{k}_return_pct'] = (seg.iloc[-1] / start_val - 1) * 100
        row[f'{k}_max_dd_pct'] = max_dd(seg)
    yearly.append(row)
yr = pd.DataFrame(yearly)

# -- PRINT ---------------------------------------------------------------------
print(f"\n{'=' * 118}\n  SUMMARY {START.date()} -> {data.dates[-1].date()}  (${START_BAL:,.0f} start, compounding, "
      f"taker 0.06% + funding)\n{'=' * 118}")
print(f"  {'config':<20}{'return %':>11}{'final $':>11}{'APY %':>8}{'MaxDD MTM':>11}{'Calmar':>8}{'trades':>8}"
      f"{'win %':>7}{'avgW R':>8}{'avgL R':>8}{'costs $':>10}{'fees $':>9}{'fund $':>9}")
for r in summ.itertuples():
    extra = '' if r.config == 'buy_hold' else (f"{r.trades:>8.0f}{r.win_rate_pct:>7.1f}{r.avg_win_R:>+8.2f}{r.avg_loss_R:>+8.2f}"
                                               f"{r.total_costs_usd:>10,.0f}{r.fees_usd:>9,.0f}{r.funding_usd:>9,.0f}")
    print(f"  {LABELS[r.config]:<20}{r.total_return_pct:>+11,.0f}{r.final_balance:>11,.0f}{r.apy_pct:>+8.1f}"
          f"{r.max_dd_mtm_pct:>11.1f}{r.calmar:>8.2f}{extra}")
print("\n  Reference: max DD on closed trades only / final balance if pre-2019-09-10 funding were 0 instead of 0.01%:")
for r in summ[summ['config'] != 'buy_hold'].itertuples():
    print(f"    {LABELS[r.config]:<20} closed-trade DD {r.max_dd_closed_trades_pct:.1f}%  |  "
          f"no synthetic funding ${r.final_if_no_synthetic_funding:,.0f} (vs ${r.final_balance:,.0f})")

print(f"\n  CALENDAR YEARS - return % / max DD % (mark-to-market)")
print(f"  {'year':<10}" + ''.join(f"{LABELS[k][:18]:>24}" for k in curves))
for d in yr.to_dict('records'):
    print(f"  {d['year']:<10}" + ''.join(f"{d[k + '_return_pct']:>+13.1f} / {d[k + '_max_dd_pct']:>6.1f}" for k in curves))

# -- SAVE ----------------------------------------------------------------------
out = pd.concat([summ.assign(section='summary'),
                 yr.assign(section='calendar_year')], ignore_index=True)
out.insert(0, 'section', out.pop('section'))
out.round(4).to_csv(os.path.join(OUT_DIR, 'backtest_2018_2026.csv'), index=False)

daily = pd.DataFrame({k: c for k, c in curves.items()})
daily.index = daily.index - pd.Timedelta(hours=4)             # bar open time -> the day the bar belongs to
daily = daily.groupby(daily.index.floor('D')).last()
daily.index = daily.index.date
daily.index.name = 'date'
daily.round(2).to_csv(os.path.join(OUT_DIR, 'equity_2018_2026.csv'))

# -- CHARTS --------------------------------------------------------------------
# dataviz reference palette: categorical slots 1-3 (validated all-pairs, light), B&H as neutral reference
SURFACE, INK, INK_2, GRID, REF = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df', '#8a8984'
COLORS = {'A_quattro_20_10': '#2a78d6', 'B_55_20': '#eb6834', 'C_20_10+55_20': '#1baf7a', 'buy_hold': REF}

def style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis='y', color=GRID, linewidth=0.8, zorder=0)
    for s in ['top', 'right', 'left']:
        ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color(GRID)
    ax.tick_params(colors=INK_2, length=0)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

def funding_line(ax, label=True):
    ax.axvline(REAL_FUNDING_START, color=INK_2, linewidth=1, linestyle=(0, (4, 3)), zorder=2)
    if label:
        ax.annotate('Real funding from 2019-09-10\n(before: 0.01% per 8h assumed)', xy=(REAL_FUNDING_START, 1),
                    xycoords=('data', 'axes fraction'), xytext=(6, -4), textcoords='offset points',
                    va='top', fontsize=8.5, color=INK_2)

fig, ax = plt.subplots(figsize=(11, 6), dpi=150)
fig.patch.set_facecolor(SURFACE); style(ax)
for k in ['buy_hold', 'A_quattro_20_10', 'B_55_20', 'C_20_10+55_20']:
    c = curves[k]
    ax.plot(c.index, c.values, color=COLORS[k], linewidth=1.4 if k != 'buy_hold' else 1.2,
            linestyle='-' if k != 'buy_hold' else (0, (5, 3)), label=LABELS[k], zorder=3)
    ax.annotate(f"${c.iloc[-1]:,.0f}", xy=(c.index[-1], c.iloc[-1]), xytext=(5, 0), textcoords='offset points',
                va='center', fontsize=8.5, color=INK)
ax.set_yscale('log')
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
ax.set_ylabel('Equity (log scale)', color=INK_2)
funding_line(ax)
ax.legend(frameon=False, loc='lower left', bbox_to_anchor=(0, 1.0), ncol=4, labelcolor=INK)
ax.set_xlim(START, T_END + pd.Timedelta(days=150))
fig.suptitle('Equity 2018-2026 from $1,000 (fees + funding, compounding)', x=0.01, y=0.99, ha='left',
             fontsize=13, color=INK, fontweight='bold')
fig.text(0.01, 0.935, 'BTC/USDT 4H, Donchian breakout with 4-unit pyramid; equity marked to market at each 4H close. '
         'Table view: results/equity_2018_2026.csv', ha='left', fontsize=9, color=INK_2)
fig.tight_layout(rect=(0, 0, 1, 0.925))
fig.savefig(os.path.join(OUT_DIR, 'equity_2018_2026.png'), facecolor=SURFACE)
plt.close(fig)

fig, axes = plt.subplots(3, 1, figsize=(11, 7.5), dpi=150, sharex=True, sharey=True)
fig.patch.set_facecolor(SURFACE)
for ax, k in zip(axes, CONFIGS):
    style(ax)
    dd = (curves[k] / curves[k].cummax() - 1) * 100
    ax.fill_between(dd.index, dd.values, 0, color=COLORS[k], alpha=0.25, linewidth=0, zorder=2)
    ax.plot(dd.index, dd.values, color=COLORS[k], linewidth=1.1, zorder=3)
    ax.set_title(f"{LABELS[k]}   max {dd.min():.1f}%", loc='left', fontsize=10, color=INK, fontweight='bold')
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlim(START, T_END)
    funding_line(ax, label=False)
axes[1].set_ylabel('Drawdown from peak (mark-to-market)', color=INK_2)
fig.suptitle('Drawdown 2018-2026', x=0.01, y=0.99, ha='left', fontsize=13, color=INK, fontweight='bold')
fig.text(0.01, 0.955, 'Equity marked to market at each 4H close; fees + funding included. Table view: '
         'results/equity_2018_2026.csv\nDashed line: real funding from 2019-09-10 (before: 0.01% per 8h assumed)',
         ha='left', va='top', fontsize=9, color=INK_2)
fig.tight_layout(rect=(0, 0, 1, 0.915))
fig.savefig(os.path.join(OUT_DIR, 'drawdown_2018_2026.png'), facecolor=SURFACE)
plt.close(fig)

print("\nSaved -> results/backtest_2018_2026.csv, results/equity_2018_2026.csv,")
print("         results/equity_2018_2026.png, results/drawdown_2018_2026.png")
