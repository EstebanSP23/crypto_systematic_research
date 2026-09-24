"""
Quattro v2 engine - shared, parametrized copy of backtest_quattro_v2_costs.py (left untouched)
for the Round 2 experiments. Default parameters reproduce v2 exactly (verify_v2() checks it).

What is parametrized (defaults = v2):
  entry_len / exit_len  Donchian lookbacks (20 / 10)
  risk_pct / hard_stop  per-unit risk and hard stop, fractions of balance at entry (0.02 / 0.05)
  allow_entry(i)        -> bool       may the signal bar i open a new trade?
  allow_unit(s, i, k)   -> 'ok' | 'defer' | 'block'
                           before adding unit k (2..4) on bar i. 'defer' = not on this bar
                           (retried next bar, filled at max(trigger, open) so it never fills
                           below the market); 'block' = no more units for this trade (the
                           blocked units are tracked as hypothetical to measure funding saved).
Several Subsystem objects can share one Book (shared balance) for ensembles: costs are
charged per subsystem order, leverage cap applies to the combined notional.

Costs exactly as v2: taker 0.06% per side on every fill; funding at each Binance BTC/USDT:USDT
settlement (00/08/16 UTC) on the open notional at the bar open, debited from the balance when
it happens. Positions held before the settlement bar pay it; entries at that open do not.
"""
import os
import ccxt
import pandas as pd
import numpy as np

HERE         = os.path.dirname(os.path.abspath(__file__))
FUNDING_CSV  = os.path.join(HERE, '..', '..', '1_data', 'btc_funding_binance.csv')
ORIGINAL_CSV = os.path.join(HERE, 'backtest_donchian_pyramid_results.csv')
V2_CSV       = os.path.join(HERE, 'results', 'quattro_v2_costs.csv')
END_DATE     = pd.Timestamp('2026-06-01', tz='UTC')   # exclusive -> data through May 2026
SPLIT_DATE   = pd.Timestamp('2024-01-01', tz='UTC')   # P1 = 2022-2023, P2 = 2024-2026

INITIAL_BALANCE = 1839.17
RISK_PCT        = 0.02
HARD_STOP_PCT   = 0.05
PYRAMID_STEP    = 0.5
MAX_UNITS       = 4
MAX_LEVERAGE    = 20
WARMUP          = 250
TAKER_FEE       = 0.0006

PERIODS = ['Full 2022-01..2026-05', 'P1 2022-2023', 'P2 2024-2026']


# -- DATA ----------------------------------------------------------------------

def _fetch_full(symbol, timeframe, since_ms, exchange):
    out = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch:
            break
        out.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000:
            break
    return out


def load_data():
    """Same pipeline as backtest.py / v2: Binance spot 4H from 2022-01, daily from 2021-01, cut at May 2026."""
    ex = ccxt.binance()
    print("Fetching 4H + daily data (Binance)...")
    raw = _fetch_full('BTC/USDT', '4h', ex.parse8601('2022-01-01T00:00:00Z'), ex)
    df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
    df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.set_index('dt').drop(columns='ts')
    df = df[df.index < END_DATE]

    raw_d = _fetch_full('BTC/USDT', '1d', ex.parse8601('2021-01-01T00:00:00Z'), ex)
    df_d = pd.DataFrame(raw_d, columns=['ts','open','high','low','close','volume'])
    df_d['dt'] = pd.to_datetime(df_d['ts'], unit='ms', utc=True)
    df_d = df_d.set_index('dt').drop(columns='ts')
    df_d = df_d[df_d.index < END_DATE]

    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low']  - df['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()

    df_d['ema200']   = df_d['close'].ewm(span=200, adjust=False).mean()
    d_avail          = df_d[['ema200']].copy()
    d_avail.index    = d_avail.index + pd.Timedelta(days=1)
    df['d_ema200']   = d_avail.reindex(df.index, method='ffill')['ema200']
    df['regime_up']  = df['close'] > df['d_ema200']

    fund = pd.read_csv(FUNDING_CSV)
    fund['bar'] = pd.to_datetime(fund['timestamp_ms'], unit='ms', utc=True).dt.floor('h')
    df['funding_rate'] = fund.set_index('bar')['funding_rate'].reindex(df.index)

    print(f"  4H: {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()} | "
          f"funding settlements mapped: {df['funding_rate'].notna().sum()}")
    return Data(df, fund)


class Data:
    def __init__(self, df, fund):
        self.df     = df
        self.fund   = fund
        self.open   = df['open'].values
        self.high   = df['high'].values
        self.low    = df['low'].values
        self.close  = df['close'].values
        self.atr    = df['atr14'].values
        self.reg    = df['regime_up'].values
        self.frate  = df['funding_rate'].values
        self.dates  = df.index
        self.close_time = df.index + pd.Timedelta(hours=4)
        self.n      = len(df)
        self._dh, self._dl = {}, {}

    def dhigh(self, k):
        if k not in self._dh:
            self._dh[k] = self.df['high'].rolling(k).max().shift(1).values
        return self._dh[k]

    def dlow(self, k):
        if k not in self._dl:
            self._dl[k] = self.df['low'].rolling(k).min().shift(1).values
        return self._dl[k]


# -- ENGINE --------------------------------------------------------------------

class Book:
    """Shared account balance for one or more subsystems."""
    def __init__(self, balance=INITIAL_BALANCE):
        self.balance = balance
        self.subs    = []

    def notional(self, price, exclude=None):
        return sum(s.notional(price) for s in self.subs if s is not exclude)


class Subsystem:
    def __init__(self, book, data, name='v2', entry_len=20, exit_len=10,
                 risk_pct=RISK_PCT, hard_stop_pct=HARD_STOP_PCT, costs=True,
                 allow_entry=None, allow_unit=None):
        self.book, self.d, self.name = book, data, name
        self.dh, self.dl = data.dhigh(entry_len), data.dlow(exit_len)
        self.risk_pct, self.hard_stop_pct = risk_pct, hard_stop_pct
        self.fee_rate    = TAKER_FEE if costs else 0.0
        self.costs       = costs
        self.allow_entry = allow_entry
        self.allow_unit  = allow_unit
        self.trades      = []
        self.events      = []          # allow_unit activations: {'bar', 'unit', 'action'}
        book.subs.append(self)
        self._reset()

    def _reset(self):
        self.in_trade = False
        self.units = []
        self.hyp_units = []            # blocked units whose trigger was reached (not traded)
        self.original_entry = self.original_atr = self.common_stop = self.acct_at_entry = None
        self.pending_exit = False
        self.pending_exit_reason = None
        self.pending_defer = False
        self.blocked = False
        self.trade_fees = self.trade_funding = self.hyp_funding = 0.0
        self.n_settlements = 0

    # helpers (same arithmetic as v2)
    def total_size(self):        return sum(u['size'] for u in self.units)
    def notional(self, price):   return sum(u['size'] * price for u in self.units)
    def pnl_at(self, price):     return sum((price - u['entry_price']) * u['size'] for u in self.units)
    def wavg(self):              return sum(u['entry_price'] * u['size'] for u in self.units) / self.total_size()

    def _pay_fee(self, notional):
        fee = self.fee_rate * notional
        self.book.balance -= fee
        self.trade_fees   += fee

    def _close(self, exit_px, reason, i):
        d = self.d
        gross = self.pnl_at(exit_px)
        self._pay_fee(self.total_size() * exit_px)
        self.book.balance += gross
        risk_1u = self.acct_at_entry * self.risk_pct
        net     = gross - self.trade_fees - self.trade_funding
        self.trades.append({
            'system':            self.name,
            'entry_date':        d.dates[self.units[0]['entry_bar']],
            'exit_date':         d.dates[i],
            'first_entry_price': self.units[0]['entry_price'],
            'avg_entry_price':   self.wavg(),
            'exit_price':        exit_px,
            'num_units':         len(self.units),
            'total_size_btc':    self.total_size(),
            'original_atr':      self.original_atr,
            'acct_at_entry':     self.acct_at_entry,
            'pnl_gross_usd':     gross,
            'fees_usd':          self.trade_fees,
            'funding_usd':       self.trade_funding,
            'hyp_funding_saved': self.hyp_funding,
            'blocked_units':     len(self.hyp_units),
            'settlements':       self.n_settlements,
            'pnl_usd':           net,
            'R_gross':           gross / risk_1u,
            'R':                 net / risk_1u,
            'fees_R':            self.trade_fees / risk_1u,
            'funding_R':         self.trade_funding / risk_1u,
            'duration_h':        (i - self.units[0]['entry_bar']) * 4,
            'exit_reason':       reason,
            'account':           self.book.balance,
        })
        self._reset()

    def step(self, i):
        d, book = self.d, self.book

        # Funding settles at this bar's open for a position held from before the bar
        if self.costs and self.in_trade and self.units[0]['entry_bar'] < i and not np.isnan(d.frate[i]):
            cost = d.frate[i] * self.total_size() * d.open[i]
            book.balance       -= cost
            self.trade_funding += cost
            self.n_settlements += 1
            if self.hyp_units:
                self.hyp_funding += d.frate[i] * sum(u['size'] for u in self.hyp_units) * d.open[i]

        # Pending exit at this bar's open
        if self.pending_exit:
            self._close(d.open[i], self.pending_exit_reason, i)

        if self.in_trade:
            # 1) Hard stop - total unrealized loss reaches hard_stop_pct of balance at entry (wick-based)
            if self.pnl_at(d.low[i]) <= -self.hard_stop_pct * self.acct_at_entry:
                target_loss = -self.hard_stop_pct * self.acct_at_entry
                self._close(self.wavg() + target_loss / self.total_size(), 'hard_stop_5pct', i)
                return

            # 2) Trailing stop - wick-based
            if d.low[i] <= self.common_stop:
                self._close(self.common_stop, 'atr_stop_trailing', i)
                return

            # 3) Pyramiding (intrabar via bar high)
            N = self.original_atr
            added = False
            while len(self.units) + len(self.hyp_units) < MAX_UNITS:
                k = len(self.units) + len(self.hyp_units) + 1
                trigger = self.original_entry + PYRAMID_STEP * (k - 1) * N
                if d.high[i] < trigger:
                    break
                size = (book.balance * self.risk_pct) / (2 * N)
                if self.blocked:                                  # already blocked: track hypothetical only
                    self.hyp_units.append({'size': size, 'bar': i})
                    continue
                if self.allow_unit is not None:
                    action = self.allow_unit(self, i, k)
                    if action != 'ok':
                        self.events.append({'bar': i, 'date': d.dates[i], 'unit': k, 'action': action})
                    if action == 'defer':
                        self.pending_defer = True
                        break
                    if action == 'block':
                        self.blocked = True
                        self.hyp_units.append({'size': size, 'bar': i})
                        continue
                unit_entry = max(trigger, d.open[i]) if self.pending_defer else trigger
                leverage = (book.notional(d.close[i]) + size * unit_entry) / book.balance
                if leverage > MAX_LEVERAGE:
                    break
                self.units.append({'entry_price': unit_entry, 'size': size, 'entry_bar': i})
                self._pay_fee(size * unit_entry)
                added = True
                new_stop = unit_entry - 2 * N
                if new_stop > self.common_stop:
                    self.common_stop = new_stop
            if added:
                self.pending_defer = False

            # 4) Donchian exit - close < exit_len-bar low
            if d.close[i] < self.dl[i]:
                self.pending_exit        = True
                self.pending_exit_reason = 'donchian_exit'
            return

        # Entry
        if np.isnan(self.dh[i]) or np.isnan(d.atr[i]) or np.isnan(d.reg[i]):
            return
        if d.close[i] > self.dh[i] and d.reg[i]:
            if self.allow_entry is not None and not self.allow_entry(i):
                return
            entry_px = d.open[i+1]
            N        = d.atr[i]
            stop_px  = entry_px - 2 * N
            if entry_px - stop_px <= 0:
                return
            size     = (book.balance * self.risk_pct) / (2 * N)
            leverage = (size * entry_px + book.notional(d.close[i], exclude=self)) / book.balance
            if leverage > MAX_LEVERAGE:
                return
            self.in_trade       = True
            self.original_entry = entry_px
            self.original_atr   = N
            self.acct_at_entry  = book.balance
            self.common_stop    = stop_px
            self.units          = [{'entry_price': entry_px, 'size': size, 'entry_bar': i + 1}]
            self._pay_fee(size * entry_px)

    def finish(self, i):
        if self.in_trade:
            self._close(self.d.close[i], 'still_open_at_end', i)


def run(data, subsystems):
    """subsystems: list of kwargs dicts for Subsystem. Returns (trades df sorted by exit, book)."""
    book = Book()
    subs = [Subsystem(book, data, **kw) for kw in subsystems]
    for i in range(WARMUP, data.n - 1):
        for s in subs:
            s.step(i)
    for s in subs:
        s.finish(data.n - 1)
    trades = pd.concat([pd.DataFrame(s.trades) for s in subs], ignore_index=True)
    if len(trades):
        trades = trades.sort_values(['exit_date', 'entry_date'], kind='stable').reset_index(drop=True)
    return trades, book, subs


def run_single(data, **kw):
    trades, book, subs = run(data, [kw])
    return trades, book, subs[0]


# -- METRICS (same definitions as v2) ------------------------------------------

def period_metrics(r, start_equity, t0, t1):
    final  = r['account'].iloc[-1] if len(r) else start_equity
    years  = (t1 - t0).total_seconds() / (365.25 * 86400)
    peak, max_dd = start_equity, 0.0
    for v in [start_equity] + list(r['account']):
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


def split_metrics(r, data, label):
    """Walk-forward exactly as v2: split by entry date; P2 starts from the equity after the last P1 trade."""
    t_start = data.dates[WARMUP]
    t_end   = data.dates[-1] + pd.Timedelta(hours=4)
    p1 = r[r['entry_date'] <  SPLIT_DATE]
    p2 = r[r['entry_date'] >= SPLIT_DATE]
    p2_start = p1['account'].iloc[-1] if len(p1) else INITIAL_BALANCE
    return [
        {'version': label, 'period': PERIODS[0], **period_metrics(r,  INITIAL_BALANCE, t_start,    t_end)},
        {'version': label, 'period': PERIODS[1], **period_metrics(p1, INITIAL_BALANCE, t_start,    SPLIT_DATE)},
        {'version': label, 'period': PERIODS[2], **period_metrics(p2, p2_start,        SPLIT_DATE, t_end)},
    ]


def verify_v2(data):
    """Guard: engine defaults must reproduce the original (no costs, trade by trade) and v2 (summary CSV)."""
    ok = True
    r0, _, _ = run_single(data, costs=False)
    orig = pd.read_csv(ORIGINAL_CSV, parse_dates=['entry_date', 'exit_date'])
    same0 = (len(r0) == len(orig)
             and (orig['entry_date'].values == r0['entry_date'].values).all()
             and np.allclose(orig['account'].values, r0['account'].values, rtol=1e-9, atol=0)
             and np.allclose(orig['total_size_btc'].values, r0['total_size_btc'].values, rtol=1e-9, atol=0))
    ok &= same0
    r1, _, _ = run_single(data)
    ref = pd.read_csv(V2_CSV)
    ref = ref[ref['version'] == 'v2_costs'].set_index('period')
    mine = pd.DataFrame(split_metrics(r1, data, 'v2')).set_index('period')
    cols = ['final_equity', 'trades', 'max_dd_pct', 'calmar', 'fees_usd', 'funding_usd']
    same1 = np.allclose(ref.loc[PERIODS, cols].values.astype(float),
                        mine.loc[PERIODS, cols].values.astype(float), rtol=0, atol=1e-3)
    ok &= same1
    print(f"  Engine check: original no-costs trade-by-trade [{'OK' if same0 else 'FAIL'}] | "
          f"v2 summary vs results/quattro_v2_costs.csv [{'OK' if same1 else 'FAIL'}]")
    if not ok:
        raise SystemExit("Engine does not reproduce v2 - aborting.")
    return r1


# -- REPORTING -----------------------------------------------------------------

LABELS = [
    ('total_return_pct', 'Total return %',     '{:+,.1f}'),
    ('apy_pct',          'APY %',              '{:+.1f}'),
    ('max_dd_pct',       'Max drawdown %',     '{:+.1f}'),
    ('calmar',           'Calmar (APY/|DD|)',  '{:.2f}'),
    ('trades',           'Trades',             '{:.0f}'),
    ('win_rate_pct',     'Win rate %',         '{:.1f}'),
    ('avg_win_R',        'Avg win (R, net)',   '{:+.2f}'),
    ('avg_loss_R',       'Avg loss (R, net)',  '{:+.2f}'),
    ('total_costs_usd',  'Total costs $',      '{:,.0f}'),
    ('fees_usd',         '  fees $',           '{:,.0f}'),
    ('funding_usd',      '  funding $',        '{:,.0f}'),
    ('final_equity',     'Final equity $',     '{:,.0f}'),
]


def print_comparison(res, versions, title, W=13):
    for period in PERIODS:
        sub = res[res['period'] == period].set_index('version')
        print(f"\n{'=' * (24 + W * len(versions))}\n  {title} - {period}\n{'=' * (24 + W * len(versions))}")
        print(f"  {'':<22}" + ''.join(f"{v[:W-1]:>{W}}" for v in versions))
        print('-' * (24 + W * len(versions)))
        for col, label, fmt in LABELS:
            cells = ['n/a' if pd.isna(sub.loc[v, col]) else fmt.format(sub.loc[v, col]) for v in versions]
            print(f"  {label:<22}" + ''.join(f"{c:>{W}}" for c in cells))


def acceptance(res, variant, explanation, base='v2'):
    """(a) Calmar > v2 in P1 AND P2, (b) >= 70% of v2 trades (full period), (c) economic explanation."""
    g = lambda v, p, c: res[(res['version'] == v) & (res['period'] == p)][c].iloc[0]
    a1 = g(variant, PERIODS[1], 'calmar') > g(base, PERIODS[1], 'calmar')
    a2 = g(variant, PERIODS[2], 'calmar') > g(base, PERIODS[2], 'calmar')
    trade_ratio = g(variant, PERIODS[0], 'trades') / g(base, PERIODS[0], 'trades')
    b = trade_ratio >= 0.70
    c = bool(explanation)
    return {
        'variant': variant,
        'calmar_P1': g(variant, PERIODS[1], 'calmar'), 'calmar_P1_v2': g(base, PERIODS[1], 'calmar'),
        'calmar_P2': g(variant, PERIODS[2], 'calmar'), 'calmar_P2_v2': g(base, PERIODS[2], 'calmar'),
        'a_calmar_P1_and_P2': a1 and a2,
        'trade_ratio_vs_v2': trade_ratio, 'b_trades_ge_70pct': b,
        'c_explanation': explanation, 'c_ok': c,
        'verdict': 'ACCEPTED' if (a1 and a2 and b and c) else 'REJECTED',
    }


def print_acceptance(rows):
    print(f"\n  ACCEPTANCE (fixed in advance): (a) Calmar > v2 in P1 and P2, (b) >= 70% of v2 trades, (c) economic rationale")
    for r in rows:
        print(f"\n  {r['variant']}: {r['verdict']}")
        print(f"    (a) Calmar P1 {r['calmar_P1']:.2f} vs {r['calmar_P1_v2']:.2f} | "
              f"P2 {r['calmar_P2']:.2f} vs {r['calmar_P2_v2']:.2f}  -> {'PASS' if r['a_calmar_P1_and_P2'] else 'FAIL'}")
        print(f"    (b) trades {r['trade_ratio_vs_v2']*100:.0f}% of v2  -> {'PASS' if r['b_trades_ge_70pct'] else 'FAIL'}")
        print(f"    (c) {r['c_explanation'] or '(none)'}  -> {'PASS' if r['c_ok'] else 'FAIL'}")
