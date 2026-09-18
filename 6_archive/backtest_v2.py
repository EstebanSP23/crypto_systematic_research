import ccxt
import pandas as pd
import numpy as np

# ── 1. DATA ──────────────────────────────────────────────────────────────────

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

print("Fetching 1H data...")
raw_1h = fetch_full('BTC/USDT', '1h', since, exchange)
df = pd.DataFrame(raw_1h, columns=['ts','open','high','low','close','volume'])
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts')

print("Fetching 4H data...")
raw_4h = fetch_full('BTC/USDT', '4h', since, exchange)
df4 = pd.DataFrame(raw_4h, columns=['ts','open','high','low','close','volume'])
df4['dt'] = pd.to_datetime(df4['ts'], unit='ms', utc=True)
df4 = df4.set_index('dt').drop(columns='ts')

print(f"  1H: {len(df)} candles  |  4H: {len(df4)} candles")

# ── 2. INDICATORS ─────────────────────────────────────────────────────────────

print("Calculating indicators...")

# 1H indicators (same as v1)
df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
df['ema55'] = df['close'].ewm(span=55, adjust=False).mean()
df['ema13'] = df['close'].ewm(span=13, adjust=False).mean()
df['pmar']  = (df['close'] / df['ema13']).abs()

pmar = df['pmar'].values
pmarp = np.full(len(df), np.nan)
for i in range(300, len(df)):
    h = pmar[i-300:i]
    pmarp[i] = np.sum(h <= pmar[i]) / 300 * 100
df['pmarp'] = pmarp

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

print("  Detecting 1H pivot lows (15/15)...")
lows = df['low'].values
n    = len(df)
pivot_raw = np.full(n, np.nan)
for i in range(15, n - 15):
    li = lows[i]
    if (li < lows[i-15:i]).all() and (li < lows[i+1:i+16]).all():
        pivot_raw[i + 15] = li
df['support'] = pd.Series(pivot_raw, index=df.index).ffill().shift(1)

# ── 4H trend filter ───────────────────────────────────────────────────────────
# A 4H bar with open_time T closes at T+4h.
# Its EMA values are available for use AFTER T+4h.
# We shift the 4H index forward by 4h to represent availability time,
# then forward-fill into the 1H index — no lookahead.

df4['ema21_4h'] = df4['close'].ewm(span=21, adjust=False).mean()
df4['ema55_4h'] = df4['close'].ewm(span=55, adjust=False).mean()

df4_avail        = df4[['ema21_4h','ema55_4h']].copy()
df4_avail.index  = df4_avail.index + pd.Timedelta(hours=4)

df4_aligned      = df4_avail.reindex(df.index, method='ffill')
df['ema21_4h']   = df4_aligned['ema21_4h']
df['ema55_4h']   = df4_aligned['ema55_4h']
df['trend_4h']   = df['ema21_4h'] > df['ema55_4h']

# ── 3. BACKTEST ───────────────────────────────────────────────────────────────

print("Running backtest with 4H trend filter...")

INITIAL_BALANCE = 1839.17
RISK_PCT        = 0.02
HARD_STOP_PCT   = 0.05
MAX_LEVERAGE    = 20
WARMUP          = 400

open_   = df['open'].values
high_   = df['high'].values
low_    = df['low'].values
close_  = df['close'].values
ema21_  = df['ema21'].values
ema55_  = df['ema55'].values
pmarp_  = df['pmarp'].values
bbwp_   = df['bbwp'].values
bbwpm_  = df['bbwp_ma'].values
supp_   = df['support'].values
t4h_    = df['trend_4h'].values
dates_  = df.index

account       = INITIAL_BALANCE
trades        = []
in_trade      = False
entry_price   = entry_support = pos_size = risk_amt = None
entry_bar     = hard_stop = acct_at_entry = None
pending_exit  = False
pending_exit_reason = None

for i in range(WARMUP, n - 1):

    if pending_exit:
        exit_px  = open_[i]
        pnl      = (exit_px - entry_price) * pos_size
        account += pnl
        trades.append({
            'entry_date':  dates_[entry_bar], 'exit_date':   dates_[i],
            'entry_price': entry_price,        'exit_price':  exit_px,
            'support':     entry_support,      'stop_distance': entry_price - entry_support,
            'pos_size_btc':pos_size,           'risk_amt':    risk_amt,
            'pnl_usd':     pnl,                'pnl_pct':     pnl / acct_at_entry * 100,
            'duration_h':  i - entry_bar,      'exit_reason': pending_exit_reason,
            'account':     account,
        })
        in_trade = False
        pending_exit = False
        pending_exit_reason = None

    if in_trade:
        if low_[i] <= hard_stop:
            exit_px  = hard_stop
            pnl      = (exit_px - entry_price) * pos_size
            account += pnl
            trades.append({
                'entry_date':  dates_[entry_bar], 'exit_date':   dates_[i],
                'entry_price': entry_price,        'exit_price':  exit_px,
                'support':     entry_support,      'stop_distance': entry_price - entry_support,
                'pos_size_btc':pos_size,           'risk_amt':    risk_amt,
                'pnl_usd':     pnl,                'pnl_pct':     pnl / acct_at_entry * 100,
                'duration_h':  i - entry_bar,      'exit_reason': 'hard_stop_5pct',
                'account':     account,
            })
            in_trade = False
            continue

        if close_[i] < supp_[i]:
            pending_exit = True
            pending_exit_reason = 'stop_loss'
            continue

        if pmarp_[i] > 77:
            pending_exit = True
            pending_exit_reason = 'take_profit'
            continue

    else:
        any_nan = any(np.isnan(x) for x in [ema21_[i], ema55_[i], pmarp_[i], bbwp_[i]])
        if any_nan:
            continue

        cond_trend_1h = ema21_[i] > ema55_[i]
        cond_trend_4h = bool(t4h_[i])          # NEW: 4H EMA 21 > EMA 55
        cond_pmarp    = pmarp_[i] < 18
        cond_bbwp     = bbwp_[i] < 80
        cond_bbwp_ma  = (not np.isnan(bbwpm_[i])) and (not np.isnan(bbwpm_[i-1])) and (bbwpm_[i] < bbwpm_[i-1])
        cond_support  = (not np.isnan(supp_[i])) and (supp_[i] < close_[i])

        if cond_trend_1h and cond_trend_4h and cond_pmarp and cond_bbwp and cond_bbwp_ma and cond_support:
            entry_px  = open_[i+1]
            stop_dist = entry_px - supp_[i]
            if stop_dist <= 0:
                continue

            r_amt    = account * RISK_PCT
            size     = r_amt / stop_dist
            leverage = (size * entry_px) / account
            if leverage > MAX_LEVERAGE:
                continue

            in_trade      = True
            entry_price   = entry_px
            entry_support = supp_[i]
            pos_size      = size
            risk_amt      = r_amt
            entry_bar     = i + 1
            hard_stop     = entry_px - (HARD_STOP_PCT * account / size)
            acct_at_entry = account

if in_trade:
    exit_px = close_[n-1]
    pnl     = (exit_px - entry_price) * pos_size
    account += pnl
    trades.append({
        'entry_date': dates_[entry_bar], 'exit_date':  dates_[n-1],
        'entry_price': entry_price,       'exit_price': exit_px,
        'support': entry_support,         'stop_distance': entry_price - entry_support,
        'pos_size_btc': pos_size,         'risk_amt': risk_amt,
        'pnl_usd': pnl,                   'pnl_pct': pnl / acct_at_entry * 100,
        'duration_h': n - 1 - entry_bar,  'exit_reason': 'still_open_at_end',
        'account': account,
    })

# ── 4. RESULTS ────────────────────────────────────────────────────────────────

V1 = { 'trades':269,'wr':63.9,'avg_win_R':0.52,'avg_loss_R':-0.78,
        'expectancy':0.052,'max_dd':-19.86,'final':2345.10 }

if not trades:
    print("No trades generated.")
else:
    r = pd.DataFrame(trades)
    r['year'] = pd.to_datetime(r['entry_date']).dt.year
    r['win']  = r['pnl_usd'] > 0
    r['R']    = r['pnl_usd'] / r['risk_amt']
    wins      = r[r['win']]
    losses    = r[~r['win']]

    curve  = [INITIAL_BALANCE] + list(r['account'])
    peak   = INITIAL_BALANCE
    max_dd = 0.0
    for v in curve:
        if v > peak: peak = v
        dd = (v - peak) / peak * 100
        if dd < max_dd: max_dd = dd

    max_w = max_l = cur_w = cur_l = 0
    for w in r['win']:
        if w:
            cur_w += 1; cur_l = 0; max_w = max(max_w, cur_w)
        else:
            cur_l += 1; cur_w = 0; max_l = max(max_l, cur_l)

    sep = "-" * 58
    print(f"\n{'='*58}")
    print(f"  BACKTEST v2  -  4H TREND FILTER ADDED")
    print(f"  BTC/USDT 1H  -  Jan 2022 to May 2026")
    print(f"{'='*58}")
    print(f"{'':30}{'v1':>10}{'v2':>10}")
    print(sep)
    print(f"{'Total trades':<30}{V1['trades']:>10}{len(r):>10}")
    print(f"{'Win rate':<30}{V1['wr']:>9.1f}%{len(wins)/len(r)*100:>9.1f}%")
    print(f"{'Avg win (R)':<30}{V1['avg_win_R']:>+10.2f}{wins['R'].mean():>+10.2f}")
    print(f"{'Avg loss (R)':<30}{V1['avg_loss_R']:>+10.2f}{losses['R'].mean():>+10.2f}")
    print(f"{'Expectancy (R)':<30}{V1['expectancy']:>+10.3f}{r['R'].mean():>+10.3f}")
    print(f"{'Max drawdown':<30}{V1['max_dd']:>+9.2f}%{max_dd:>+9.2f}%")
    print(f"{'Max win streak':<30}{'13':>10}{max_w:>10}")
    print(f"{'Max loss streak':<30}{'5':>10}{max_l:>10}")
    print(f"{'Final balance':<30}${V1['final']:>9,.2f}${account:>9,.2f}")
    print(f"{'Total return':<30}{(V1['final']/INITIAL_BALANCE-1)*100:>+9.1f}%{(account/INITIAL_BALANCE-1)*100:>+9.1f}%")
    print(f"\n{sep}")
    print(f"  Exit reasons:")
    for reason, count in r['exit_reason'].value_counts().items():
        print(f"    {reason:<28} {count:>4}")
    print(f"\n{sep}")
    print(f"  Year    Trades   Win%    P&L ($)   Expectancy")
    print(sep)
    for yr, grp in r.groupby('year'):
        yw = grp[grp['win']]
        print(f"  {yr}    {len(grp):>5}   {len(yw)/len(grp)*100:>5.1f}%   ${grp['pnl_usd'].sum():>+8,.2f}   {grp['R'].mean():>+.3f}R")
    print(f"{'='*58}\n")

    r.to_csv('backtest_v2_results.csv', index=False)
    print("Full trade log -> backtest_v2_results.csv")
