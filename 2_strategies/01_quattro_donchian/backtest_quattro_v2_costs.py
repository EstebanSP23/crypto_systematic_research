"""
Quattro v2 - backtest.py + real trading costs
Same system as backtest.py (left untouched), same data pipeline (Binance spot
4H from 2022-01 + daily EMA200 from 2021-01), capped at May 2026. Adds:

  - Taker fee 0.06% per side on every fill: first entry, each pyramid unit, exit
  - Funding: at every settlement of the BTC/USDT:USDT perpetual (00/08/16 UTC,
    history in 1_data/btc_funding_binance.csv, Binance used as proxy for BloFin)
    with a position open, cost = rate x total size x bar open (spot proxy for
    mark price). Positive funding costs the long; negative funding pays it.
    Entry at the open of the settlement bar pays nothing; exit at that open pays.
  - Fees and funding hit the account balance when they happen; that running
    balance sizes the next pyramid units and the next trades. The 5% hard stop
    and R keep referencing the balance at original entry (price rules unchanged).

Usage:
  py backtest_quattro_v2_costs.py              # original vs v2 report -> results/quattro_v2_costs.csv
  py backtest_quattro_v2_costs.py --no-costs   # original engine only + trade-by-trade check vs
                                               # backtest_donchian_pyramid_results.csv (94 trades, $22,196)
"""
import os
import argparse
import ccxt
import pandas as pd
import numpy as np

parser = argparse.ArgumentParser(description='Quattro v2 with fees + funding')
parser.add_argument('--no-costs', action='store_true', help='reproduce the original backtest exactly')
NO_COSTS = parser.parse_args().no_costs

HERE         = os.path.dirname(os.path.abspath(__file__))
FUNDING_CSV  = os.path.join(HERE, '..', '..', '1_data', 'btc_funding_binance.csv')
ORIGINAL_CSV = os.path.join(HERE, 'backtest_donchian_pyramid_results.csv')
END_DATE     = pd.Timestamp('2026-06-01', tz='UTC')   # exclusive -> data through May 2026
SPLIT_DATE   = pd.Timestamp('2024-01-01', tz='UTC')   # P1 = 2022-2023, P2 = 2024-2026

# -- DATA ----------------------------------------------------------------------

def fetch_full(symbol, timeframe, since_ms, exchange):
    all_candles = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch:
            break
        all_candles.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000:
            break
    return all_candles

exchange = ccxt.binance()
since    = exchange.parse8601('2022-01-01T00:00:00Z')
since_d  = exchange.parse8601('2021-01-01T00:00:00Z')

print("Fetching 4H data...")
raw_4h = fetch_full('BTC/USDT', '4h', since, exchange)
df = pd.DataFrame(raw_4h, columns=['ts','open','high','low','close','volume'])
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts')
df = df[df.index < END_DATE]

print("Fetching daily data...")
raw_d = fetch_full('BTC/USDT', '1d', since_d, exchange)
df_d = pd.DataFrame(raw_d, columns=['ts','open','high','low','close','volume'])
df_d['dt'] = pd.to_datetime(df_d['ts'], unit='ms', utc=True)
df_d = df_d.set_index('dt').drop(columns='ts')
df_d = df_d[df_d.index < END_DATE]

print(f"  4H: {len(df)} candles  |  Daily: {len(df_d)} candles  |  "
      f"{df.index[0].date()} to {df.index[-1].date()}")

fund = pd.read_csv(FUNDING_CSV)
fund['bar'] = pd.to_datetime(fund['timestamp_ms'], unit='ms', utc=True).dt.floor('h')
df['funding_rate'] = fund.set_index('bar')['funding_rate'].reindex(df.index)
settle_bars = df.index.hour.isin([0, 8, 16])
print(f"  Funding: {df['funding_rate'].notna().sum()} settlements mapped to 4H bars  |  "
      f"00/08/16 bars without a rate: {int((settle_bars & df['funding_rate'].isna()).sum())}")

# -- INDICATORS ----------------------------------------------------------------

print("Calculating indicators...")

df['donch_high_20'] = df['high'].rolling(20).max().shift(1)
df['donch_low_10']  = df['low'].rolling(10).min().shift(1)

tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low']  - df['close'].shift(1)).abs(),
], axis=1).max(axis=1)
df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()

df_d['ema200']    = df_d['close'].ewm(span=200, adjust=False).mean()
df_d_avail        = df_d[['ema200']].copy()
df_d_avail.index  = df_d_avail.index + pd.Timedelta(days=1)
df_d_aligned      = df_d_avail.reindex(df.index, method='ffill')
df['d_ema200']    = df_d_aligned['ema200']
df['regime_up']   = df['close'] > df['d_ema200']

# -- BACKTEST ------------------------------------------------------------------

INITIAL_BALANCE = 1839.17
RISK_PCT        = 0.02
HARD_STOP_PCT   = 0.05
ATR_MULT_STOP   = 2.0
PYRAMID_STEP    = 0.5      # add new unit every 0.5*N of favorable move
MAX_UNITS       = 4
MAX_LEVERAGE    = 20
WARMUP          = 250
TAKER_FEE       = 0.0006   # per side, on notional

open_  = df['open'].values
high_  = df['high'].values
low_   = df['low'].values
close_ = df['close'].values
dhigh_ = df['donch_high_20'].values
dlow_  = df['donch_low_10'].values
atr_   = df['atr14'].values
reg_   = df['regime_up'].values
frate_ = df['funding_rate'].values
dates_ = df.index
n      = len(df)


def run_backtest(costs):
    fee_rate = TAKER_FEE if costs else 0.0
    account  = INITIAL_BALANCE
    trades   = []

    in_trade = False
    units = []                  # list of (entry_price, size, entry_bar)
    original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None
    pending_exit = False
    pending_exit_reason = None
    trade_fees = trade_funding = 0.0
    n_settlements = 0

    def total_size():
        return sum(u['size'] for u in units)

    def total_notional(price):
        return sum(u['size'] * price for u in units)

    def total_pnl_at(price):
        return sum((price - u['entry_price']) * u['size'] for u in units)

    def pay_fee(notional):
        nonlocal account, trade_fees
        fee = fee_rate * notional
        account    -= fee
        trade_fees += fee

    def close_all_units(exit_px, reason, i):
        nonlocal account, in_trade, units, original_entry, original_atr, common_stop, hard_stop, acct_at_entry
        nonlocal trade_fees, trade_funding, n_settlements
        gross = total_pnl_at(exit_px)
        pay_fee(total_size() * exit_px)
        account += gross
        risk_1u  = acct_at_entry * RISK_PCT
        net      = gross - trade_fees - trade_funding
        trades.append({
            'entry_date':        dates_[units[0]['entry_bar']],
            'exit_date':         dates_[i],
            'first_entry_price': units[0]['entry_price'],
            'avg_entry_price':   sum(u['entry_price'] * u['size'] for u in units) / total_size(),
            'exit_price':        exit_px,
            'num_units':         len(units),
            'total_size_btc':    total_size(),
            'original_atr':      original_atr,
            'acct_at_entry':     acct_at_entry,
            'pnl_gross_usd':     gross,
            'fees_usd':          trade_fees,
            'funding_usd':       trade_funding,
            'settlements':       n_settlements,
            'pnl_usd':           net,
            'R_gross':           gross / risk_1u,
            'R':                 net / risk_1u,
            'fees_R':            trade_fees / risk_1u,
            'funding_R':         trade_funding / risk_1u,
            'duration_h':        (i - units[0]['entry_bar']) * 4,
            'exit_reason':       reason,
            'account':           account,
        })
        in_trade = False
        units    = []
        original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None
        trade_fees = trade_funding = 0.0
        n_settlements = 0

    for i in range(WARMUP, n - 1):

        # Funding settles at this bar's open for a position held from before the bar
        if costs and in_trade and units[0]['entry_bar'] < i and not np.isnan(frate_[i]):
            cost = frate_[i] * total_size() * open_[i]
            account       -= cost
            trade_funding += cost
            n_settlements += 1

        # Execute any pending exit at this bar's open
        if pending_exit:
            close_all_units(open_[i], pending_exit_reason, i)
            pending_exit = False
            pending_exit_reason = None

        if in_trade:
            # 1) Hard 5% stop - total unrealized loss reaches 5% of account at entry (wick-based)
            worst_pnl = total_pnl_at(low_[i])
            if worst_pnl <= -HARD_STOP_PCT * acct_at_entry:
                target_loss = -HARD_STOP_PCT * acct_at_entry
                wavg_entry  = sum(u['entry_price'] * u['size'] for u in units) / total_size()
                exit_px     = wavg_entry + target_loss / total_size()
                close_all_units(exit_px, 'hard_stop_5pct', i)
                continue

            # 2) 2*ATR trailing stop - wick-based (low touches common_stop)
            if low_[i] <= common_stop:
                close_all_units(common_stop, 'atr_stop_trailing', i)
                continue

            # 3) Pyramiding - add new units if price reached next trigger (intrabar via bar high)
            while len(units) < MAX_UNITS:
                next_trigger = original_entry + PYRAMID_STEP * len(units) * original_atr
                if high_[i] < next_trigger:
                    break
                unit_entry = next_trigger
                stop_dist  = 2 * original_atr
                r_amt      = account * RISK_PCT          # running balance (== acct_at_entry without costs)
                size       = r_amt / stop_dist
                leverage   = (total_notional(close_[i]) + size * unit_entry) / account
                if leverage > MAX_LEVERAGE:
                    break

                units.append({'entry_price': unit_entry, 'size': size, 'entry_bar': i})
                pay_fee(size * unit_entry)

                # Trail common stop to (newest unit entry - 2N), but never DOWN
                new_stop = unit_entry - 2 * original_atr
                if new_stop > common_stop:
                    common_stop = new_stop

                target_loss   = -HARD_STOP_PCT * acct_at_entry
                wavg_entry    = sum(u['entry_price'] * u['size'] for u in units) / total_size()
                hard_stop     = wavg_entry + target_loss / total_size()

            # 4) Donchian trailing exit - close < 10-bar low
            if close_[i] < dlow_[i]:
                pending_exit        = True
                pending_exit_reason = 'donchian_exit'
                continue

        else:
            if np.isnan(dhigh_[i]) or np.isnan(atr_[i]) or np.isnan(reg_[i]):
                continue
            if close_[i] > dhigh_[i] and reg_[i]:
                entry_px  = open_[i+1]
                N         = atr_[i]                  # ATR at signal bar - fixed for whole trade
                stop_px   = entry_px - 2 * N
                if entry_px - stop_px <= 0:
                    continue

                r_amt    = account * RISK_PCT
                size     = r_amt / (2 * N)
                leverage = (size * entry_px) / account
                if leverage > MAX_LEVERAGE:
                    continue

                in_trade       = True
                original_entry = entry_px
                original_atr   = N
                acct_at_entry  = account             # balance that sized the trade (before its fee)
                common_stop    = stop_px
                units          = [{'entry_price': entry_px, 'size': size, 'entry_bar': i + 1}]
                hard_stop      = entry_px - (HARD_STOP_PCT * account / size)
                pay_fee(size * entry_px)

    if in_trade:
        close_all_units(close_[n-1], 'still_open_at_end', n-1)

    return pd.DataFrame(trades), account


# -- METRICS -------------------------------------------------------------------

def period_metrics(r, start_equity, t0, t1):
    final  = r['account'].iloc[-1] if len(r) else start_equity
    years  = (t1 - t0).total_seconds() / (365.25 * 86400)
    curve  = [start_equity] + list(r['account'])
    peak, max_dd = start_equity, 0.0
    for v in curve:
        peak   = max(peak, v)
        max_dd = min(max_dd, (v - peak) / peak * 100)
    apy  = ((final / start_equity) ** (1 / years) - 1) * 100
    wins = r[r['pnl_usd'] > 0]
    loss = r[r['pnl_usd'] <= 0]
    return {
        'start_equity':     start_equity,
        'final_equity':     final,
        'total_return_pct': (final / start_equity - 1) * 100,
        'apy_pct':          apy,
        'max_dd_pct':       max_dd,
        'calmar':           apy / abs(max_dd) if max_dd < 0 else np.nan,
        'trades':           len(r),
        'win_rate_pct':     len(wins) / len(r) * 100 if len(r) else np.nan,
        'avg_win_R':        wins['R'].mean(),
        'avg_loss_R':       loss['R'].mean(),
        'fees_usd':         r['fees_usd'].sum(),
        'funding_usd':      r['funding_usd'].sum(),
        'total_costs_usd':  r['fees_usd'].sum() + r['funding_usd'].sum(),
        'fees_R':           r['fees_R'].sum(),
        'funding_R':        r['funding_R'].sum(),
        'gross_pnl_usd':    r['pnl_gross_usd'].sum(),
    }


def split_metrics(r, label):
    t_start = dates_[WARMUP]
    t_end   = dates_[-1] + pd.Timedelta(hours=4)
    p1 = r[r['entry_date'] <  SPLIT_DATE]
    p2 = r[r['entry_date'] >= SPLIT_DATE]
    p2_start = p1['account'].iloc[-1] if len(p1) else INITIAL_BALANCE
    return [
        {'version': label, 'period': 'Full 2022-01..2026-05', **period_metrics(r,  INITIAL_BALANCE, t_start,    t_end)},
        {'version': label, 'period': 'P1 2022-2023',          **period_metrics(p1, INITIAL_BALANCE, t_start,    SPLIT_DATE)},
        {'version': label, 'period': 'P2 2024-2026',          **period_metrics(p2, p2_start,        SPLIT_DATE, t_end)},
    ]


def verify_against_original(r):
    """Trade-by-trade comparison with the committed output of the original script."""
    orig = pd.read_csv(ORIGINAL_CSV, parse_dates=['entry_date', 'exit_date'])
    checks = {
        'same trade count':      len(orig) == len(r),
        'same entry/exit dates': len(orig) == len(r) and (orig['entry_date'].values == r['entry_date'].values).all()
                                 and (orig['exit_date'].values == r['exit_date'].values).all(),
        'same exit reasons':     len(orig) == len(r) and (orig['exit_reason'].values == r['exit_reason'].values).all(),
    }
    if len(orig) == len(r):
        for col in ['exit_price', 'total_size_btc', 'pnl_usd', 'account']:
            checks[f'same {col} (rel 1e-9)'] = np.allclose(orig[col].values, r[col].values, rtol=1e-9, atol=0)
    print(f"\n  Check vs {os.path.basename(ORIGINAL_CSV)} ({len(orig)} trades, final ${orig['account'].iloc[-1]:,.2f}):")
    for k, ok in checks.items():
        print(f"    [{'OK' if ok else 'FAIL'}] {k}")
    return all(checks.values())


# -- RUN -----------------------------------------------------------------------

print("Running original engine (no costs)...")
r0, acct0 = run_backtest(costs=False)
print(f"  {len(r0)} trades, final ${acct0:,.2f}")
ok = verify_against_original(r0)

if NO_COSTS:
    raise SystemExit(0 if ok else 1)

print("\nRunning v2 (fees + funding)...")
r1, acct1 = run_backtest(costs=True)
print(f"  {len(r1)} trades, final ${acct1:,.2f}")

res = pd.DataFrame(split_metrics(r0, 'original_no_costs') + split_metrics(r1, 'v2_costs'))

# -- REPORT --------------------------------------------------------------------

LABELS = [
    ('total_return_pct', 'Total return %',      '{:+,.1f}'),
    ('apy_pct',          'APY %',               '{:+.1f}'),
    ('max_dd_pct',       'Max drawdown %',      '{:+.1f}'),
    ('calmar',           'Calmar (APY/|DD|)',   '{:.2f}'),
    ('trades',           'Trades',              '{:.0f}'),
    ('win_rate_pct',     'Win rate %',          '{:.1f}'),
    ('avg_win_R',        'Avg win (R, net)',    '{:+.2f}'),
    ('avg_loss_R',       'Avg loss (R, net)',   '{:+.2f}'),
    ('fees_usd',         'Fees $',              '{:,.0f}'),
    ('funding_usd',      'Funding $ (net)',     '{:,.0f}'),
    ('total_costs_usd',  'Total costs $',       '{:,.0f}'),
    ('fees_R',           'Fees (sum of R)',     '{:.1f}'),
    ('funding_R',        'Funding (sum of R)',  '{:.1f}'),
    ('start_equity',     'Start equity $',      '{:,.0f}'),
    ('final_equity',     'Final equity $',      '{:,.0f}'),
]

W = 12
cols = [(p, v) for p in res['period'].unique() for v in ['original_no_costs', 'v2_costs']]
print(f"\n{'=' * (24 + W * len(cols))}")
print(f"  ORIGINAL (no costs) vs V2 (taker 0.06%/side + Binance funding)   BTC/USDT 4H")
print('=' * (24 + W * len(cols)))
print(f"  {'':<22}" + ''.join(f"{p.split(' ')[0]:>{W}}" for p, _ in cols))
print(f"  {'':<22}" + ''.join(f"{('orig' if v.startswith('orig') else 'v2'):>{W}}" for _, v in cols))
print('-' * (24 + W * len(cols)))
for col, label, fmt in LABELS:
    cells = []
    for p, v in cols:
        val = res[(res['period'] == p) & (res['version'] == v)][col].iloc[0]
        cells.append('n/a' if pd.isna(val) else fmt.format(val))
    print(f"  {label:<22}" + ''.join(f"{c:>{W}}" for c in cells))

top = r1.nlargest(10, 'R_gross').copy()
top['duration_d']     = top['duration_h'] / 24
top['funding_pct_of_gross'] = top['funding_usd'] / top['pnl_gross_usd'] * 100
top_cols = ['entry_date', 'exit_date', 'num_units', 'duration_d', 'settlements', 'R_gross', 'R',
            'pnl_gross_usd', 'fees_usd', 'funding_usd', 'funding_R', 'funding_pct_of_gross']
print(f"\n  TOP 10 TRADES BY GROSS R (v2 run) - funding paid")
print('-' * 120)
print(f"  {'Entry':<11}{'Exit':<11}{'Units':>6}{'Days':>7}{'Settl.':>7}{'R gross':>9}{'R net':>8}"
      f"{'Gross $':>10}{'Fees $':>9}{'Funding $':>11}{'Fund. R':>9}{'Fund % gross':>14}")
for t in top.itertuples():
    print(f"  {t.entry_date.date()!s:<11}{t.exit_date.date()!s:<11}{t.num_units:>6}{t.duration_d:>7.1f}"
          f"{t.settlements:>7}{t.R_gross:>+9.2f}{t.R:>+8.2f}{t.pnl_gross_usd:>10,.0f}{t.fees_usd:>9,.0f}"
          f"{t.funding_usd:>11,.0f}{t.funding_R:>9.2f}{t.funding_pct_of_gross:>13.1f}%")

print("\nNotes: win = net pnl > 0. Max DD on closed-trade equity (as the original). APY from the first")
print("       tradeable bar (after warmup). Funding > 0 = paid by the long. No slippage modeled.")

out_dir = os.path.join(HERE, 'results')
os.makedirs(out_dir, exist_ok=True)
res.round(4).to_csv(os.path.join(out_dir, 'quattro_v2_costs.csv'), index=False)
top[top_cols].round(4).to_csv(os.path.join(out_dir, 'quattro_v2_top10_funding.csv'), index=False)
print(f"\nResults -> results/quattro_v2_costs.csv, results/quattro_v2_top10_funding.csv")
