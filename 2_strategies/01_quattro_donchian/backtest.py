"""
Donchian Pyramid — Donchian breakout with Turtle-style pyramiding
- Entry: close > previous 20-bar high  AND  price > daily 200 EMA
- Pyramiding: add Unit 2 at +0.5N, Unit 3 at +1.0N, Unit 4 at +1.5N (max 4 units)
- Each unit risks 2% of account at original entry, sized off 2N
- N = ATR(14) at original entry, FIXED for trade duration
- Stop trails up as each unit is added: stop = newest unit entry - 2N (wick-based)
- Exit: close < previous 10-bar low (closes ALL units at next open)
- Hard stop: total trade unrealized loss reaches 5% of account (wick-based)
"""
import ccxt
import pandas as pd
import numpy as np

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

print("Fetching daily data...")
raw_d = fetch_full('BTC/USDT', '1d', since_d, exchange)
df_d = pd.DataFrame(raw_d, columns=['ts','open','high','low','close','volume'])
df_d['dt'] = pd.to_datetime(df_d['ts'], unit='ms', utc=True)
df_d = df_d.set_index('dt').drop(columns='ts')

print(f"  4H: {len(df)} candles  |  Daily: {len(df_d)} candles  |  to: {df.index[-1].date()}")

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

print("Running Donchian Pyramid backtest...")

INITIAL_BALANCE = 1839.17
RISK_PCT        = 0.02
HARD_STOP_PCT   = 0.05
ATR_MULT_STOP   = 2.0
PYRAMID_STEP    = 0.5      # add new unit every 0.5*N of favorable move
MAX_UNITS       = 4
MAX_LEVERAGE    = 20
WARMUP          = 250

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

account = INITIAL_BALANCE
trades  = []

in_trade = False
units = []                  # list of (entry_price, size, entry_bar)
original_entry = None
original_atr   = None       # N — fixed at first entry
common_stop    = None       # trails up with each pyramid addition
hard_stop      = None
acct_at_entry  = None
pending_exit   = False
pending_exit_reason = None

def total_size():
    return sum(u['size'] for u in units)

def total_notional(price):
    return sum(u['size'] * price for u in units)

def total_pnl_at(price):
    return sum((price - u['entry_price']) * u['size'] for u in units)

def close_all_units(exit_px, reason, i):
    global account, in_trade, units, original_entry, original_atr, common_stop, hard_stop, acct_at_entry
    total_pnl = total_pnl_at(exit_px)
    total_risk = len(units) * acct_at_entry * RISK_PCT
    avg_entry  = sum(u['entry_price'] * u['size'] for u in units) / total_size()
    duration   = i - units[0]['entry_bar']
    account   += total_pnl

    trades.append({
        'entry_date':       dates_[units[0]['entry_bar']],
        'exit_date':        dates_[i],
        'first_entry_price':units[0]['entry_price'],
        'avg_entry_price':  avg_entry,
        'exit_price':       exit_px,
        'num_units':        len(units),
        'total_size_btc':   total_size(),
        'original_atr':     original_atr,
        'total_risk':       total_risk,
        'first_unit_risk':  acct_at_entry * RISK_PCT,
        'pnl_usd':          total_pnl,
        'pnl_pct':          total_pnl / acct_at_entry * 100,
        'R_total':          total_pnl / (acct_at_entry * RISK_PCT),    # in units of first-unit risk
        'duration_h':       duration * 4,
        'exit_reason':      reason,
        'account':          account,
    })
    in_trade       = False
    units          = []
    original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None

for i in range(WARMUP, n - 1):

    # Execute any pending exit at this bar's open
    if pending_exit:
        close_all_units(open_[i], pending_exit_reason, i)
        pending_exit = False
        pending_exit_reason = None

    if in_trade:
        # 1) Hard 5% stop — total unrealized loss reaches 5% of account at entry (wick-based)
        worst_pnl = total_pnl_at(low_[i])
        if worst_pnl <= -HARD_STOP_PCT * acct_at_entry:
            # exit price approximated as the level where total loss = 5%
            target_loss = -HARD_STOP_PCT * acct_at_entry
            # need: sum((px - entry) * size) = target_loss
            # px * total_size - sum(entry*size) = target_loss
            wavg_entry = sum(u['entry_price'] * u['size'] for u in units) / total_size()
            exit_px    = wavg_entry + target_loss / total_size()
            close_all_units(exit_px, 'hard_stop_5pct', i)
            continue

        # 2) 2*ATR trailing stop — wick-based (low touches common_stop)
        if low_[i] <= common_stop:
            close_all_units(common_stop, 'atr_stop_trailing', i)
            continue

        # 3) Pyramiding — add new units if price reached next trigger (intrabar via bar high)
        while len(units) < MAX_UNITS:
            next_trigger = original_entry + PYRAMID_STEP * len(units) * original_atr
            if high_[i] < next_trigger:
                break
            # add new unit at the trigger price
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

            # Recalc hard stop level so total loss = 5% of acct_at_entry
            # Find price P where: sum((P - entry_k) * size_k) = -5% * acct
            # P = (target_loss + sum(entry*size)) / total_size
            target_loss   = -HARD_STOP_PCT * acct_at_entry
            wavg_entry    = sum(u['entry_price'] * u['size'] for u in units) / total_size()
            hard_stop     = wavg_entry + target_loss / total_size()

        # 4) Donchian trailing exit — close < 10-bar low
        if close_[i] < dlow_[i]:
            pending_exit        = True
            pending_exit_reason = 'donchian_exit'
            continue

    else:
        if np.isnan(dhigh_[i]) or np.isnan(atr_[i]) or np.isnan(reg_[i]):
            continue
        if close_[i] > dhigh_[i] and reg_[i]:
            entry_px  = open_[i+1]
            N         = atr_[i]                  # ATR at signal bar — fixed for whole trade
            stop_px   = entry_px - 2 * N
            if entry_px - stop_px <= 0:
                continue

            r_amt   = account * RISK_PCT
            size    = r_amt / (2 * N)
            leverage = (size * entry_px) / account
            if leverage > MAX_LEVERAGE:
                continue

            in_trade       = True
            original_entry = entry_px
            original_atr   = N
            acct_at_entry  = account
            common_stop    = stop_px
            units          = [{'entry_price': entry_px, 'size': size, 'entry_bar': i + 1}]
            # initial hard stop: price where Unit 1 loses 5% of account
            hard_stop      = entry_px - (HARD_STOP_PCT * account / size)

if in_trade:
    close_all_units(close_[n-1], 'still_open_at_end', n-1)

# -- RESULTS -------------------------------------------------------------------

TRENDv1 = {'name':'Donchian (no pyr)','trades':89,'wr':32.6,'avg_win_R':3.39,
           'avg_loss_R':-0.83,'expectancy':0.542,'max_dd':-15.42,'final':4166.71,
           'max_w':3,'max_l':7,'biggest':19.54}

if not trades:
    print("No trades.")
else:
    r = pd.DataFrame(trades)
    r['year'] = pd.to_datetime(r['entry_date']).dt.year
    r['win']  = r['pnl_usd'] > 0
    r['R']    = r['R_total']
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

    sep = "-" * 80
    print(f"\n{'='*80}")
    print(f"  STRATEGY:  Donchian Pyramid")
    print(f"  BTC/USDT 4H   Jan 2022 to {df.index[-1].date()}   start ${INITIAL_BALANCE:,.2f}")
    print(f"{'='*80}")
    print(f"{'':30}{TRENDv1['name']:>22}{'Donchian Pyramid':>22}")
    print(sep)
    print(f"  {'Total trades':<28}{TRENDv1['trades']:>22}{len(r):>22}")
    print(f"  {'Win rate %':<28}{TRENDv1['wr']:>22.1f}{len(wins)/len(r)*100:>22.1f}")
    print(f"  {'Avg win (R)':<28}{TRENDv1['avg_win_R']:>+22.2f}{wins['R'].mean():>+22.2f}")
    print(f"  {'Avg loss (R)':<28}{TRENDv1['avg_loss_R']:>+22.2f}{losses['R'].mean():>+22.2f}")
    print(f"  {'Expectancy (R)':<28}{TRENDv1['expectancy']:>+22.3f}{r['R'].mean():>+22.3f}")
    print(f"  {'Max drawdown %':<28}{TRENDv1['max_dd']:>+22.2f}{max_dd:>+22.2f}")
    print(f"  {'Max winning streak':<28}{TRENDv1['max_w']:>22}{max_w:>22}")
    print(f"  {'Max losing streak':<28}{TRENDv1['max_l']:>22}{max_l:>22}")
    print(f"  {'Final balance ($)':<28}${TRENDv1['final']:>21,.2f}${account:>21,.2f}")
    print(f"  {'Total return %':<28}{(TRENDv1['final']/INITIAL_BALANCE-1)*100:>+22.1f}{(account/INITIAL_BALANCE-1)*100:>+22.1f}")
    print(f"  {'Biggest winner (R)':<28}{TRENDv1['biggest']:>+22.2f}{wins['R'].max():>+22.2f}")
    print(f"  {'Avg units per trade':<28}{1.0:>22.2f}{r['num_units'].mean():>22.2f}")

    print(f"\n{sep}")
    print(f"  PYRAMID UNIT DISTRIBUTION")
    print(sep)
    for u, count in r['num_units'].value_counts().sort_index().items():
        grp = r[r['num_units'] == u]
        wr  = len(grp[grp['win']]) / len(grp) * 100
        avgR = grp['R'].mean()
        print(f"    {u} unit(s): {count:>4} trades   {wr:>5.1f}% win   avg R: {avgR:+.3f}")

    print(f"\n{sep}")
    print(f"  EXIT REASONS")
    print(sep)
    for reason, count in r['exit_reason'].value_counts().items():
        grp  = r[r['exit_reason'] == reason]
        wr   = len(grp[grp['win']]) / len(grp) * 100
        avgR = grp['R'].mean()
        print(f"    {reason:<22} {count:>4} trades   {wr:>5.1f}% win   avg R: {avgR:+.3f}")

    print(f"\n{sep}")
    print(f"  YEAR-BY-YEAR")
    print(sep)
    print(f"  Year  Trades  Win%      P&L ($)   Expectancy   Biggest R   Avg units")
    for yr, grp in r.groupby('year'):
        yw   = grp[grp['win']]
        bigW = grp['R'].max() if len(grp) > 0 else 0
        print(f"  {yr}   {len(grp):>5}  {len(yw)/len(grp)*100 if len(grp) else 0:>5.1f}%   ${grp['pnl_usd'].sum():>+9,.2f}      {grp['R'].mean():>+.3f}R      {bigW:+.2f}R      {grp['num_units'].mean():.2f}")

    print(f"\n{sep}")
    print(f"  R DISTRIBUTION")
    print(sep)
    buckets = [-99,-5,-3,-2,-1,-0.5,0,0.5,1,2,3,5,10,99]
    labels  = ['<-5','-5 to -3','-3 to -2','-2 to -1','-1 to -0.5','-0.5 to 0',
               '0 to 0.5','0.5 to 1','1 to 2','2 to 3','3 to 5','5 to 10','>10']
    r['bucket'] = pd.cut(r['R'], bins=buckets, labels=labels)
    for lbl, count in r['bucket'].value_counts().sort_index().items():
        bar = '#' * count
        print(f"    {lbl:<14} {count:>4}  {bar}")

    print(f"\n{'='*80}\n")
    r.to_csv('backtest_donchian_pyramid_results.csv', index=False)
    print("Trade log -> backtest_donchian_pyramid_results.csv")
