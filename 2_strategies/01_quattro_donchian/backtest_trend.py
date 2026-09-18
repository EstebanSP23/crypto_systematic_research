"""
Donchian Breakout — classic trend-following on BTC 4H
- Entry: close > previous 20-bar high  AND  price > daily 200 EMA
- Exit:  close < previous 10-bar low   (trailing)
- Stop:  entry - 2*ATR(14)             (volatility-adjusted catastrophe stop)
- Risk:  2% per trade
- Hard stop backup: 5% account loss
"""
import ccxt
import pandas as pd
import numpy as np

# ── DATA ──────────────────────────────────────────────────────────────────────

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
since_d  = exchange.parse8601('2021-01-01T00:00:00Z')   # extra year for 200 EMA warmup

print("Fetching 4H data...")
raw_4h = fetch_full('BTC/USDT', '4h', since, exchange)
df = pd.DataFrame(raw_4h, columns=['ts','open','high','low','close','volume'])
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts')

print("Fetching daily data (for 200 EMA regime filter)...")
raw_d = fetch_full('BTC/USDT', '1d', since_d, exchange)
df_d = pd.DataFrame(raw_d, columns=['ts','open','high','low','close','volume'])
df_d['dt'] = pd.to_datetime(df_d['ts'], unit='ms', utc=True)
df_d = df_d.set_index('dt').drop(columns='ts')

print(f"  4H: {len(df)} candles  |  Daily: {len(df_d)} candles")

# ── INDICATORS ────────────────────────────────────────────────────────────────

print("Calculating indicators...")

# Donchian channel — previous N bars (excluding current) using shift(1)
df['donch_high_20'] = df['high'].rolling(20).max().shift(1)
df['donch_low_10']  = df['low'].rolling(10).min().shift(1)

# ATR(14) — Wilder's smoothing
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low']  - df['close'].shift(1)).abs(),
], axis=1).max(axis=1)
df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()

# Daily 200 EMA aligned to 4H without lookahead
df_d['ema200'] = df_d['close'].ewm(span=200, adjust=False).mean()
df_d_avail        = df_d[['ema200']].copy()
df_d_avail.index  = df_d_avail.index + pd.Timedelta(days=1)   # available after daily close
df_d_aligned      = df_d_avail.reindex(df.index, method='ffill')
df['d_ema200']    = df_d_aligned['ema200']
df['regime_up']   = df['close'] > df['d_ema200']

# ── BACKTEST ──────────────────────────────────────────────────────────────────

print("Running Donchian breakout backtest...")

INITIAL_BALANCE = 1839.17
RISK_PCT        = 0.02
HARD_STOP_PCT   = 0.05
ATR_MULT_STOP   = 2.0
MAX_LEVERAGE    = 20
WARMUP          = 250   # enough for 200 daily EMA and 20-bar Donchian

open_  = df['open'].values
high_  = df['high'].values
low_   = df['low'].values
close_ = df['close'].values
dhigh_ = df['donch_high_20'].values
dlow_  = df['donch_low_10'].values
atr_   = df['atr14'].values
reg_   = df['regime_up'].values
dates_ = df.index
n      = len(df)

account             = INITIAL_BALANCE
trades              = []
in_trade            = False
entry_price         = atr_stop = pos_size = risk_amt = None
entry_bar           = hard_stop = acct_at_entry = None
pending_exit        = False
pending_exit_reason = None

for i in range(WARMUP, n - 1):

    # Execute pending exit
    if pending_exit:
        exit_px  = open_[i]
        pnl      = (exit_px - entry_price) * pos_size
        account += pnl
        trades.append({
            'entry_date':  dates_[entry_bar], 'exit_date': dates_[i],
            'entry_price': entry_price,        'exit_price': exit_px,
            'atr_stop':    atr_stop,           'stop_distance': entry_price - atr_stop,
            'pos_size_btc':pos_size,           'risk_amt':   risk_amt,
            'pnl_usd':     pnl,                'pnl_pct':    pnl / acct_at_entry * 100,
            'duration_h':  (i - entry_bar) * 4,
            'exit_reason': pending_exit_reason,
            'account':     account,
        })
        in_trade = False
        pending_exit = False
        pending_exit_reason = None

    if in_trade:
        # Hard stop (5% account) intrabar
        if low_[i] <= hard_stop:
            exit_px  = hard_stop
            pnl      = (exit_px - entry_price) * pos_size
            account += pnl
            trades.append({
                'entry_date':  dates_[entry_bar], 'exit_date': dates_[i],
                'entry_price': entry_price,        'exit_price': exit_px,
                'atr_stop':    atr_stop,           'stop_distance': entry_price - atr_stop,
                'pos_size_btc':pos_size,           'risk_amt':   risk_amt,
                'pnl_usd':     pnl,                'pnl_pct':    pnl / acct_at_entry * 100,
                'duration_h':  (i - entry_bar) * 4,
                'exit_reason': 'hard_stop_5pct',
                'account':     account,
            })
            in_trade = False
            continue

        # ATR catastrophe stop intrabar
        if low_[i] <= atr_stop:
            exit_px  = atr_stop
            pnl      = (exit_px - entry_price) * pos_size
            account += pnl
            trades.append({
                'entry_date':  dates_[entry_bar], 'exit_date': dates_[i],
                'entry_price': entry_price,        'exit_price': exit_px,
                'atr_stop':    atr_stop,           'stop_distance': entry_price - atr_stop,
                'pos_size_btc':pos_size,           'risk_amt':   risk_amt,
                'pnl_usd':     pnl,                'pnl_pct':    pnl / acct_at_entry * 100,
                'duration_h':  (i - entry_bar) * 4,
                'exit_reason': 'atr_stop',
                'account':     account,
            })
            in_trade = False
            continue

        # Trailing exit — close below 10-bar low
        if close_[i] < dlow_[i]:
            pending_exit        = True
            pending_exit_reason = 'donchian_exit'
            continue

    else:
        if np.isnan(dhigh_[i]) or np.isnan(atr_[i]) or np.isnan(reg_[i]):
            continue

        # Entry conditions
        if close_[i] > dhigh_[i] and reg_[i]:
            entry_px  = open_[i+1]
            stop_px   = entry_px - ATR_MULT_STOP * atr_[i]
            stop_dist = entry_px - stop_px
            if stop_dist <= 0:
                continue

            r_amt = account * RISK_PCT
            size  = r_amt / stop_dist
            leverage = (size * entry_px) / account
            if leverage > MAX_LEVERAGE:
                continue

            in_trade      = True
            entry_price   = entry_px
            atr_stop      = stop_px
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
        'entry_date': dates_[entry_bar], 'exit_date': dates_[n-1],
        'entry_price': entry_price,       'exit_price': exit_px,
        'atr_stop': atr_stop,             'stop_distance': entry_price - atr_stop,
        'pos_size_btc': pos_size,         'risk_amt': risk_amt,
        'pnl_usd': pnl,                   'pnl_pct': pnl / acct_at_entry * 100,
        'duration_h': (n - 1 - entry_bar) * 4,
        'exit_reason': 'still_open_at_end',
        'account': account,
    })

# ── RESULTS ────────────────────────────────────────────────────────────────────

# Reference stats from previous backtests
V1 = {'trades':269,'wr':63.9,'avg_win_R':0.52,'avg_loss_R':-0.78,
      'expectancy':0.052,'max_dd':-19.86,'final':2345.10,
      'max_w':13,'max_l':5,'name':'v1 mean-rev'}
V2 = {'trades':222,'wr':64.9,'avg_win_R':0.52,'avg_loss_R':-0.78,
      'expectancy':0.061,'max_dd':-16.27,'final':2341.16,
      'max_w':10,'max_l':4,'name':'v2 +4H filter'}

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
        if w: cur_w += 1; cur_l = 0; max_w = max(max_w, cur_w)
        else: cur_l += 1; cur_w = 0; max_l = max(max_l, cur_l)

    sep = "-" * 78
    print(f"\n{'='*78}")
    print(f"  STRATEGY COMPARISON   BTC 1H/4H   Jan 2022 to May 2026")
    print(f"{'='*78}")
    print(f"{'':30}{V1['name']:>14}{V2['name']:>14}{'TREND (Donchian)':>18}")
    print(sep)

    def row(label, v1, v2, v3, fmt='{:.2f}'):
        print(f"  {label:<28}{fmt.format(v1):>14}{fmt.format(v2):>14}{fmt.format(v3):>18}")

    print(f"  {'Total trades':<28}{V1['trades']:>14}{V2['trades']:>14}{len(r):>18}")
    print(f"  {'Win rate %':<28}{V1['wr']:>14.1f}{V2['wr']:>14.1f}{len(wins)/len(r)*100:>18.1f}")
    print(f"  {'Avg win (R)':<28}{V1['avg_win_R']:>+14.2f}{V2['avg_win_R']:>+14.2f}{wins['R'].mean():>+18.2f}")
    print(f"  {'Avg loss (R)':<28}{V1['avg_loss_R']:>+14.2f}{V2['avg_loss_R']:>+14.2f}{losses['R'].mean():>+18.2f}")
    print(f"  {'Expectancy (R)':<28}{V1['expectancy']:>+14.3f}{V2['expectancy']:>+14.3f}{r['R'].mean():>+18.3f}")
    print(f"  {'Max drawdown %':<28}{V1['max_dd']:>+14.2f}{V2['max_dd']:>+14.2f}{max_dd:>+18.2f}")
    print(f"  {'Max winning streak':<28}{V1['max_w']:>14}{V2['max_w']:>14}{max_w:>18}")
    print(f"  {'Max losing streak':<28}{V1['max_l']:>14}{V2['max_l']:>14}{max_l:>18}")
    print(f"  {'Final balance ($)':<28}{V1['final']:>14,.2f}{V2['final']:>14,.2f}{account:>18,.2f}")
    print(f"  {'Total return %':<28}{(V1['final']/INITIAL_BALANCE-1)*100:>+14.1f}{(V2['final']/INITIAL_BALANCE-1)*100:>+14.1f}{(account/INITIAL_BALANCE-1)*100:>+18.1f}")
    print(f"  {'Biggest winner (R)':<28}{'?':>14}{'?':>14}{wins['R'].max():>+18.2f}")

    print(f"\n{sep}")
    print(f"  TREND-STRATEGY EXIT REASONS")
    print(sep)
    for reason, count in r['exit_reason'].value_counts().items():
        grp = r[r['exit_reason'] == reason]
        wr  = len(grp[grp['win']]) / len(grp) * 100
        avgR = grp['R'].mean()
        print(f"    {reason:<24} {count:>4} trades   {wr:>5.1f}% win   avg R: {avgR:+.3f}")

    print(f"\n{sep}")
    print(f"  TREND-STRATEGY YEAR-BY-YEAR")
    print(sep)
    print(f"  Year   Trades   Win%      P&L ($)   Expectancy   Biggest winner")
    for yr, grp in r.groupby('year'):
        yw   = grp[grp['win']]
        bigW = grp['R'].max() if len(grp) > 0 else 0
        print(f"  {yr}    {len(grp):>5}   {len(yw)/len(grp)*100 if len(grp) else 0:>5.1f}%   ${grp['pnl_usd'].sum():>+9,.2f}      {grp['R'].mean():>+.3f}R       {bigW:+.2f}R")

    print(f"\n{sep}")
    print(f"  R DISTRIBUTION   (TREND)")
    print(sep)
    buckets = [-99,-2,-1,-0.5,0,0.5,1,2,3,5,99]
    labels  = ['<-2','-2 to -1','-1 to -0.5','-0.5 to 0','0 to 0.5','0.5 to 1','1 to 2','2 to 3','3 to 5','>5']
    r['bucket'] = pd.cut(r['R'], bins=buckets, labels=labels)
    for lbl, count in r['bucket'].value_counts().sort_index().items():
        bar = '#' * count
        print(f"    {lbl:<14} {count:>4}  {bar}")

    print(f"\n{'='*78}\n")

    r.to_csv('backtest_trend_results.csv', index=False)
    print("Trade log -> backtest_trend_results.csv")
