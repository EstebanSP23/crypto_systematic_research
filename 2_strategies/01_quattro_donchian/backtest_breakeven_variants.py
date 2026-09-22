"""
Quattro - Break-even variants
Based on backtest_donchian_pyramid.py (left untouched). Same data, same period
(2022-01 to 2026-05), same rules; only the stop / exit tweak below changes:

  A) Baseline  - current system, no changes
  B) BE@U4     - when Unit 4 fills: common_stop = max(common_stop, weighted avg entry)
  C) BE@+1N    - when close > weighted avg entry + 1N (N = ATR at original entry):
                 common_stop = max(common_stop, weighted avg entry)
  D) BE@+1N+D5 - same as C, and once Unit 4 is in, the Donchian exit uses the
                 5-bar low instead of the 10-bar low

Metrics per variant (full period + walk-forward P1 2022-2023 / P2 2024-2026):
total return, APY, max DD (closed-trade equity, as in the original), trades,
win rate, avg win / avg loss in R, and "given back": trades whose floating
profit exceeded +1N (bar high vs weighted avg entry) and still closed negative.
Walk-forward splits the single full run by trade entry date; each period's
return / DD is measured from the equity it started with.

Usage:
  py backtest_breakeven_variants.py                    # original engine -> results/breakeven_variants.csv
  py backtest_breakeven_variants.py --realistic-fills  # sensitivity     -> results/breakeven_variants_realistic_fills.csv

--realistic-fills changes only how stops are filled (all 4 variants alike):
the HIGHER of common_stop / hard-stop level is hit first as price falls, and
the fill is min(bar open, stop). The original engine checks the hard stop
first and always fills at the stop level.
"""
import os
import argparse
import ccxt
import pandas as pd
import numpy as np

parser = argparse.ArgumentParser(description='Quattro break-even variants')
parser.add_argument('--realistic-fills', action='store_true',
                    help='higher stop hit first; fill at min(open, stop)')
REALISTIC_FILLS = parser.parse_args().realistic_fills

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

END_DATE   = pd.Timestamp('2026-06-01', tz='UTC')   # exclusive -> data through May 2026
SPLIT_DATE = pd.Timestamp('2024-01-01', tz='UTC')   # P1 = 2022-2023, P2 = 2024-2026

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

# -- INDICATORS ----------------------------------------------------------------

print("Calculating indicators...")

df['donch_high_20'] = df['high'].rolling(20).max().shift(1)
df['donch_low_10']  = df['low'].rolling(10).min().shift(1)
df['donch_low_5']   = df['low'].rolling(5).min().shift(1)     # variant D only

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
PNL_EPS         = 1e-6     # |pnl| below this (USD) = exact break-even exit

open_  = df['open'].values
high_  = df['high'].values
low_   = df['low'].values
close_ = df['close'].values
dhigh_ = df['donch_high_20'].values
dlow_  = df['donch_low_10'].values
dlow5_ = df['donch_low_5'].values
atr_   = df['atr14'].values
reg_   = df['regime_up'].values
dates_ = df.index
n      = len(df)

VARIANTS = {
    'A_baseline': dict(be_on_unit4=False, be_on_profit=False, short_exit_after_u4=False),
    'B_be_unit4': dict(be_on_unit4=True,  be_on_profit=False, short_exit_after_u4=False),
    'C_be_1N':    dict(be_on_unit4=False, be_on_profit=True,  short_exit_after_u4=False),
    'D_be_1N_d5': dict(be_on_unit4=False, be_on_profit=True,  short_exit_after_u4=True),
}


def run_backtest(be_on_unit4, be_on_profit, short_exit_after_u4):
    account = INITIAL_BALANCE
    trades  = []

    in_trade = False
    units = []
    original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None
    pending_exit = False
    pending_exit_reason = None
    mfe_high_N = mfe_close_N = None     # max floating profit vs wavg entry, in N

    def total_size():
        return sum(u['size'] for u in units)

    def total_notional(price):
        return sum(u['size'] * price for u in units)

    def total_pnl_at(price):
        return sum((price - u['entry_price']) * u['size'] for u in units)

    def wavg_entry():
        return sum(u['entry_price'] * u['size'] for u in units) / total_size()

    def close_all_units(exit_px, reason, i):
        nonlocal account, in_trade, units, original_entry, original_atr, common_stop, hard_stop, acct_at_entry
        total_pnl = total_pnl_at(exit_px)
        account  += total_pnl
        trades.append({
            'entry_date':        dates_[units[0]['entry_bar']],
            'exit_date':         dates_[i],
            'first_entry_price': units[0]['entry_price'],
            'avg_entry_price':   wavg_entry(),
            'exit_price':        exit_px,
            'num_units':         len(units),
            'original_atr':      original_atr,
            'pnl_usd':           total_pnl,
            'R':                 total_pnl / (acct_at_entry * RISK_PCT),
            'mfe_high_N':        mfe_high_N,
            'mfe_close_N':       mfe_close_N,
            'exit_reason':       reason,
            'account':           account,
        })
        in_trade = False
        units    = []
        original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None

    for i in range(WARMUP, n - 1):

        # Execute any pending exit at this bar's open
        if pending_exit:
            close_all_units(open_[i], pending_exit_reason, i)
            pending_exit = False
            pending_exit_reason = None

        if in_trade:
            if REALISTIC_FILLS:
                # 1+2) Whichever stop is higher is hit first; gap below it fills at the open
                hs_px = wavg_entry() + (-HARD_STOP_PCT * acct_at_entry) / total_size()
                top   = max(common_stop, hs_px)
                if low_[i] <= top:
                    reason = 'atr_stop_trailing' if common_stop > hs_px else 'hard_stop_5pct'
                    close_all_units(min(open_[i], top), reason, i)
                    continue
            else:
                # 1) Hard 5% stop - total unrealized loss reaches 5% of account at entry (wick-based)
                worst_pnl = total_pnl_at(low_[i])
                if worst_pnl <= -HARD_STOP_PCT * acct_at_entry:
                    target_loss = -HARD_STOP_PCT * acct_at_entry
                    exit_px     = wavg_entry() + target_loss / total_size()
                    close_all_units(exit_px, 'hard_stop_5pct', i)
                    continue

                # 2) Common trailing stop - wick-based (low touches common_stop)
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
                r_amt      = acct_at_entry * RISK_PCT
                size       = r_amt / stop_dist
                leverage   = (total_notional(close_[i]) + size * unit_entry) / account
                if leverage > MAX_LEVERAGE:
                    break

                units.append({'entry_price': unit_entry, 'size': size, 'entry_bar': i})

                # Trail common stop to (newest unit entry - 2N), but never DOWN
                new_stop = unit_entry - 2 * original_atr
                if new_stop > common_stop:
                    common_stop = new_stop

                target_loss = -HARD_STOP_PCT * acct_at_entry
                hard_stop   = wavg_entry() + target_loss / total_size()

                # [B] Break-even as soon as Unit 4 fills
                if be_on_unit4 and len(units) == MAX_UNITS:
                    common_stop = max(common_stop, wavg_entry())

            # Floating-profit tracking (bar survived the stops, so its high/close count)
            wavg = wavg_entry()
            mfe_high_N  = max(mfe_high_N,  (high_[i]  - wavg) / original_atr)
            mfe_close_N = max(mfe_close_N, (close_[i] - wavg) / original_atr)

            # [C/D] Break-even once close > weighted avg entry + 1N
            if be_on_profit and close_[i] > wavg + original_atr:
                common_stop = max(common_stop, wavg)

            # 4) Donchian trailing exit - close < 10-bar low ([D] 5-bar low once Unit 4 is in)
            exit_low = dlow5_[i] if (short_exit_after_u4 and len(units) == MAX_UNITS) else dlow_[i]
            if close_[i] < exit_low:
                pending_exit        = True
                pending_exit_reason = 'donchian_exit'
                continue

        else:
            if np.isnan(dhigh_[i]) or np.isnan(atr_[i]) or np.isnan(reg_[i]):
                continue
            if close_[i] > dhigh_[i] and reg_[i]:
                entry_px = open_[i+1]
                N        = atr_[i]                  # ATR at signal bar - fixed for whole trade
                stop_px  = entry_px - 2 * N
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
                acct_at_entry  = account
                common_stop    = stop_px
                units          = [{'entry_price': entry_px, 'size': size, 'entry_bar': i + 1}]
                hard_stop      = entry_px - (HARD_STOP_PCT * account / size)
                mfe_high_N = mfe_close_N = -np.inf

    if in_trade:
        close_all_units(close_[n-1], 'still_open_at_end', n-1)

    return pd.DataFrame(trades)


# -- METRICS -------------------------------------------------------------------

def period_metrics(r, start_equity, t0, t1):
    final  = r['account'].iloc[-1] if len(r) else start_equity
    years  = (t1 - t0).total_seconds() / (365.25 * 86400)
    curve  = [start_equity] + list(r['account'])
    peak, max_dd = start_equity, 0.0
    for v in curve:
        peak   = max(peak, v)
        max_dd = min(max_dd, (v - peak) / peak * 100)

    wins   = r[r['pnl_usd'] >  PNL_EPS]
    losses = r[r['pnl_usd'] < -PNL_EPS]
    be     = r[r['pnl_usd'].abs() <= PNL_EPS]
    return {
        'start_equity':     start_equity,
        'final_equity':     final,
        'total_return_pct': (final / start_equity - 1) * 100,
        'apy_pct':          ((final / start_equity) ** (1 / years) - 1) * 100,
        'max_dd_pct':       max_dd,
        'trades':           len(r),
        'win_rate_pct':     len(wins) / len(r) * 100 if len(r) else np.nan,
        'avg_win_R':        wins['R'].mean(),
        'avg_loss_R':       losses['R'].mean(),
        'breakeven_trades': len(be),
        'reached_1N':       int((r['mfe_high_N'] > 1).sum()),
        'given_back':       int(((r['mfe_high_N'] > 1) & (r['pnl_usd'] < -PNL_EPS)).sum()),
        'given_back_close': int(((r['mfe_close_N'] > 1) & (r['pnl_usd'] < -PNL_EPS)).sum()),
    }


t_start = dates_[WARMUP]
t_end   = dates_[-1] + pd.Timedelta(hours=4)

rows      = []
trade_logs = {}
for name, cfg in VARIANTS.items():
    print(f"Running {name}...")
    r = run_backtest(**cfg)
    trade_logs[name] = r
    p1 = r[r['entry_date'] <  SPLIT_DATE]
    p2 = r[r['entry_date'] >= SPLIT_DATE]
    p2_start = p1['account'].iloc[-1] if len(p1) else INITIAL_BALANCE
    for period, sub, eq0, t0, t1 in [
        ('Full 2022-01..2026-05', r,  INITIAL_BALANCE, t_start,    t_end),
        ('P1 2022-2023',          p1, INITIAL_BALANCE, t_start,    SPLIT_DATE),
        ('P2 2024-2026',          p2, p2_start,        SPLIT_DATE, t_end),
    ]:
        rows.append({'variant': name, 'period': period, **period_metrics(sub, eq0, t0, t1)})

res = pd.DataFrame(rows)

# -- REPORT --------------------------------------------------------------------

LABELS = [
    ('total_return_pct', 'Total return %',          '{:+,.1f}'),
    ('apy_pct',          'APY %',                   '{:+.1f}'),
    ('max_dd_pct',       'Max drawdown %',          '{:+.1f}'),
    ('trades',           'Trades',                  '{:d}'),
    ('win_rate_pct',     'Win rate %',              '{:.1f}'),
    ('avg_win_R',        'Avg win (R)',             '{:+.2f}'),
    ('avg_loss_R',       'Avg loss (R)',            '{:+.2f}'),
    ('breakeven_trades', 'Break-even exits (0R)',   '{:d}'),
    ('reached_1N',       'Reached > +1N floating',  '{:d}'),
    ('given_back',       'Given back (>+1N, <0)',   '{:d}'),
    ('given_back_close', '  ...on close basis',     '{:d}'),
    ('start_equity',     'Start equity $',          '{:,.0f}'),
    ('final_equity',     'Final equity $',          '{:,.0f}'),
]

names = list(VARIANTS)
W = 14
for period in res['period'].unique():
    sub = res[res['period'] == period].set_index('variant')
    print(f"\n{'=' * (28 + W * len(names))}")
    print(f"  {period}   (BTC/USDT 4H, {'REALISTIC fills' if REALISTIC_FILLS else 'original engine fills'})")
    print('=' * (28 + W * len(names)))
    print(f"  {'':<26}" + ''.join(f"{v:>{W}}" for v in names))
    print('-' * (28 + W * len(names)))
    for col, label, fmt in LABELS:
        cells = []
        for v in names:
            val = sub.loc[v, col]
            cells.append('n/a' if pd.isna(val) else fmt.format(int(val) if 'd}' in fmt else val))
        print(f"  {label:<26}" + ''.join(f"{c:>{W}}" for c in cells))

print("\nNotes: win = pnl > 0; avg loss excludes exact 0R break-even exits (counted separately).")
print("       'Given back' = max(bar high - wavg entry) exceeded 1N and the trade closed < 0.")
print("       Max DD on closed-trade equity (same method as the original). No fees/slippage.")

out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
os.makedirs(out_dir, exist_ok=True)
out_csv = os.path.join(out_dir, 'breakeven_variants_realistic_fills.csv' if REALISTIC_FILLS
                                else 'breakeven_variants.csv')
res.round(4).to_csv(out_csv, index=False)
print(f"\nResults -> {out_csv}")
