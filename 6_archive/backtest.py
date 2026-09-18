import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# ── 1. DATA ─────────────────────────────────────────────────────────────────

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

print("Fetching BTC/USDT 1H from Binance (Jan 2022 to now)...")
exchange = ccxt.binance()
since = exchange.parse8601('2022-01-01T00:00:00Z')
raw = fetch_full('BTC/USDT', '1h', since, exchange)
df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts')
print(f"  {len(df)} candles  |  {df.index[0].date()} → {df.index[-1].date()}")

# ── 2. INDICATORS ────────────────────────────────────────────────────────────

print("Calculating indicators...")

# Trend filter
df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
df['ema55'] = df['close'].ewm(span=55, adjust=False).mean()

# PMARP  (validated: EMA 13, lookback 300)
df['ema13']  = df['close'].ewm(span=13, adjust=False).mean()
df['pmar']   = (df['close'] / df['ema13']).abs()
pmar = df['pmar'].values
pmarp = np.full(len(df), np.nan)
for i in range(300, len(df)):
    h = pmar[i-300:i]
    pmarp[i] = np.sum(h <= pmar[i]) / 300 * 100
df['pmarp'] = pmarp

# BBWP  (validated: SMA 13, lookback 252, MA SMA 5)
df['basis'] = df['close'].rolling(13).mean()
df['bbw']   = 2 * df['close'].rolling(13).std(ddof=0) / df['basis']
bbw = df['bbw'].values
bbwp = np.full(len(df), np.nan)
for i in range(13, len(df)):
    start = max(13, i - 252)
    h = bbw[start:i]
    valid = h[~np.isnan(h)]
    if len(valid) > 0:
        bbwp[i] = np.sum(valid <= bbw[i]) / len(valid) * 100
df['bbwp']    = bbwp
df['bbwp_ma'] = df['bbwp'].rolling(5).mean()

# LuxAlgo support  (pivotlow 15/15, fixnan, shifted [1])
print("  Detecting pivot lows (15/15)...")
lows = df['low'].values
n = len(df)
pivot_raw = np.full(n, np.nan)
for i in range(15, n - 15):
    li = lows[i]
    if (li < lows[i-15:i]).all() and (li < lows[i+1:i+16]).all():
        pivot_raw[i + 15] = li          # confirmed 15 bars later

support_series = pd.Series(pivot_raw, index=df.index).ffill().shift(1)
df['support'] = support_series

# ── 3. BACKTEST ──────────────────────────────────────────────────────────────

print("Running backtest...")

INITIAL_BALANCE = 1839.17
RISK_PCT        = 0.02          # 2% per trade
HARD_STOP_PCT   = 0.05          # 5% emergency hard stop
MAX_LEVERAGE    = 20
WARMUP          = 400

open_  = df['open'].values
high_  = df['high'].values
low_   = df['low'].values
close_ = df['close'].values
ema21_ = df['ema21'].values
ema55_ = df['ema55'].values
pmarp_ = df['pmarp'].values
bbwp_  = df['bbwp'].values
bbwpm_ = df['bbwp_ma'].values
supp_  = df['support'].values
dates_ = df.index

account       = INITIAL_BALANCE
trades        = []

in_trade      = False
entry_price   = None
entry_support = None
pos_size      = None
risk_amt      = None
entry_bar     = None
hard_stop     = None
acct_at_entry = None

pending_exit        = False
pending_exit_reason = None

for i in range(WARMUP, n - 1):

    # ── Execute pending exit at this bar's open ──
    if pending_exit:
        exit_px = open_[i]
        pnl     = (exit_px - entry_price) * pos_size
        account += pnl
        trades.append({
            'entry_date':    dates_[entry_bar],
            'exit_date':     dates_[i],
            'entry_price':   entry_price,
            'exit_price':    exit_px,
            'support':       entry_support,
            'stop_distance': entry_price - entry_support,
            'pos_size_btc':  pos_size,
            'risk_amt':      risk_amt,
            'pnl_usd':       pnl,
            'pnl_pct':       pnl / acct_at_entry * 100,
            'duration_h':    i - entry_bar,
            'exit_reason':   pending_exit_reason,
            'account':       account,
        })
        in_trade      = False
        pending_exit  = False
        pending_exit_reason = None

    # ── Manage open trade ──
    if in_trade:
        # Hard stop — triggered intrabar by the candle low
        if low_[i] <= hard_stop:
            exit_px  = hard_stop
            pnl      = (exit_px - entry_price) * pos_size
            account += pnl
            trades.append({
                'entry_date':    dates_[entry_bar],
                'exit_date':     dates_[i],
                'entry_price':   entry_price,
                'exit_price':    exit_px,
                'support':       entry_support,
                'stop_distance': entry_price - entry_support,
                'pos_size_btc':  pos_size,
                'risk_amt':      risk_amt,
                'pnl_usd':       pnl,
                'pnl_pct':       pnl / acct_at_entry * 100,
                'duration_h':    i - entry_bar,
                'exit_reason':   'hard_stop_5pct',
                'account':       account,
            })
            in_trade = False
            continue

        # Soft stop — close below support level
        if close_[i] < supp_[i]:
            pending_exit        = True
            pending_exit_reason = 'stop_loss'
            continue

        # Take profit — PMARP closes above 77
        if pmarp_[i] > 77:
            pending_exit        = True
            pending_exit_reason = 'take_profit'
            continue

    # ── Check entry conditions at this bar's close ──
    else:
        cond_trend   = ema21_[i] > ema55_[i]
        cond_pmarp   = pmarp_[i] < 18
        cond_bbwp    = bbwp_[i] < 80
        cond_bbwp_ma = (not np.isnan(bbwpm_[i])) and (not np.isnan(bbwpm_[i-1])) and (bbwpm_[i] < bbwpm_[i-1])
        cond_support = (not np.isnan(supp_[i])) and (supp_[i] < close_[i])
        cond_valid   = not any(np.isnan(x) for x in [ema21_[i], ema55_[i], pmarp_[i], bbwp_[i]])

        if cond_valid and cond_trend and cond_pmarp and cond_bbwp and cond_bbwp_ma and cond_support:
            entry_px   = open_[i+1]
            stop_level = supp_[i]
            stop_dist  = entry_px - stop_level

            if stop_dist <= 0:
                continue

            r_amt    = account * RISK_PCT
            size     = r_amt / stop_dist
            notional = size * entry_px
            leverage = notional / account

            if leverage > MAX_LEVERAGE:
                continue

            # Hard stop price = 5% account loss from this position
            hard_stop_px = entry_px - (HARD_STOP_PCT * account / size)

            in_trade      = True
            entry_price   = entry_px
            entry_support = stop_level
            pos_size      = size
            risk_amt      = r_amt
            entry_bar     = i + 1
            hard_stop     = hard_stop_px
            acct_at_entry = account

# Close any open trade at final bar
if in_trade:
    exit_px  = close_[n-1]
    pnl      = (exit_px - entry_price) * pos_size
    account += pnl
    trades.append({
        'entry_date':    dates_[entry_bar],
        'exit_date':     dates_[n-1],
        'entry_price':   entry_price,
        'exit_price':    exit_px,
        'support':       entry_support,
        'stop_distance': entry_price - entry_support,
        'pos_size_btc':  pos_size,
        'risk_amt':      risk_amt,
        'pnl_usd':       pnl,
        'pnl_pct':       pnl / acct_at_entry * 100,
        'duration_h':    n - 1 - entry_bar,
        'exit_reason':   'still_open_at_end',
        'account':       account,
    })

# ── 4. RESULTS ───────────────────────────────────────────────────────────────

if not trades:
    print("No trades generated.")
else:
    r = pd.DataFrame(trades)
    r['year'] = pd.to_datetime(r['entry_date']).dt.year
    r['win']  = r['pnl_usd'] > 0
    r['R']    = r['pnl_usd'] / r['risk_amt']

    wins   = r[r['win']]
    losses = r[~r['win']]

    # Max drawdown on account curve
    curve  = [INITIAL_BALANCE] + list(r['account'])
    peak   = INITIAL_BALANCE
    max_dd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    # Streaks
    max_w = max_l = cur_w = cur_l = 0
    for w in r['win']:
        if w:
            cur_w += 1; cur_l = 0
            max_w  = max(max_w, cur_w)
        else:
            cur_l += 1; cur_w = 0
            max_l  = max(max_l, cur_l)

    sep = "─" * 58
    print(f"\n{'═'*58}")
    print(f"  BACKTEST  ·  BTC/USDT 1H  ·  Jan 2022 → May 2026")
    print(f"{'═'*58}")
    print(f"  Starting balance    ${INITIAL_BALANCE:>10,.2f}")
    print(f"  Final balance       ${account:>10,.2f}")
    total_pct = (account / INITIAL_BALANCE - 1) * 100
    print(f"  Total return        {total_pct:>+10.1f}%")
    print(f"\n{sep}")
    print(f"  Total trades        {len(r):>10}")
    print(f"  Win rate            {len(wins)/len(r)*100:>9.1f}%")
    print(f"\n  Avg win             ${wins['pnl_usd'].mean():>10,.2f}  ({wins['pnl_pct'].mean():+.2f}%)")
    print(f"  Avg loss            ${losses['pnl_usd'].mean():>10,.2f}  ({losses['pnl_pct'].mean():+.2f}%)")
    print(f"\n  Avg win duration    {wins['duration_h'].mean():>9.1f}h")
    print(f"  Avg loss duration   {losses['duration_h'].mean():>9.1f}h")
    print(f"\n  Max win streak      {max_w:>10}")
    print(f"  Max loss streak     {max_l:>10}")
    print(f"\n  Max drawdown        {max_dd:>+9.2f}%")
    print(f"\n  Expectancy          {r['R'].mean():>+9.3f}R per trade")
    print(f"  Avg win (R)         {wins['R'].mean():>+9.2f}R")
    print(f"  Avg loss (R)        {losses['R'].mean():>+9.2f}R")
    print(f"\n{sep}")
    print(f"  Exit reasons:")
    for reason, count in r['exit_reason'].value_counts().items():
        print(f"    {reason:<28} {count:>4}")

    # Yearly breakdown
    print(f"\n{sep}")
    print(f"  Year    Trades   Win%    P&L ($)     P&L (%)")
    print(f"  {sep}")
    for year, grp in r.groupby('year'):
        yr_wins = grp[grp['win']]
        yr_pnl  = grp['pnl_usd'].sum()
        yr_start_acct = curve[r[r['year'] == year].index[0]]
        print(f"  {year}    {len(grp):>5}   {len(yr_wins)/len(grp)*100:>5.1f}%   ${yr_pnl:>+9,.2f}")

    print(f"{'═'*58}\n")

    r.to_csv('backtest_results.csv', index=False)
    print("Full trade log → backtest_results.csv")
